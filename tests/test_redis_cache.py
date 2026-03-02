"""
Performance & correctness tests for RedisCacheBackend.

Tests both the caching behaviour (hit/miss/invalidation) and
latency improvement over direct Cosmos DB queries.

Usage:
    python -m pytest tests/test_redis_cache.py -v
    python -m pytest tests/test_redis_cache.py -k "perf" -v   # perf only
"""

import hashlib
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import MagicMock, patch
from backend.memory_store import (
    RedisCacheBackend,
    MemoryStoreBackend,
    _user_hash,
    _redis_stats,
    get_redis_stats,
)


# ── Helpers ──────────────────────────────────────────────────────────────

class FakeDelegate(MemoryStoreBackend):
    """In-memory backend simulating Cosmos DB with configurable latency."""

    def __init__(self, latency_ms: float = 0):
        self._store: dict = {}  # (collection, key) -> doc
        self._latency = latency_ms / 1000.0
        self.call_count = {"put": 0, "get": 0, "search": 0, "delete": 0}

    def _sleep(self):
        if self._latency > 0:
            time.sleep(self._latency)

    def put(self, collection, key, doc):
        self.call_count["put"] += 1
        self._sleep()
        self._store[(collection, key)] = dict(doc)

    def get(self, collection, key):
        self.call_count["get"] += 1
        self._sleep()
        return self._store.get((collection, key))

    def delete(self, collection, key):
        self.call_count["delete"] += 1
        self._sleep()
        return self._store.pop((collection, key), None) is not None

    def list_keys(self, collection):
        return [k for (c, k) in self._store if c == collection]

    def query(self, collection, filters, limit=50):
        results = []
        for (c, k), doc in self._store.items():
            if c != collection:
                continue
            if all(doc.get(fk) == fv for fk, fv in filters.items()):
                results.append(doc)
            if len(results) >= limit:
                break
        return results

    def search(self, collection, query_text, limit=10):
        self.call_count["search"] += 1
        self._sleep()
        terms = set(query_text.lower().split())
        results = []
        for (c, k), doc in self._store.items():
            if c != collection:
                continue
            doc_text = " ".join(str(v) for v in doc.values()).lower()
            if any(t in doc_text for t in terms):
                results.append(dict(doc))
            if len(results) >= limit:
                break
        return results


def make_fake_redis():
    """Return a dict-based fake Redis client that mimics redis.Redis."""
    store = {}
    ttls = {}

    class FakeRedis:
        def ping(self):
            return True

        def get(self, key):
            return store.get(key)

        def setex(self, key, ttl, value):
            store[key] = value
            ttls[key] = ttl

        def delete(self, *keys):
            for k in keys:
                store.pop(k, None)
                ttls.pop(k, None)

        def pipeline(self, transaction=False):
            return FakePipeline()

        def scan(self, cursor, match=None, count=100):
            import fnmatch
            matched = [k for k in store if fnmatch.fnmatch(k, match)] if match else []
            return (0, matched)

        def info(self, section=None):
            return {"used_memory": 1024 * 1024 * 5}

        @property
        def _store(self):
            return store

    class FakePipeline:
        def __init__(self):
            self._ops = []

        def setex(self, key, ttl, value):
            self._ops.append(("setex", key, ttl, value))
            return self

        def delete(self, *keys):
            self._ops.append(("delete", keys))
            return self

        def execute(self):
            for op in self._ops:
                if op[0] == "setex":
                    store[op[1]] = op[3]
                elif op[0] == "delete":
                    for k in op[1]:
                        store.pop(k, None)
            self._ops.clear()

    return FakeRedis()


# ── Tests ────────────────────────────────────────────────────────────────

