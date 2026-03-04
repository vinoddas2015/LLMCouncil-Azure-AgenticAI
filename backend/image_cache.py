"""
3-tier serverless image cache — designed for 500+ concurrent users.

Architecture:
  L1  In-memory   : tiny per-process dedup (10 items, same-request only)
  L2  Redis        : shared hot cache across all App Service instances (~5ms)
  L3  Azure Blob   : permanent cold storage, survives restarts/redeploys (unlimited)

Flow:
  READ  → L1 hit? → L2 (Redis) hit? → L3 (Blob) hit? → miss (generate)
  WRITE → L3 (Blob, permanent) → L2 (Redis, TTL) → L1 (in-process)

Key schema:
  Redis:  img:{md5_hash}          (binary, TTL = REDIS_IMAGE_TTL)
  Blob:   images/{md5_hash}.png   (permanent, content-addressed)

The content-addressed design means identical prompts always produce the same
cache key, so 500 users asking the same question share one cached image.

Stats tracked: l1_hits, l2_hits, l3_hits, misses, writes, errors.
"""

import base64
import hashlib
import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Stats (thread-safe via GIL for simple increments) ────────────────────
_stats: Dict[str, int] = {
    "l1_hits": 0,
    "l2_hits": 0,
    "l3_hits": 0,
    "misses": 0,
    "writes": 0,
    "errors": 0,
}


def get_image_cache_stats() -> Dict[str, Any]:
    """Return cache hit/miss statistics for the Image Quality Monitor agent."""
    total = _stats["l1_hits"] + _stats["l2_hits"] + _stats["l3_hits"] + _stats["misses"]
    hit_total = _stats["l1_hits"] + _stats["l2_hits"] + _stats["l3_hits"]
    return {
        **_stats,
        "total_requests": total,
        "total_hits": hit_total,
        "hit_rate_pct": round((hit_total / total * 100) if total else 0.0, 1),
        "l1_size": len(_l1_cache),
        "l1_max": _L1_MAX,
    }


# ── Cache key ────────────────────────────────────────────────────────────

def cache_key(prompt: str, aspect: str) -> str:
    """Deterministic content-addressed key from prompt + aspect ratio."""
    return hashlib.md5(f"{prompt}:{aspect}".encode()).hexdigest()


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  L1 — In-Memory LRU (per-process, tiny)                            ║
# ╚══════════════════════════════════════════════════════════════════════╝

_L1_MAX = 10  # Tiny — just for same-request dedup within one export
_l1_cache: OrderedDict = OrderedDict()
_l1_lock = threading.Lock()


def _l1_get(key: str) -> Optional[bytes]:
    with _l1_lock:
        if key in _l1_cache:
            _l1_cache.move_to_end(key)
            return _l1_cache[key]
    return None


def _l1_put(key: str, data: bytes):
    with _l1_lock:
        if key in _l1_cache:
            _l1_cache.move_to_end(key)
            return
        _l1_cache[key] = data
        while len(_l1_cache) > _L1_MAX:
            _l1_cache.popitem(last=False)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  L2 — Redis (shared across App Service instances)                   ║
# ╚══════════════════════════════════════════════════════════════════════╝

_REDIS_IMAGE_TTL = int(os.getenv("REDIS_IMAGE_TTL", "3600"))  # 1 hour default

_redis_client_img = None
_redis_init_done = False


def _get_redis():
    """Lazy-init Redis connection for image cache (reuses same cluster)."""
    global _redis_client_img, _redis_init_done
    if _redis_init_done:
        return _redis_client_img

    from .config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_SSL
    if not REDIS_HOST:
        _redis_init_done = True
        return None

    try:
        import redis as redis_lib
        client = redis_lib.RedisCluster(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            ssl=REDIS_SSL,
            ssl_cert_reqs=None,
            socket_timeout=5,
            socket_connect_timeout=3,
            retry_on_timeout=True,
            decode_responses=False,  # binary mode for image bytes
        )
        client.ping()
        _redis_client_img = client
        _redis_init_done = True
        logger.info("[ImageCache] Redis L2 connected at %s:%s", REDIS_HOST, REDIS_PORT)
        return _redis_client_img
    except Exception as e:
        logger.warning("[ImageCache] Redis L2 unavailable (non-fatal): %s", e)
        _redis_init_done = True
        return None


def _l2_get(key: str) -> Optional[bytes]:
    rc = _get_redis()
    if not rc:
        return None
    try:
        data = rc.get(f"img:{key}")
        if data:
            # Refresh TTL on access (LRU-like behaviour)
            rc.expire(f"img:{key}", _REDIS_IMAGE_TTL)
            return data
        return None
    except Exception as e:
        _stats["errors"] += 1
        logger.debug("[ImageCache] Redis L2 read error: %s", e)
        return None


