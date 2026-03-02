"""
Cloud-agnostic memory store abstraction.

Provides a pluggable storage backend for the council's 3-tier memory system
(Semantic, Episodic, Procedural).  Ships with a local JSON-file backend that
requires zero infrastructure; swap in Redis / CosmosDB / PostgreSQL
via the abstract base class for production deployments.

Per-user isolation:
    All memory operations are scoped to the current user via a ContextVar.
    Call ``set_memory_user(user_id)`` before any memory operation to set
    the active user.  Backends automatically namespace data by user_id.

    - Local JSON: ``data/memory/{user_hash}/{collection}/{key}.json``
    - Cosmos DB:  ``_user_id`` field on every document, filtered in queries
    - Redis Cache: write-through cache wrapping CosmosDB for sub-100ms recall

Directory layout (local backend):
    data/memory/{user_hash}/
        semantic/   ← domain knowledge entries
        episodic/   ← conversation-level decision logs
        procedural/ ← workflow patterns & learned procedures
        index.json  ← lightweight inverted index for search
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
import math
import re
from abc import ABC, abstractmethod
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("llm_council.memory_store")

MEMORY_DIR = os.path.join("data", "memory")

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Per-user scoping via ContextVar                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

_current_memory_user: ContextVar[str] = ContextVar("memory_user", default="shared")


def set_memory_user(user_id: str) -> None:
    """Set the active user for all subsequent memory operations in this async context."""
    _current_memory_user.set(user_id)


def get_memory_user() -> str:
    """Return the current memory user (defaults to 'shared')."""
    return _current_memory_user.get()


def _user_hash(user_id: str) -> str:
    """Generate a short, filesystem-safe hash from a user_id."""
    sanitised = user_id.lower().strip()
    return hashlib.md5(sanitised.encode()).hexdigest()[:10]


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Abstract Base — implement this for any cloud provider              ║
# ╚══════════════════════════════════════════════════════════════════════╝

class MemoryStoreBackend(ABC):
    """Interface every backend must implement."""

    @abstractmethod
    def put(self, collection: str, key: str, doc: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def delete(self, collection: str, key: str) -> bool: ...

    @abstractmethod
    def list_keys(self, collection: str) -> List[str]: ...

    @abstractmethod
    def query(self, collection: str, filters: Dict[str, Any],
              limit: int = 50) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def search(self, collection: str, query_text: str,
               limit: int = 10) -> List[Dict[str, Any]]: ...


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Local JSON-file backend (zero dependencies)                        ║
# ╚══════════════════════════════════════════════════════════════════════╝

class LocalJSONBackend(MemoryStoreBackend):
    """
    Stores each document as an individual JSON file:
        {MEMORY_DIR}/{user_hash}/{collection}/{key}.json

    A lightweight TF-IDF-ish inverted index is maintained in memory for search.
    Suitable for single-node dev / POC; swap for a managed store in production to the respective cloud env.
    """

    def __init__(self, base_dir: str = MEMORY_DIR, user_id: str = "shared"):
        self._user_id = user_id
        self._base_dir = base_dir
        self._base = os.path.join(base_dir, _user_hash(user_id))
        self._index: Dict[str, Dict[str, Dict[str, float]]] = {}  # collection -> {term -> {key -> score}}
        self._ensure_dirs()
        self._migrate_legacy_data()
        self._rebuild_index()

    # ── CRUD ─────────────────────────────────────────────────────────

    def put(self, collection: str, key: str, doc: Dict[str, Any]) -> None:
        self._ensure_dirs(collection)
        path = self._path(collection, key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, default=str)
        self._index_document(collection, key, doc)

    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]:
        path = self._path(collection, key)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete(self, collection: str, key: str) -> bool:
        path = self._path(collection, key)
        if os.path.exists(path):
            os.remove(path)
            self._remove_from_index(collection, key)
            return True
        return False

    def list_keys(self, collection: str) -> List[str]:
        coll_dir = os.path.join(self._base, collection)
        if not os.path.isdir(coll_dir):
            return []
        return [f[:-5] for f in os.listdir(coll_dir) if f.endswith(".json")]

    def query(self, collection: str, filters: Dict[str, Any],
              limit: int = 50) -> List[Dict[str, Any]]:
        results = []
        for key in self.list_keys(collection):
            doc = self.get(collection, key)
            if doc is None:
                continue
            if all(doc.get(k) == v for k, v in filters.items()):
                results.append(doc)
            if len(results) >= limit:
                break
        return results

    def search(self, collection: str, query_text: str,
               limit: int = 10) -> List[Dict[str, Any]]:
        terms = self._tokenize(query_text)
        if not terms:
            return []
        coll_index = self._index.get(collection, {})
        scores: Dict[str, float] = {}
        for term in terms:
            posting = coll_index.get(term, {})
            for key, tf in posting.items():
                scores[key] = scores.get(key, 0.0) + tf
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        results = []
        for key, score in ranked:
            doc = self.get(collection, key)
            if doc:
                doc["_search_score"] = round(score, 4)
                results.append(doc)
        return results

    # ── Internal helpers ─────────────────────────────────────────────

    def _path(self, collection: str, key: str) -> str:
        return os.path.join(self._base, collection, f"{key}.json")

    def _migrate_legacy_data(self):
        """Migrate pre-user-scoping memory data into the user-hashed directory.

        Before per-user isolation was added, memory files were stored directly
        in ``data/memory/{collection}/{key}.json``.  This function detects those
        legacy files and moves them into the current user-scoped path so they
        appear in stats and listings.  Migration is idempotent — files are only
        moved if the destination does not already exist.
        """
        import shutil
        legacy_base = self._base_dir  # e.g. data/memory
        if legacy_base == self._base:
            return  # nothing to migrate (shouldn't happen)
        migrated = 0
        for collection in ("semantic", "episodic", "procedural"):
            legacy_dir = os.path.join(legacy_base, collection)
            if not os.path.isdir(legacy_dir):
                continue
            # Only migrate if the legacy dir is NOT inside a user-hash folder
            # (i.e. it's directly under base_dir, not base_dir/{hash}/collection)
            parent_name = os.path.basename(os.path.dirname(legacy_dir))
            if parent_name != os.path.basename(legacy_base):
                continue  # this is already inside a user-hash dir
            target_dir = os.path.join(self._base, collection)
            for fname in os.listdir(legacy_dir):
                if not fname.endswith(".json"):
                    continue
                src = os.path.join(legacy_dir, fname)
                dst = os.path.join(target_dir, fname)
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                        migrated += 1
                    except Exception:
                        pass  # best-effort
        if migrated:
            logger.info(f"[MemoryStore] Migrated {migrated} legacy memory files to user-scoped dir")

    def _ensure_dirs(self, collection: str | None = None):
        Path(self._base).mkdir(parents=True, exist_ok=True)
        for default in ("semantic", "episodic", "procedural"):
            Path(os.path.join(self._base, default)).mkdir(exist_ok=True)
        if collection:
            Path(os.path.join(self._base, collection)).mkdir(exist_ok=True)

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        tokens = re.findall(r"[a-z0-9]{2,}", text)
        # Remove very common stopwords
        stop = {"the", "is", "at", "in", "on", "of", "to", "and", "or", "for", "an", "it", "by", "as", "be"}
        return [t for t in tokens if t not in stop]

    def _index_document(self, collection: str, key: str, doc: Dict[str, Any]):
        coll_index = self._index.setdefault(collection, {})
        # Remove old entries for this key
        self._remove_from_index(collection, key)
        # Build text from all string fields
        parts = []
        for v in doc.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, list):
                parts.extend(str(x) for x in v)
        text = " ".join(parts)
        terms = self._tokenize(text)
        term_counts: Dict[str, int] = {}
        for t in terms:
            term_counts[t] = term_counts.get(t, 0) + 1
        total = max(len(terms), 1)
        for term, count in term_counts.items():
            posting = coll_index.setdefault(term, {})
            posting[key] = count / total  # TF score

    def _remove_from_index(self, collection: str, key: str):
        coll_index = self._index.get(collection, {})
        empty_terms = []
        for term, posting in coll_index.items():
            posting.pop(key, None)
            if not posting:
                empty_terms.append(term)
        for t in empty_terms:
            del coll_index[t]

    def _rebuild_index(self):
        """Scan all existing documents to populate the search index."""
        for collection in ("semantic", "episodic", "procedural"):
            for key in self.list_keys(collection):
                doc = self.get(collection, key)
                if doc:
                    self._index_document(collection, key, doc)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Azure Cosmos DB backend (cloud production)                         ║
# ╚══════════════════════════════════════════════════════════════════════╝

class CosmosDBBackend(MemoryStoreBackend):
    """
    Stores memory documents in Azure Cosmos DB (NoSQL API).

    Container : configurable (default 'memory')
    Partition : /collection  (semantic | episodic | procedural)
    Document  : {"id": key, "collection": collection, "_user_id": ..., ...doc fields}

    All operations are scoped to a specific user_id for per-user isolation.
    """

    def __init__(self, endpoint: str, key: str, database: str, container_name: str = "memory", user_id: str = "shared"):
        from azure.cosmos import CosmosClient, PartitionKey
        self._client = CosmosClient(endpoint, credential=key)
        db = self._client.create_database_if_not_exists(id=database)
        self._container = db.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path="/collection"),
            offer_throughput=400,
        )
        self._user_id = user_id
        self._key_prefix = _user_hash(user_id)

    def _user_key(self, key: str) -> str:
        """Prefix a document key with the user hash for namespace isolation."""
        if key.startswith(f"{self._key_prefix}::"):
            return key  # already prefixed
        return f"{self._key_prefix}::{key}"

    def _strip_prefix(self, key: str) -> str:
        """Remove the user hash prefix from a key."""
        prefix = f"{self._key_prefix}::"
        return key[len(prefix):] if key.startswith(prefix) else key

    def put(self, collection: str, key: str, doc: Dict[str, Any]) -> None:
        item = dict(doc)
        item["id"] = self._user_key(key)
        item["collection"] = collection
        item["_user_id"] = self._user_id
        self._container.upsert_item(item)

    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]:
        try:
            item = self._container.read_item(item=self._user_key(key), partition_key=collection)
            for k in ("_rid", "_self", "_etag", "_attachments", "_ts"):
                item.pop(k, None)
            # Restore original key (without prefix) for callers
            item["id"] = self._strip_prefix(item.get("id", key))
            return item
        except Exception:
            return None

    def delete(self, collection: str, key: str) -> bool:
        try:
            self._container.delete_item(item=self._user_key(key), partition_key=collection)
            return True
        except Exception:
            return False

    def list_keys(self, collection: str) -> List[str]:
        query = "SELECT c.id FROM c WHERE c.collection = @coll AND c._user_id = @uid"
        params = [
            {"name": "@coll", "value": collection},
            {"name": "@uid", "value": self._user_id},
        ]
        items = list(self._container.query_items(
            query=query, parameters=params, enable_cross_partition_query=False,
        ))
        return [self._strip_prefix(item["id"]) for item in items]

    def query(self, collection: str, filters: Dict[str, Any],
              limit: int = 50) -> List[Dict[str, Any]]:
        conditions = ["c.collection = @coll", "c._user_id = @uid"]
        params: list = [
            {"name": "@coll", "value": collection},
            {"name": "@uid", "value": self._user_id},
        ]
        idx = 0
        for fk, fv in filters.items():
            pname = f"@f{idx}"
            conditions.append(f"c.{fk} = {pname}")
            params.append({"name": pname, "value": fv})
            idx += 1
        sql = f"SELECT TOP {int(limit)} * FROM c WHERE " + " AND ".join(conditions)
        items = list(self._container.query_items(
            query=sql, parameters=params, enable_cross_partition_query=False,
        ))
        for item in items:
            for k in ("_rid", "_self", "_etag", "_attachments", "_ts"):
                item.pop(k, None)
            item["id"] = self._strip_prefix(item.get("id", ""))
        return items

    def search(self, collection: str, query_text: str,
               limit: int = 10) -> List[Dict[str, Any]]:
        """
        Full-text search via Cosmos DB CONTAINS (case-insensitive).

        Searches across a set of common text fields, scoped to the current user.
        For production-scale search consider enabling Cosmos DB full-text indexing
        or Azure AI Search.
        """
        terms = [t.lower() for t in re.findall(r"[a-z0-9]{2,}", query_text.lower())]
        if not terms:
            return []
        # Build OR conditions across known text fields
        field_names = ["content", "summary", "insight", "text", "title", "description"]
        contains_clauses = []
        for term in terms[:5]:  # Cap to avoid overly long queries
            for fn in field_names:
                contains_clauses.append(f"CONTAINS(LOWER(c.{fn} ?? ''), '{term}')")
        where_clause = " OR ".join(contains_clauses)
        sql = (
            f"SELECT TOP {int(limit)} * FROM c "
            f"WHERE c.collection = @coll AND c._user_id = @uid AND ({where_clause})"
        )
        params = [
            {"name": "@coll", "value": collection},
            {"name": "@uid", "value": self._user_id},
        ]
        items = list(self._container.query_items(
            query=sql, parameters=params, enable_cross_partition_query=False,
        ))
        for item in items:
            for k in ("_rid", "_self", "_etag", "_attachments", "_ts"):
                item.pop(k, None)
            item["id"] = self._strip_prefix(item.get("id", ""))
        return items


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Azure Cache for Redis — write-through cache (Enterprise tier)      ║
# ╚══════════════════════════════════════════════════════════════════════╝

_redis_client = None  # Shared Redis connection (lazy-init, thread-safe)
_redis_stats: Dict[str, int] = {"hits": 0, "misses": 0, "errors": 0}


def _get_redis_client():
    """Lazy-init a shared Redis Cluster connection (one per process).

    Azure Cache for Redis Enterprise uses OSS Cluster mode, requiring
    ``RedisCluster`` to handle automatic MOVED/ASK redirection.
    Returns None if Redis is not configured or connection fails.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    from .config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_SSL
    if not REDIS_HOST:
        return None

    try:
        import redis as redis_lib
        client = redis_lib.RedisCluster(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            ssl=REDIS_SSL,
            ssl_cert_reqs=None,  # Azure Enterprise manages certs
            socket_timeout=5,
            socket_connect_timeout=3,
            retry_on_timeout=True,
            decode_responses=True,
        )
        # Verify connectivity
        client.ping()
        _redis_client = client
        logger.info(
            f"[Redis] Connected to Azure Cache for Redis Enterprise (Cluster) at "
            f"{REDIS_HOST}:{REDIS_PORT} (SSL={REDIS_SSL})"
        )
        return _redis_client
    except Exception as e:
        logger.warning(f"[Redis] Connection failed (falling back to direct Cosmos): {e}")
        return None


