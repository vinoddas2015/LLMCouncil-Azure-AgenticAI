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
import os
import uuid
import math
import re
from abc import ABC, abstractmethod
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        self._base = os.path.join(base_dir, _user_hash(user_id))
        self._index: Dict[str, Dict[str, Dict[str, float]]] = {}  # collection -> {term -> {key -> score}}
        self._ensure_dirs()
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
      1. Cosmos DB — if COSMOS_ENDPOINT + COSMOS_KEY are set
      2. Local JSON — file-based fallback for dev (per-user directory)
    """
    user_id = get_memory_user()

    if user_id in _backend_cache:
        return _backend_cache[user_id]

    from .config import COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE, COSMOS_MEMORY_CONTAINER
    if COSMOS_ENDPOINT and COSMOS_KEY:
        backend = CosmosDBBackend(
            endpoint=COSMOS_ENDPOINT,
            key=COSMOS_KEY,
            database=COSMOS_DATABASE,
            container_name=COSMOS_MEMORY_CONTAINER,
            user_id=user_id,
        )
    else:
        backend = LocalJSONBackend(user_id=user_id)

    _backend_cache[user_id] = backend
    return backend


def set_memory_backend(backend: MemoryStoreBackend):
    """Swap the backend at runtime (e.g. for cloud deployment or tests)."""
    user_id = get_memory_user()
    _backend_cache[user_id] = backend
