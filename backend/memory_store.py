"""
Cloud-agnostic memory store abstraction.

Provides a pluggable storage backend for the council's 3-tier memory system
(Semantic, Episodic, Procedural).  Ships with a local JSON-file backend that
requires zero infrastructure; swap in Redis / DynamoDB / CosmosDB / PostgreSQL
via the abstract base class for production deployments.

Directory layout (local backend):
    data/memory/
        semantic/   ← domain knowledge entries
        episodic/   ← conversation-level decision logs
        procedural/ ← workflow patterns & learned procedures
        index.json  ← lightweight inverted index for search
"""

from __future__ import annotations

import json
import os
import uuid
import math
import hashlib
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MEMORY_DIR = os.path.join("data", "memory")


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
        {MEMORY_DIR}/{collection}/{key}.json

    A lightweight TF-IDF-ish inverted index is maintained in memory for search.
    Suitable for single-node dev / POC; swap for a managed store in production.
    """

    def __init__(self, base_dir: str = MEMORY_DIR):
        self._base = base_dir
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
# ║  Singleton accessor                                                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

_backend_instance: Optional[MemoryStoreBackend] = None


def get_memory_backend() -> MemoryStoreBackend:
    """Return the active memory store backend (lazy-init local JSON)."""
    global _backend_instance
    if _backend_instance is None:
        _backend_instance = LocalJSONBackend()
    return _backend_instance


def set_memory_backend(backend: MemoryStoreBackend):
    """Swap the backend at runtime (e.g. for cloud deployment or tests)."""
    global _backend_instance
    _backend_instance = backend