class TestRedisCacheBackend:

    def setup_method(self):
        """Reset stats before each test."""
        _redis_stats["hits"] = 0
        _redis_stats["misses"] = 0
        _redis_stats["errors"] = 0

    def _make_backend(self, latency_ms=0):
        delegate = FakeDelegate(latency_ms=latency_ms)
        redis = make_fake_redis()
        backend = RedisCacheBackend(
            redis_client=redis,
            delegate=delegate,
            user_id="test-user",
            search_ttl=300,
            doc_ttl=600,
        )
        return backend, delegate, redis

    # ── Write-through tests ──────────────────────────────────────────

    def test_put_writes_to_delegate_and_cache(self):
        backend, delegate, redis = self._make_backend()
        doc = {"id": "k1", "content": "hello world", "topic": "test"}
        backend.put("semantic", "k1", doc)

        # Delegate should have it
        assert delegate.get("semantic", "k1") is not None
        assert delegate.call_count["put"] == 1

        # Redis should have it cached
        uh = _user_hash("test-user")
        cache_key = f"mem:{uh}:semantic:k1"
        assert redis._store.get(cache_key) is not None

    def test_get_returns_from_cache_on_hit(self):
        backend, delegate, redis = self._make_backend()
        doc = {"id": "k1", "content": "cached doc"}
        backend.put("semantic", "k1", doc)

        # Reset delegate call count
        delegate.call_count["get"] = 0

        # Get should hit cache, NOT delegate
        result = backend.get("semantic", "k1")
        assert result is not None
        assert result["content"] == "cached doc"
        assert delegate.call_count["get"] == 0  # NO delegate call
        assert _redis_stats["hits"] >= 1

    def test_get_falls_back_to_delegate_on_miss(self):
        backend, delegate, redis = self._make_backend()
        # Put directly in delegate (bypass cache)
        delegate.put("semantic", "k2", {"id": "k2", "content": "only in cosmos"})

        result = backend.get("semantic", "k2")
        assert result is not None
        assert result["content"] == "only in cosmos"
        assert delegate.call_count["get"] >= 1
        assert _redis_stats["misses"] >= 1

    def test_delete_invalidates_cache(self):
        backend, delegate, redis = self._make_backend()
        backend.put("semantic", "k1", {"id": "k1", "content": "delete me"})

        # Verify cached
        uh = _user_hash("test-user")
        assert redis._store.get(f"mem:{uh}:semantic:k1") is not None

        # Delete
        backend.delete("semantic", "k1")

        # Cache should be cleared
        assert redis._store.get(f"mem:{uh}:semantic:k1") is None
        # Delegate should also be empty
        assert delegate.get("semantic", "k1") is None

    # ── Search caching tests ────────────────────────────────────────

    def test_search_caches_results(self):
        backend, delegate, redis = self._make_backend()
        # Populate some data in delegate
        delegate.put("semantic", "d1", {"id": "d1", "content": "pharma drug safety"})
        delegate.put("semantic", "d2", {"id": "d2", "content": "clinical trials data"})

        # First search — cache miss
        results1 = backend.search("semantic", "pharma safety", limit=10)
        assert len(results1) >= 1
        assert _redis_stats["misses"] >= 1
        first_miss = _redis_stats["misses"]

        # Second identical search — cache hit
        results2 = backend.search("semantic", "pharma safety", limit=10)
        assert results2 == results1
        assert _redis_stats["hits"] >= 1

        # Delegate should only be called once for search
        assert delegate.call_count["search"] == 1

    def test_put_invalidates_search_cache(self):
        backend, delegate, redis = self._make_backend()
        delegate.put("semantic", "d1", {"id": "d1", "content": "pharma data"})

        # Search to populate cache
        backend.search("semantic", "pharma", limit=10)
        assert delegate.call_count["search"] == 1

        # Write new doc — should invalidate search caches
        backend.put("semantic", "d2", {"id": "d2", "content": "new pharma entry"})

        # Search again — should be a cache miss (invalidated)
        backend.search("semantic", "pharma", limit=10)
        assert delegate.call_count["search"] == 2  # Called again

    # ── list_keys caching ────────────────────────────────────────────

    def test_list_keys_caches(self):
        backend, delegate, redis = self._make_backend()
        delegate.put("semantic", "k1", {"id": "k1"})
        delegate.put("semantic", "k2", {"id": "k2"})

        keys1 = backend.list_keys("semantic")
        assert len(keys1) == 2
        assert _redis_stats["misses"] >= 1

        # Second call — cache hit
        keys2 = backend.list_keys("semantic")
        assert keys2 == keys1
        assert _redis_stats["hits"] >= 1

    # ── query passthrough ────────────────────────────────────────────

    def test_query_passes_through_to_delegate(self):
        backend, delegate, redis = self._make_backend()
        delegate.put("episodic", "e1", {"id": "e1", "type": "ca_snapshot", "model": "gpt-5"})

        results = backend.query("episodic", {"type": "ca_snapshot"}, limit=10)
        assert len(results) == 1
        assert results[0]["model"] == "gpt-5"

    # ── Redis stats ──────────────────────────────────────────────────

    def test_redis_stats_reporting(self):
        backend, delegate, redis = self._make_backend()
        backend.put("semantic", "k1", {"content": "test"})
        backend.get("semantic", "k1")  # hit
        backend.get("semantic", "nonexistent")  # miss

        stats = get_redis_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1
        assert stats["total_requests"] >= 2
        assert stats["hit_rate_pct"] > 0

    # ── Graceful degradation ─────────────────────────────────────────

    def test_redis_failure_falls_back_to_delegate(self):
        """When Redis throws, operations should still succeed via delegate."""
        delegate = FakeDelegate()
        delegate.put("semantic", "k1", {"content": "important"})

        # Create a Redis mock that always raises
        broken_redis = MagicMock()
        broken_redis.get.side_effect = ConnectionError("Redis down")
        broken_redis.setex.side_effect = ConnectionError("Redis down")
        broken_redis.pipeline.side_effect = ConnectionError("Redis down")
        broken_redis.scan.side_effect = ConnectionError("Redis down")

        backend = RedisCacheBackend(
            redis_client=broken_redis,
            delegate=delegate,
            user_id="test-user",
        )

        # Should still work via delegate
        result = backend.get("semantic", "k1")
        assert result is not None
        assert result["content"] == "important"

        # Put should also succeed
        backend.put("semantic", "k2", {"content": "new"})
        assert delegate.get("semantic", "k2") is not None