def get_redis_stats() -> Dict[str, Any]:
    """Return Redis cache hit/miss statistics for diagnostics."""
    total = _redis_stats["hits"] + _redis_stats["misses"]
    hit_rate = (_redis_stats["hits"] / total * 100) if total > 0 else 0.0
    return {
        **_redis_stats,
        "total_requests": total,
        "hit_rate_pct": round(hit_rate, 1),
    }


class RedisCacheBackend(MemoryStoreBackend):
    """
    Write-through Redis cache wrapping any MemoryStoreBackend (typically CosmosDB).

    Architecture:
      READ  → Redis cache first → on miss → delegate (Cosmos DB) → backfill cache
      WRITE → delegate first (source of truth) → update Redis cache
      DELETE → delegate first → invalidate Redis cache + search caches

    Cache key schema:
      Document:  mem:{user_hash}:{collection}:{key}
      Search:    search:{user_hash}:{collection}:{query_md5}:{limit}
      List keys: keys:{user_hash}:{collection}

    TTL:
      Search results: 5 minutes (configurable via REDIS_SEARCH_TTL)
      Documents:      10 minutes (configurable via REDIS_DOC_TTL)
      List keys:      2 minutes (short — keys change on writes)

    Performance target: <5ms cache hits vs 200-800ms Cosmos queries.
    """

    def __init__(self, redis_client, delegate: MemoryStoreBackend,
                 user_id: str = "shared",
                 search_ttl: int = 300, doc_ttl: int = 600):
        self._redis = redis_client
        self._delegate = delegate
        self._user_hash = _user_hash(user_id)
        self._search_ttl = search_ttl
        self._doc_ttl = doc_ttl
        self._keys_ttl = 120  # 2 min for list_keys cache

    # ── Cache key builders ──────────────────────────────────────────

    def _doc_key(self, collection: str, key: str) -> str:
        return f"mem:{self._user_hash}:{collection}:{key}"

    def _search_key(self, collection: str, query_text: str, limit: int) -> str:
        q_hash = hashlib.md5(query_text.lower().strip().encode()).hexdigest()[:12]
        return f"search:{self._user_hash}:{collection}:{q_hash}:{limit}"

    def _keys_key(self, collection: str) -> str:
        return f"keys:{self._user_hash}:{collection}"

    def _collection_pattern(self, collection: str) -> str:
        """Pattern for invalidating all search caches in a collection."""
        return f"search:{self._user_hash}:{collection}:*"

    # ── CRUD (write-through) ─────────────────────────────────────────

    def put(self, collection: str, key: str, doc: Dict[str, Any]) -> None:
        # Source of truth: delegate first
        self._delegate.put(collection, key, doc)
        try:
            pipe = self._redis.pipeline(transaction=False)
            # Cache the document
            pipe.setex(
                self._doc_key(collection, key),
                self._doc_ttl,
                json.dumps(doc, default=str),
            )
            # Invalidate search + list caches (stale after write)
            pipe.delete(self._keys_key(collection))
            pipe.execute()
            # Invalidate search caches via pattern scan (non-blocking)
            self._invalidate_search_cache(collection)
        except Exception as e:
            _redis_stats["errors"] += 1
            logger.debug(f"[Redis] Cache write failed (non-fatal): {e}")

    def get(self, collection: str, key: str) -> Optional[Dict[str, Any]]:
        # Try Redis first
        try:
            cached = self._redis.get(self._doc_key(collection, key))
            if cached is not None:
                _redis_stats["hits"] += 1
                return json.loads(cached)
        except Exception as e:
            _redis_stats["errors"] += 1
            logger.debug(f"[Redis] Cache read failed: {e}")

        # Cache miss — fetch from delegate
        _redis_stats["misses"] += 1
        doc = self._delegate.get(collection, key)
        if doc is not None:
            try:
                self._redis.setex(
                    self._doc_key(collection, key),
                    self._doc_ttl,
                    json.dumps(doc, default=str),
                )
            except Exception:
                pass
        return doc

    def delete(self, collection: str, key: str) -> bool:
        result = self._delegate.delete(collection, key)
        try:
            pipe = self._redis.pipeline(transaction=False)
            pipe.delete(self._doc_key(collection, key))
            pipe.delete(self._keys_key(collection))
            pipe.execute()
            self._invalidate_search_cache(collection)
        except Exception as e:
            _redis_stats["errors"] += 1
            logger.debug(f"[Redis] Cache invalidation failed: {e}")
        return result

    def list_keys(self, collection: str) -> List[str]:
        # Try cached key list
        try:
            cached = self._redis.get(self._keys_key(collection))
            if cached is not None:
                _redis_stats["hits"] += 1
                return json.loads(cached)
        except Exception:
            pass

        _redis_stats["misses"] += 1
        keys = self._delegate.list_keys(collection)
        try:
            self._redis.setex(
                self._keys_key(collection),
                self._keys_ttl,
                json.dumps(keys),
            )
        except Exception:
            pass
        return keys

    def query(self, collection: str, filters: Dict[str, Any],
              limit: int = 50) -> List[Dict[str, Any]]:
        # Query is complex/dynamic — pass through to delegate (no caching)
        # Filter queries are rare and change based on arbitrary filter combos
        return self._delegate.query(collection, filters, limit)

    def search(self, collection: str, query_text: str,
               limit: int = 10) -> List[Dict[str, Any]]:
        """
        Cached search — the HOT PATH for memory recall acceleration.

        Cache hit: ~2-5ms (Redis GET + JSON deserialize)
        Cache miss: ~200-800ms (Cosmos CONTAINS query) + backfill
        """
        cache_key = self._search_key(collection, query_text, limit)

        # Try Redis cache first
        try:
            t0 = time.perf_counter()
            cached = self._redis.get(cache_key)
            if cached is not None:
                _redis_stats["hits"] += 1
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.debug(f"[Redis] Search HIT ({elapsed_ms:.1f}ms): {collection}/{query_text[:50]}")
                return json.loads(cached)
        except Exception as e:
            _redis_stats["errors"] += 1
            logger.debug(f"[Redis] Search cache read failed: {e}")

        # Cache miss — query delegate
        _redis_stats["misses"] += 1
        t0 = time.perf_counter()
        results = self._delegate.search(collection, query_text, limit)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"[Redis] Search MISS ({elapsed_ms:.1f}ms delegate): {collection}/{query_text[:50]}")

        # Backfill cache
        if results:
            try:
                self._redis.setex(
                    cache_key,
                    self._search_ttl,
                    json.dumps(results, default=str),
                )
            except Exception:
                pass

        return results

    # ── Internal helpers ─────────────────────────────────────────────

    def _invalidate_search_cache(self, collection: str):
        """Remove all search cache entries for a collection.

        Uses ``scan_iter`` which handles cluster-mode SCAN across all nodes.
        Falls back gracefully — stale caches expire via TTL anyway.
        """
        try:
            pattern = self._collection_pattern(collection)
            keys = list(self._redis.scan_iter(match=pattern, count=100))
            if keys:
                for key in keys:
                    try:
                        self._redis.delete(key)
                    except Exception:
                        pass  # Best effort per-key deletion in cluster mode
        except Exception:
            pass  # Best effort — stale caches expire via TTL anyway


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  User-scoped backend accessor                                      ║
# ╚══════════════════════════════════════════════════════════════════════╝

