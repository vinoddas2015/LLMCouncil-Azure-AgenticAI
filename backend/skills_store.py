"""
Skills Store — Cosmos DB persistence for the 28-skill evidence pipeline.

Stores skill execution results, citation caches, per-skill health metrics,
and query-skill affinity data.  Mirrors the architecture of memory_store.py
(ABC + local fallback + Cosmos DB backend).

Container: ``skills`` in the ``llm-council`` database.
Partition key: ``/skill_name``  (one logical partition per skill source).

Document types stored:
  - **execution**  — one per skill invocation (citations, latency, status)
  - **health**     — rolling health/availability stats per skill
  - **affinity**   — query-keyword -> skill hit-rate mapping for smart routing
  - **citation**   — deduplicated citation cache (keyed by URL hash)

Usage::

    from backend.skills_store import get_skills_store
    store = get_skills_store()

    # Persist an execution run
    store.save_execution("PubMed", run_doc)

    # Query recent executions for a skill
    runs = store.get_recent_executions("PubMed", limit=20)

    # Update health metrics
    store.update_health("OpenFDA", {"status": "ok", "avg_latency_ms": 340})
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skills_store")

SKILLS_DATA_DIR = os.path.join("data", "skills")

# Every document stored has one of these types
DOC_TYPES = ("execution", "health", "affinity", "citation")


# =====================================================================
# Abstract base class
# =====================================================================

class SkillsStoreBackend(ABC):
    """Interface for skills persistence backends."""

    # -- Execution records -------------------------------------------
    @abstractmethod
    def save_execution(self, skill_name: str, doc: Dict[str, Any]) -> str:
        """Persist a single skill-execution record.  Returns document id."""
        ...

    @abstractmethod
    def get_recent_executions(
        self, skill_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Return the *limit* most recent execution docs for a skill."""
        ...

    # -- Health / availability ---------------------------------------
    @abstractmethod
    def update_health(self, skill_name: str, metrics: Dict[str, Any]) -> None:
        """Upsert rolling health metrics for a skill."""
        ...

    @abstractmethod
    def get_health(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Read current health record for a skill."""
        ...

    @abstractmethod
    def get_all_health(self) -> List[Dict[str, Any]]:
        """Return health records for ALL skills."""
        ...

    # -- Citation cache ----------------------------------------------
    @abstractmethod
    def cache_citation(self, skill_name: str, citation: Dict[str, Any]) -> None:
        """Upsert a citation keyed by URL hash."""
        ...

    @abstractmethod
    def get_cached_citation(self, url: str) -> Optional[Dict[str, Any]]:
        """Look up a cached citation by its URL."""
        ...

    # -- Affinity (query -> skill hit-rate) --------------------------
    @abstractmethod
    def record_affinity(
        self, skill_name: str, keywords: List[str], hit_count: int
    ) -> None:
        """Record that *skill_name* returned *hit_count* results for keywords."""
        ...

    @abstractmethod
    def get_top_skills_for_keywords(
        self, keywords: List[str], limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Return the skills most likely to return results for these keywords."""
        ...

    # -- Bulk / utility ----------------------------------------------
    @abstractmethod
    def save_full_run(self, run_bundle: Dict[str, Any]) -> str:
        """Persist a complete run_evidence_skills result bundle."""
        ...

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a full run bundle by id."""
        ...


# =====================================================================
# Local JSON-file backend (zero-infra dev fallback)
# =====================================================================

class LocalSkillsBackend(SkillsStoreBackend):
    """
    File-based skills store.
    Layout::
        data/skills/
            executions/{skill_name}/{id}.json
            health/{skill_name}.json
            citations/{url_hash}.json
            affinity/{skill_name}.json
            runs/{run_id}.json
    """

    def __init__(self, base_dir: str = SKILLS_DATA_DIR):
        self._base = base_dir
        self._ensure_dirs()

    def _ensure_dirs(self):
        for sub in ("executions", "health", "citations", "affinity", "runs"):
            os.makedirs(os.path.join(self._base, sub), exist_ok=True)

    def _write(self, path: str, data: dict):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _read(self, path: str) -> Optional[dict]:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _url_hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    # -- Executions --------------------------------------------------

    def save_execution(self, skill_name: str, doc: Dict[str, Any]) -> str:
        doc_id = doc.get("id") or str(uuid.uuid4())
        doc["id"] = doc_id
        doc["skill_name"] = skill_name
        doc["type"] = "execution"
        doc.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        path = os.path.join(
            self._base, "executions", skill_name.replace("/", "_"), f"{doc_id}.json"
        )
        self._write(path, doc)
        return doc_id

    def get_recent_executions(
        self, skill_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        folder = os.path.join(
            self._base, "executions", skill_name.replace("/", "_")
        )
        if not os.path.isdir(folder):
            return []
        files = sorted(Path(folder).glob("*.json"), key=os.path.getmtime, reverse=True)
        results = []
        for f in files[:limit]:
            data = self._read(str(f))
            if data:
                results.append(data)
        return results

    # -- Health ------------------------------------------------------

    def update_health(self, skill_name: str, metrics: Dict[str, Any]) -> None:
        path = os.path.join(
            self._base, "health", f"{skill_name.replace('/', '_')}.json"
        )
        existing = self._read(path) or {}
        existing.update(metrics)
        existing["skill_name"] = skill_name
        existing["type"] = "health"
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(path, existing)

    def get_health(self, skill_name: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(
            self._base, "health", f"{skill_name.replace('/', '_')}.json"
        )
        return self._read(path)

    def get_all_health(self) -> List[Dict[str, Any]]:
        folder = os.path.join(self._base, "health")
        results = []
        for f in Path(folder).glob("*.json"):
            data = self._read(str(f))
            if data:
                results.append(data)
        return results

    # -- Citation cache ----------------------------------------------

    def cache_citation(self, skill_name: str, citation: Dict[str, Any]) -> None:
        url = citation.get("url", "")
        if not url:
            return
        url_hash = self._url_hash(url)
        citation["skill_name"] = skill_name
        citation["type"] = "citation"
        citation["url_hash"] = url_hash
        citation["cached_at"] = datetime.now(timezone.utc).isoformat()
        path = os.path.join(self._base, "citations", f"{url_hash}.json")
        self._write(path, citation)

    def get_cached_citation(self, url: str) -> Optional[Dict[str, Any]]:
        url_hash = self._url_hash(url)
        path = os.path.join(self._base, "citations", f"{url_hash}.json")
        return self._read(path)

    # -- Affinity ----------------------------------------------------

    def record_affinity(
        self, skill_name: str, keywords: List[str], hit_count: int
    ) -> None:
        path = os.path.join(
            self._base, "affinity", f"{skill_name.replace('/', '_')}.json"
        )
        existing = self._read(path) or {
            "skill_name": skill_name,
            "type": "affinity",
            "keyword_hits": {},
        }
        for kw in keywords:
            kw_lower = kw.lower()
            prev = existing["keyword_hits"].get(kw_lower, 0)
            existing["keyword_hits"][kw_lower] = prev + hit_count
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(path, existing)

    def get_top_skills_for_keywords(
        self, keywords: List[str], limit: int = 5
    ) -> List[Dict[str, Any]]:
        folder = os.path.join(self._base, "affinity")
        scored: List[Dict[str, Any]] = []
        kw_set = {k.lower() for k in keywords}
        for f in Path(folder).glob("*.json"):
            data = self._read(str(f))
            if not data:
                continue
            hits = data.get("keyword_hits", {})
            score = sum(hits.get(k, 0) for k in kw_set)
            if score > 0:
                scored.append({"skill_name": data["skill_name"], "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    # -- Full run bundles --------------------------------------------

    def save_full_run(self, run_bundle: Dict[str, Any]) -> str:
        run_id = run_bundle.get("id") or str(uuid.uuid4())
        run_bundle["id"] = run_id
        run_bundle["type"] = "full_run"
        run_bundle.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        path = os.path.join(self._base, "runs", f"{run_id}.json")
        self._write(path, run_bundle)
        return run_id

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self._base, "runs", f"{run_id}.json")
        return self._read(path)


# =====================================================================
# Cosmos DB backend (production)
# =====================================================================

class CosmosSkillsBackend(SkillsStoreBackend):
    """
    Azure Cosmos DB backend for the skills container.

    Partition key: ``/skill_name`` -- each skill source gets its own
    logical partition for efficient per-skill queries.

    Full-run bundles use ``skill_name = "__run__"`` as a synthetic partition.
    """

    _SYSTEM_KEYS = ("_rid", "_self", "_etag", "_attachments", "_ts")

    def __init__(
        self,
        endpoint: str,
        key: str,
        database: str = "llm-council",
        container_name: str = "skills",
    ):
        from azure.cosmos import CosmosClient, PartitionKey

        client = CosmosClient(endpoint, credential=key)
        db = client.create_database_if_not_exists(id=database)
        self._container = db.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path="/skill_name"),
        )

    def _strip(self, item: dict) -> dict:
        for k in self._SYSTEM_KEYS:
            item.pop(k, None)
        return item

    @staticmethod
    def _url_hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    # -- Executions --------------------------------------------------

    def save_execution(self, skill_name: str, doc: Dict[str, Any]) -> str:
        doc_id = doc.get("id") or str(uuid.uuid4())
        item = dict(doc)
        item["id"] = doc_id
        item["skill_name"] = skill_name
        item["type"] = "execution"
        item.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self._container.upsert_item(item)
        return doc_id

    def get_recent_executions(
        self, skill_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        sql = (
            f"SELECT TOP {int(limit)} * FROM c "
            f"WHERE c.skill_name = @sk AND c.type = 'execution' "
            f"ORDER BY c.timestamp DESC"
        )
        params = [{"name": "@sk", "value": skill_name}]
        items = list(self._container.query_items(
            query=sql,
            parameters=params,
            enable_cross_partition_query=False,
        ))
        return [self._strip(i) for i in items]

    # -- Health ------------------------------------------------------

    def update_health(self, skill_name: str, metrics: Dict[str, Any]) -> None:
        doc_id = f"health-{skill_name.replace('/', '_').replace(' ', '_').lower()}"
        item = dict(metrics)
        item["id"] = doc_id
        item["skill_name"] = skill_name
        item["type"] = "health"
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._container.upsert_item(item)

    def get_health(self, skill_name: str) -> Optional[Dict[str, Any]]:
        doc_id = f"health-{skill_name.replace('/', '_').replace(' ', '_').lower()}"
        try:
            item = self._container.read_item(item=doc_id, partition_key=skill_name)
            return self._strip(item)
        except Exception:
            return None

    def get_all_health(self) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM c WHERE c.type = 'health'"
        items = list(self._container.query_items(
            query=sql,
            parameters=[],
            enable_cross_partition_query=True,
        ))
        return [self._strip(i) for i in items]

    # -- Citation cache ----------------------------------------------

    def cache_citation(self, skill_name: str, citation: Dict[str, Any]) -> None:
        url = citation.get("url", "")
        if not url:
            return
        url_hash = self._url_hash(url)
        item = dict(citation)
        item["id"] = f"cite-{url_hash}"
        item["skill_name"] = skill_name
        item["type"] = "citation"
        item["url_hash"] = url_hash
        item["cached_at"] = datetime.now(timezone.utc).isoformat()
        self._container.upsert_item(item)

    def get_cached_citation(self, url: str) -> Optional[Dict[str, Any]]:
        url_hash = self._url_hash(url)
        doc_id = f"cite-{url_hash}"
        # Citation could be in any skill partition, so cross-partition query
        sql = "SELECT * FROM c WHERE c.id = @id AND c.type = 'citation'"
        params = [{"name": "@id", "value": doc_id}]
        items = list(self._container.query_items(
            query=sql,
            parameters=params,
            enable_cross_partition_query=True,
        ))
        return self._strip(items[0]) if items else None

    # -- Affinity ----------------------------------------------------

    def record_affinity(
        self, skill_name: str, keywords: List[str], hit_count: int
    ) -> None:
        doc_id = f"affinity-{skill_name.replace('/', '_').replace(' ', '_').lower()}"
        # Read-modify-write (upsert pattern)
        try:
            existing = self._container.read_item(item=doc_id, partition_key=skill_name)
            self._strip(existing)
        except Exception:
            existing = {
                "id": doc_id,
                "skill_name": skill_name,
                "type": "affinity",
                "keyword_hits": {},
            }
        kw_hits = existing.get("keyword_hits", {})
        for kw in keywords:
            kw_lower = kw.lower()
            kw_hits[kw_lower] = kw_hits.get(kw_lower, 0) + hit_count
        existing["keyword_hits"] = kw_hits
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._container.upsert_item(existing)

    def get_top_skills_for_keywords(
        self, keywords: List[str], limit: int = 5
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM c WHERE c.type = 'affinity'"
        items = list(self._container.query_items(
            query=sql,
            parameters=[],
            enable_cross_partition_query=True,
        ))
        kw_set = {k.lower() for k in keywords}
        scored = []
        for item in items:
            hits = item.get("keyword_hits", {})
            score = sum(hits.get(k, 0) for k in kw_set)
            if score > 0:
                scored.append({
                    "skill_name": item.get("skill_name", ""),
                    "score": score,
                })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    # -- Full run bundles --------------------------------------------

    def save_full_run(self, run_bundle: Dict[str, Any]) -> str:
        run_id = run_bundle.get("id") or str(uuid.uuid4())
        item = dict(run_bundle)
        item["id"] = run_id
        item["skill_name"] = "__run__"   # synthetic partition for run bundles
        item["type"] = "full_run"
        item.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self._container.upsert_item(item)
        return run_id

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        try:
            item = self._container.read_item(item=run_id, partition_key="__run__")
            return self._strip(item)
        except Exception:
            return None


# =====================================================================
# Singleton accessor
# =====================================================================

_skills_store_instance: Optional[SkillsStoreBackend] = None


def get_skills_store() -> SkillsStoreBackend:
    """Return the active skills store backend (lazy-init).

    Priority:
      1. Cosmos DB -- if COSMOS_ENDPOINT + COSMOS_KEY are set
      2. Local JSON -- file-based fallback for dev
    """
    global _skills_store_instance
    if _skills_store_instance is None:
        from .config import (
            COSMOS_ENDPOINT,
            COSMOS_KEY,
            COSMOS_DATABASE,
            COSMOS_SKILLS_CONTAINER,
        )
        if COSMOS_ENDPOINT and COSMOS_KEY:
            logger.info("[SkillsStore] Using Cosmos DB backend")
            _skills_store_instance = CosmosSkillsBackend(
                endpoint=COSMOS_ENDPOINT,
                key=COSMOS_KEY,
                database=COSMOS_DATABASE,
                container_name=COSMOS_SKILLS_CONTAINER,
            )
        else:
            logger.info("[SkillsStore] Using local JSON backend")
            _skills_store_instance = LocalSkillsBackend()
    return _skills_store_instance


def set_skills_store(backend: SkillsStoreBackend):
    """Swap the backend at runtime (for tests or hot-swap)."""
    global _skills_store_instance
    _skills_store_instance = backend