def _l2_put(key: str, data: bytes):
    rc = _get_redis()
    if not rc:
        return
    try:
        rc.setex(f"img:{key}", _REDIS_IMAGE_TTL, data)
    except Exception as e:
        _stats["errors"] += 1
        logger.debug("[ImageCache] Redis L2 write error: %s", e)


def _l2_exists(key: str) -> bool:
    rc = _get_redis()
    if not rc:
        return False
    try:
        return bool(rc.exists(f"img:{key}"))
    except Exception:
        return False


def get_l2_count() -> int:
    """Approximate count of cached images in Redis (SCAN-based)."""
    rc = _get_redis()
    if not rc:
        return -1
    try:
        count = 0
        for _ in rc.scan_iter(match="img:*", count=500):
            count += 1
        return count
    except Exception:
        return -1


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  L3 — Azure Blob Storage (permanent, content-addressed)            ║
# ╚══════════════════════════════════════════════════════════════════════╝

_BLOB_CONTAINER = os.getenv("AZURE_BLOB_IMAGES_CONTAINER", "images")
_blob_client = None
_blob_init_done = False


def _get_blob_container():
    """Lazy-init Azure Blob container client for images."""
    global _blob_client, _blob_init_done
    if _blob_init_done:
        return _blob_client

    from .config import AZURE_STORAGE_CONNECTION_STRING
    if not AZURE_STORAGE_CONNECTION_STRING:
        _blob_init_done = True
        return None

    try:
        from azure.storage.blob import BlobServiceClient
        svc = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container = svc.get_container_client(_BLOB_CONTAINER)
        # Create container if it doesn't exist (first-time setup)
        try:
            container.get_container_properties()
        except Exception:
            container.create_container()
            logger.info("[ImageCache] Created Blob container '%s'", _BLOB_CONTAINER)
        _blob_client = container
        _blob_init_done = True
        logger.info("[ImageCache] Blob L3 connected (container: %s)", _BLOB_CONTAINER)
        return _blob_client
    except Exception as e:
        logger.warning("[ImageCache] Blob L3 unavailable (non-fatal): %s", e)
        _blob_init_done = True
        return None


def _l3_get(key: str) -> Optional[bytes]:
    container = _get_blob_container()
    if not container:
        return None
    try:
        blob = container.get_blob_client(f"{key}.png")
        return blob.download_blob().readall()
    except Exception:
        # 404 or any other error — treat as miss
        return None


def _l3_put(key: str, data: bytes):
    container = _get_blob_container()
    if not container:
        return
    try:
        blob = container.get_blob_client(f"{key}.png")
        blob.upload_blob(data, overwrite=True, content_settings=_png_content_settings())
    except Exception as e:
        _stats["errors"] += 1
        logger.debug("[ImageCache] Blob L3 write error: %s", e)


def _l3_exists(key: str) -> bool:
    container = _get_blob_container()
    if not container:
        return False
    try:
        blob = container.get_blob_client(f"{key}.png")
        blob.get_blob_properties()
        return True
    except Exception:
        return False


def _png_content_settings():
    from azure.storage.blob import ContentSettings
    return ContentSettings(content_type="image/png")


def get_l3_count() -> int:
    """Count images in Blob Storage (approximate, capped scan)."""
    container = _get_blob_container()
    if not container:
        return -1
    try:
        count = 0
        for _ in container.list_blobs(name_starts_with="", results_per_page=500):
            count += 1
            if count >= 10000:
                break  # safety cap
        return count
    except Exception:
        return -1


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Public API — read-through / write-through                         ║
# ╚══════════════════════════════════════════════════════════════════════╝

def get(prompt: str, aspect: str) -> Optional[bytes]:
    """Read image from cache (L1 → L2 → L3). Returns None on miss."""
    key = cache_key(prompt, aspect)

    # L1 — in-memory
    data = _l1_get(key)
    if data:
        _stats["l1_hits"] += 1
        return data

    # L2 — Redis
    data = _l2_get(key)
    if data:
        _stats["l2_hits"] += 1
        _l1_put(key, data)  # backfill L1
        return data

    # L3 — Blob
    data = _l3_get(key)
    if data:
        _stats["l3_hits"] += 1
        _l2_put(key, data)  # backfill L2
        _l1_put(key, data)  # backfill L1
        return data

    _stats["misses"] += 1
    return None


def put(prompt: str, aspect: str, data: bytes):
    """Write image to all tiers (L3 first as source of truth)."""
    key = cache_key(prompt, aspect)
    _stats["writes"] += 1

    # L3 — Blob (permanent, source of truth)
    _l3_put(key, data)

    # L2 — Redis (hot cache, TTL)
    _l2_put(key, data)

    # L1 — in-memory (dedup)
    _l1_put(key, data)


def exists(prompt: str, aspect: str) -> bool:
    """Quick existence check (L1 → L2 → L3)."""
    key = cache_key(prompt, aspect)
    if _l1_get(key):
        return True
    if _l2_exists(key):
        return True
    return _l3_exists(key)