# Cache: one backend per user_id (avoids re-creating Cosmos clients)
_backend_cache: Dict[str, MemoryStoreBackend] = {}
_cosmos_container = None  # shared Cosmos container (lazy-init)


def _get_cosmos_container():
    """Lazy-init a shared Cosmos container reference (one per process)."""
    global _cosmos_container
    if _cosmos_container is None:
        from .config import COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE, COSMOS_MEMORY_CONTAINER
        if COSMOS_ENDPOINT and COSMOS_KEY:
            from azure.cosmos import CosmosClient, PartitionKey
            client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
            db = client.create_database_if_not_exists(id=COSMOS_DATABASE)
            _cosmos_container = db.create_container_if_not_exists(
                id=COSMOS_MEMORY_CONTAINER,
                partition_key=PartitionKey(path="/collection"),
                offer_throughput=400,
            )
    return _cosmos_container


def get_memory_backend() -> MemoryStoreBackend:
    """Return a user-scoped memory store backend.

    Reads the active user from the ``_current_memory_user`` ContextVar
    (set via ``set_memory_user(user_id)``).

    Priority:
      1. local-user → always Local JSON (dev mode, no cloud dependency)
      2. Cosmos DB + Redis Cache → if both COSMOS + REDIS env vars are set
      3. Cosmos DB alone → if only COSMOS env vars are set
      4. Local JSON → file-based fallback (per-user directory)
    """
    user_id = get_memory_user()

    if user_id in _backend_cache:
        return _backend_cache[user_id]

    # Local development always uses file-based storage
    if user_id == "local-user":
        backend = LocalJSONBackend(user_id=user_id)
    else:
        from .config import (
            COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE, COSMOS_MEMORY_CONTAINER,
            REDIS_HOST, REDIS_SEARCH_TTL, REDIS_DOC_TTL,
        )
        if COSMOS_ENDPOINT and COSMOS_KEY:
            cosmos_backend = CosmosDBBackend(
                endpoint=COSMOS_ENDPOINT,
                key=COSMOS_KEY,
                database=COSMOS_DATABASE,
                container_name=COSMOS_MEMORY_CONTAINER,
                user_id=user_id,
            )
            # Wrap Cosmos with Redis cache if Redis is configured
            redis_client = _get_redis_client() if REDIS_HOST else None
            if redis_client is not None:
                backend = RedisCacheBackend(
                    redis_client=redis_client,
                    delegate=cosmos_backend,
                    user_id=user_id,
                    search_ttl=REDIS_SEARCH_TTL,
                    doc_ttl=REDIS_DOC_TTL,
                )
                logger.info(f"[MemoryStore] Using Redis-cached Cosmos backend for user {_user_hash(user_id)}")
            else:
                backend = cosmos_backend
        else:
            backend = LocalJSONBackend(user_id=user_id)

    _backend_cache[user_id] = backend
    return backend


def set_memory_backend(backend: MemoryStoreBackend):
    """Swap the backend at runtime (e.g. for cloud deployment or tests)."""
    user_id = get_memory_user()
    _backend_cache[user_id] = backend