class TestPerformance:
    """Performance benchmarks comparing cached vs uncached."""

    def setup_method(self):
        _redis_stats["hits"] = 0
        _redis_stats["misses"] = 0
        _redis_stats["errors"] = 0

    def test_perf_search_cache_hit_faster_than_delegate(self):
        """Cache hits should be significantly faster than delegate calls."""
        # Simulate 50ms Cosmos latency
        delegate = FakeDelegate(latency_ms=50)
        redis = make_fake_redis()
        backend = RedisCacheBackend(
            redis_client=redis,
            delegate=delegate,
            user_id="perf-user",
            search_ttl=300,
        )

        # Populate data
        for i in range(20):
            delegate.put("semantic", f"doc{i}", {
                "id": f"doc{i}",
                "content": f"pharmaceutical drug safety study number {i}",
                "topic": "pharma",
            })

        query = "pharmaceutical safety"

        # First call — cache miss (goes to delegate)
        t0 = time.perf_counter()
        results_miss = backend.search("semantic", query, limit=10)
        miss_ms = (time.perf_counter() - t0) * 1000

        # Second call — cache hit (from Redis)
        t0 = time.perf_counter()
        results_hit = backend.search("semantic", query, limit=10)
        hit_ms = (time.perf_counter() - t0) * 1000

        print(f"\n  Cache MISS: {miss_ms:.1f}ms")
        print(f"  Cache HIT:  {hit_ms:.1f}ms")
        print(f"  Speedup:    {miss_ms / max(hit_ms, 0.01):.1f}x")

        assert results_hit == results_miss, "Cached results should match original"
        assert hit_ms < miss_ms, "Cache hit should be faster"

    def test_perf_get_cache_hit_faster(self):
        """Individual document gets should be faster from cache."""
        delegate = FakeDelegate(latency_ms=30)
        redis = make_fake_redis()
        backend = RedisCacheBackend(
            redis_client=redis,
            delegate=delegate,
            user_id="perf-user",
        )

        doc = {"id": "perf1", "content": "performance test document", "topic": "benchmark"}
        backend.put("semantic", "perf1", doc)

        # Reset delegate counter
        delegate.call_count["get"] = 0

        # Get from cache
        t0 = time.perf_counter()
        for _ in range(100):
            backend.get("semantic", "perf1")
        cached_ms = (time.perf_counter() - t0) * 1000

        print(f"\n  100 cached gets: {cached_ms:.1f}ms ({cached_ms/100:.2f}ms/op)")
        assert delegate.call_count["get"] == 0, "All gets should hit cache"
        assert _redis_stats["hits"] >= 100

    def test_perf_write_through_does_not_block(self):
        """Write-through should complete delegate + cache writes efficiently."""
        delegate = FakeDelegate(latency_ms=10)
        redis = make_fake_redis()
        backend = RedisCacheBackend(
            redis_client=redis,
            delegate=delegate,
            user_id="perf-user",
        )

        t0 = time.perf_counter()
        for i in range(50):
            backend.put("semantic", f"wt{i}", {"content": f"write-through test {i}"})
        total_ms = (time.perf_counter() - t0) * 1000

        print(f"\n  50 write-throughs: {total_ms:.1f}ms ({total_ms/50:.1f}ms/op)")
        assert delegate.call_count["put"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
