"""
Three-tier Memory Management for the LLM Council.

Implements Semantic, Episodic, and Procedural memory with learn/unlearn
capabilities tied to the grounding confidence score.

Memory Types
────────────
• **Semantic**    – Domain knowledge & facts extracted from council decisions.
                    Entries are keyed by topic and de-duplicated to build a
                    growing knowledge base that future councils can consult.

• **Episodic**    – Per-conversation decision records: what the council decided,
                    which models ranked highest, the grounding score, cost, and
                    the user's learn/unlearn verdict.

• **Procedural**  – Recurring workflow patterns, templates, and procedures the
                    council has learned to follow for specific task categories.

Learn / Unlearn
───────────────
At each stage gate, the end user can:
  • **Learn**   – Persist the decision into the appropriate memory tier(s).
                  Future councils will retrieve this as prior context.
  • **Unlearn** – Mark an existing memory entry as deprecated/removed so it
                  stops influencing future councils.  The raw record is kept
                  with a `"status": "unlearned"` flag for audit.

Confidence Feedback Loop
────────────────────────
Grounding scores for retrieved memories are used to weight their influence
on future councils.  Low-scoring memories decay in priority; high-scoring
ones are boosted.  Users can override this via explicit learn/unlearn.
"""

from __future__ import annotations

import math
import uuid
import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .memory_store import get_memory_backend, set_memory_user, get_memory_user

logger = logging.getLogger("llm_council.memory")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Semantic Memory                                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

class SemanticMemory:
    """
    Domain knowledge derived from council decisions.
    Each entry: topic, facts, source conversation, confidence.
    """

    COLLECTION = "semantic"

    def store(
        self,
        topic: str,
        facts: List[str],
        source_conversation_id: str,
        source_query: str,
        confidence: float,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        backend = get_memory_backend()
        entry_id = self._topic_key(topic)
        existing = backend.get(self.COLLECTION, entry_id)

        now = datetime.now(timezone.utc).isoformat()

        if existing and existing.get("status") != "unlearned":
            # Merge new facts into existing entry
            old_facts = set(existing.get("facts", []))
            merged = list(old_facts | set(facts))
            existing["facts"] = merged
            existing["confidence"] = max(existing.get("confidence", 0), confidence)
            existing["updated_at"] = now
            existing["source_conversations"] = list(
                set(existing.get("source_conversations", []) + [source_conversation_id])
            )
            existing["tags"] = list(set(existing.get("tags", []) + (tags or [])))
            backend.put(self.COLLECTION, entry_id, existing)
            logger.info(f"[SemanticMemory] Merged into '{topic}' ({len(merged)} facts)")
            return existing

        entry = {
            "id": entry_id,
            "type": "semantic",
            "topic": topic,
            "facts": facts,
            "source_conversations": [source_conversation_id],
            "source_query": source_query,
            "confidence": round(confidence, 4),
            "tags": tags or [],
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "access_count": 0,
        }
        backend.put(self.COLLECTION, entry_id, entry)
        logger.info(f"[SemanticMemory] Stored '{topic}' ({len(facts)} facts)")
        return entry

    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        backend = get_memory_backend()
        results = backend.search(self.COLLECTION, query, limit=limit * 2)
        # Filter out unlearned
        active = [r for r in results if r.get("status") != "unlearned"][:limit]
        # Boost access count
        for r in active:
            r["access_count"] = r.get("access_count", 0) + 1
            backend.put(self.COLLECTION, r["id"], r)
        return active

    def unlearn(self, topic: str, reason: str = "") -> bool:
        backend = get_memory_backend()
        entry_id = self._topic_key(topic)
        existing = backend.get(self.COLLECTION, entry_id)
        if not existing:
            return False
        existing["status"] = "unlearned"
        existing["unlearned_at"] = datetime.now(timezone.utc).isoformat()
        existing["unlearn_reason"] = reason
        backend.put(self.COLLECTION, entry_id, existing)
        logger.info(f"[SemanticMemory] Unlearned '{topic}'")
        return True

    def relearn(self, topic: str) -> bool:
        backend = get_memory_backend()
        entry_id = self._topic_key(topic)
        existing = backend.get(self.COLLECTION, entry_id)
        if not existing:
            return False
        existing["status"] = "active"
        existing.pop("unlearned_at", None)
        existing.pop("unlearn_reason", None)
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        backend.put(self.COLLECTION, entry_id, existing)
        logger.info(f"[SemanticMemory] Re-learned '{topic}'")
        return True

    def list_all(self, include_unlearned: bool = False) -> List[Dict[str, Any]]:
        backend = get_memory_backend()
        keys = backend.list_keys(self.COLLECTION)
        entries = []
        for k in keys:
            doc = backend.get(self.COLLECTION, k)
            if doc:
                if include_unlearned or doc.get("status") != "unlearned":
                    entries.append(doc)
        entries.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return entries

    @staticmethod
    def _topic_key(topic: str) -> str:
        slug = topic.lower().strip().replace(" ", "_")[:60]
        # Remove characters invalid in filenames (Windows + Unix)
        slug = "".join(c for c in slug if c.isalnum() or c in ("_", "-"))
        h = hashlib.md5(topic.lower().strip().encode()).hexdigest()[:8]
        return f"{slug}_{h}"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Episodic Memory                                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

class EpisodicMemory:
    """
    Records of specific council deliberations — what happened, who won,
    grounding score, cost, and user's learn/unlearn verdict.
    """

    COLLECTION = "episodic"

    def store(
        self,
        conversation_id: str,
        query: str,
        stage1_summary: List[Dict[str, Any]],
        aggregate_rankings: List[Dict[str, Any]],
        chairman_model: str,
        chairman_response_preview: str,
        grounding_score: float,
        cost_summary: Optional[Dict[str, Any]] = None,
        user_verdict: str = "pending",  # "learn" | "unlearn" | "pending"
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        backend = get_memory_backend()
        entry_id = f"ep_{conversation_id}_{uuid.uuid4().hex[:6]}"

        entry = {
            "id": entry_id,
            "type": "episodic",
            "conversation_id": conversation_id,
            "query": query,
            "stage1_models": [s.get("model") for s in stage1_summary],
            "aggregate_rankings": aggregate_rankings,
            "chairman_model": chairman_model,
            "chairman_response_preview": chairman_response_preview[:500],
            "grounding_score": round(grounding_score, 4),
            "cost_summary": cost_summary,
            "user_verdict": user_verdict,
            "tags": tags or [],
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        backend.put(self.COLLECTION, entry_id, entry)
        logger.info(f"[EpisodicMemory] Stored episode for conv={conversation_id} (grounding={grounding_score:.2%})")
        return entry

    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        backend = get_memory_backend()
        results = backend.search(self.COLLECTION, query, limit=limit * 2)
        active = [r for r in results if r.get("status") != "unlearned"][:limit]
        return active

    def recall_by_conversation(self, conversation_id: str) -> List[Dict[str, Any]]:
        backend = get_memory_backend()
        return backend.query(self.COLLECTION, {"conversation_id": conversation_id})

    def update_verdict(self, episode_id: str, verdict: str, reason: str = "") -> bool:
        backend = get_memory_backend()
        doc = backend.get(self.COLLECTION, episode_id)
        if not doc:
            return False
        doc["user_verdict"] = verdict
        doc["verdict_reason"] = reason
        doc["verdict_at"] = datetime.now(timezone.utc).isoformat()
        if verdict == "unlearn":
            doc["status"] = "unlearned"
        elif verdict == "learn":
            doc["status"] = "active"
        backend.put(self.COLLECTION, episode_id, doc)
        logger.info(f"[EpisodicMemory] Verdict '{verdict}' on {episode_id}")
        return True

    def list_all(self, include_unlearned: bool = False) -> List[Dict[str, Any]]:
        backend = get_memory_backend()
        keys = backend.list_keys(self.COLLECTION)
        entries = []
        for k in keys:
            doc = backend.get(self.COLLECTION, k)
            if doc:
                # The episodic collection is shared by multiple subsystems
                # (ca_snapshot, user_profile_interaction, eca_state).
                # Only include actual episodic memory entries.
                if doc.get("type") not in ("episodic", None):
                    continue
                if include_unlearned or doc.get("status") != "unlearned":
                    entries.append(doc)
        entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return entries

    def find_duplicate(
        self, query: str, similarity_threshold: float = 0.55,
    ) -> Optional[Dict[str, Any]]:
        """
        Check if a near-duplicate episodic memory already exists for this query.

        Uses word-level Jaccard similarity — effective for detecting
        re-submitted queries or documents even with minor prompt variations.

        Args:
            query: The new user query (may include extracted document text).
            similarity_threshold: Jaccard similarity cutoff (0-1).

        Returns:
            The best-matching episodic memory if above threshold, else None.
        """
        all_episodes = self.list_all(include_unlearned=False)
        if not all_episodes:
            return None

        query_words = set(query.lower().split())
        if len(query_words) < 3:
            return None

        best_match = None
        best_score = 0.0

        for ep in all_episodes:
            ep_query = ep.get("query", "")
            if not ep_query:
                continue
            ep_words = set(ep_query.lower().split())
            if not ep_words:
                continue
            intersection = query_words & ep_words
            union = query_words | ep_words
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard > best_score:
                best_score = jaccard
                best_match = ep

        if best_score >= similarity_threshold and best_match:
            best_match = {**best_match, "_similarity": round(best_score, 4)}
            return best_match
        return None


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Procedural Memory                                                  ║
# ╚══════════════════════════════════════════════════════════════════════╝

class ProceduralMemory:
    """
    Workflow patterns and procedures the council has learned from
    repeated similar tasks — templates, step sequences, best practices.
    """

    COLLECTION = "procedural"

    def store(
        self,
        task_type: str,
        procedure: str,
        steps: List[str],
        source_conversations: List[str],
        confidence: float,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        backend = get_memory_backend()
        entry_id = self._task_key(task_type)
        existing = backend.get(self.COLLECTION, entry_id)

        now = datetime.now(timezone.utc).isoformat()

        if existing and existing.get("status") != "unlearned":
            # Reinforce / update existing procedure
            existing["procedure"] = procedure
            existing["steps"] = steps
            existing["confidence"] = max(existing.get("confidence", 0), confidence)
            existing["reinforcement_count"] = existing.get("reinforcement_count", 0) + 1
            existing["source_conversations"] = list(
                set(existing.get("source_conversations", []) + source_conversations)
            )
            existing["tags"] = list(set(existing.get("tags", []) + (tags or [])))
            existing["updated_at"] = now
            backend.put(self.COLLECTION, entry_id, existing)
            logger.info(f"[ProceduralMemory] Reinforced '{task_type}' (×{existing['reinforcement_count']})")
            return existing

        entry = {
            "id": entry_id,
            "type": "procedural",
            "task_type": task_type,
            "procedure": procedure,
            "steps": steps,
            "source_conversations": source_conversations,
            "confidence": round(confidence, 4),
            "reinforcement_count": 1,
            "tags": tags or [],
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "access_count": 0,
        }
        backend.put(self.COLLECTION, entry_id, entry)
        logger.info(f"[ProceduralMemory] Stored '{task_type}' ({len(steps)} steps)")
        return entry

    def recall(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        backend = get_memory_backend()
        results = backend.search(self.COLLECTION, query, limit=limit * 2)
        active = [r for r in results if r.get("status") != "unlearned"][:limit]
        for r in active:
            r["access_count"] = r.get("access_count", 0) + 1
            backend.put(self.COLLECTION, r["id"], r)
        return active

    def unlearn(self, task_type: str, reason: str = "") -> bool:
        backend = get_memory_backend()
        entry_id = self._task_key(task_type)
        existing = backend.get(self.COLLECTION, entry_id)
        if not existing:
            return False
        existing["status"] = "unlearned"
        existing["unlearned_at"] = datetime.now(timezone.utc).isoformat()
        existing["unlearn_reason"] = reason
        backend.put(self.COLLECTION, entry_id, existing)
        logger.info(f"[ProceduralMemory] Unlearned '{task_type}'")
        return True

    def relearn(self, task_type: str) -> bool:
        backend = get_memory_backend()
        entry_id = self._task_key(task_type)
        existing = backend.get(self.COLLECTION, entry_id)
        if not existing:
            return False
        existing["status"] = "active"
        existing.pop("unlearned_at", None)
        existing.pop("unlearn_reason", None)
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        backend.put(self.COLLECTION, entry_id, existing)
        logger.info(f"[ProceduralMemory] Re-learned '{task_type}'")
        return True

    def list_all(self, include_unlearned: bool = False) -> List[Dict[str, Any]]:
        backend = get_memory_backend()
        keys = backend.list_keys(self.COLLECTION)
        entries = []
        for k in keys:
            doc = backend.get(self.COLLECTION, k)
            if doc:
                if include_unlearned or doc.get("status") != "unlearned":
                    entries.append(doc)
        entries.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return entries

    @staticmethod
    def _task_key(task_type: str) -> str:
        slug = task_type.lower().strip().replace(" ", "_")[:60]
        # Remove characters invalid in filenames (Windows + Unix)
        slug = "".join(c for c in slug if c.isalnum() or c in ("_", "-"))
        h = hashlib.md5(task_type.lower().strip().encode()).hexdigest()[:8]
        return f"{slug}_{h}"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Unified MemoryManager                                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

class MemoryManager:
    """
    Facade that orchestrates all three memory tiers, provides combined
    recall for council augmentation, and exposes learn/unlearn controls.
    """

    def __init__(self):
        self.semantic = SemanticMemory()
        self.episodic = EpisodicMemory()
        self.procedural = ProceduralMemory()

    # ── Combined recall for council augmentation ─────────────────────

    def recall_for_query(self, query: str, limit_per_tier: int = 3) -> Dict[str, Any]:
        """
        Retrieve relevant memories across all tiers for a new council query.
        Returns a structured context block that can be injected into prompts.
        """
        semantic_hits = self.semantic.recall(query, limit=limit_per_tier)
        episodic_hits = self.episodic.recall(query, limit=limit_per_tier)
        procedural_hits = self.procedural.recall(query, limit=limit_per_tier)

        return {
            "semantic": semantic_hits,
            "episodic": episodic_hits,
            "procedural": procedural_hits,
            "total": len(semantic_hits) + len(episodic_hits) + len(procedural_hits),
        }

    def format_memory_context(self, memories: Dict[str, Any]) -> str:
        """
        Format recalled memories into a text block for prompt injection.
        Only includes memories above a confidence threshold.
        """
        parts = []
        CONFIDENCE_THRESHOLD = 0.4

        # Semantic — prior domain knowledge
        sem = [m for m in memories.get("semantic", [])
               if m.get("confidence", 0) >= CONFIDENCE_THRESHOLD]
        if sem:
            parts.append("=== PRIOR DOMAIN KNOWLEDGE (from council memory) ===")
            for m in sem:
                facts_text = "; ".join(m.get("facts", [])[:5])
                parts.append(f"• Topic: {m['topic']} (confidence: {m['confidence']:.0%})")
                parts.append(f"  Facts: {facts_text}")
            parts.append("")

        # Episodic — past similar deliberations
        epi = [m for m in memories.get("episodic", [])
               if m.get("grounding_score", 0) >= CONFIDENCE_THRESHOLD]
        if epi:
            parts.append("=== PAST SIMILAR DELIBERATIONS ===")
            for m in epi:
                parts.append(f"• Query: \"{m.get('query', '')[:150]}\"")
                parts.append(f"  Chairman: {m.get('chairman_model', '?')} | "
                             f"Grounding: {m.get('grounding_score', 0):.0%}")
                preview = m.get("chairman_response_preview", "")[:200]
                parts.append(f"  Decision: {preview}...")
            parts.append("")

        # Procedural — learned workflows
        proc = [m for m in memories.get("procedural", [])
                if m.get("confidence", 0) >= CONFIDENCE_THRESHOLD]
        if proc:
            parts.append("=== LEARNED PROCEDURES ===")
            for m in proc:
                parts.append(f"• Procedure: {m['task_type']} (confidence: {m['confidence']:.0%})")
                steps = m.get("steps", [])
                for i, step in enumerate(steps[:5], 1):
                    parts.append(f"  {i}. {step}")
            parts.append("")

        if not parts:
            return ""

        return "\n".join(parts) + "\n---\n\n"

    # ── Post-council learning ────────────────────────────────────────

    def learn_from_council(
        self,
        conversation_id: str,
        query: str,
        stage1_results: List[Dict[str, Any]],
        aggregate_rankings: List[Dict[str, Any]],
        stage3_result: Dict[str, Any],
        grounding_score: float,
        cost_summary: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Automatically extract & store memories after a council deliberation.
        Returns a summary of what was learned for the frontend.
        """
        learned = {"semantic": None, "episodic": None, "procedural": None}

        # 1. Episodic — always store the deliberation record
        chairman_preview = stage3_result.get("response", "")[:500]
        episode = self.episodic.store(
            conversation_id=conversation_id,
            query=query,
            stage1_summary=stage1_results,
            aggregate_rankings=aggregate_rankings,
            chairman_model=stage3_result.get("model", "unknown"),
            chairman_response_preview=chairman_preview,
            grounding_score=grounding_score,
            cost_summary=cost_summary,
            user_verdict="pending",
            tags=tags,
        )
        learned["episodic"] = episode

        # 2. Semantic — extract topic & key facts if grounding is high enough
        if grounding_score >= 0.5:
            topic = self._extract_topic(query)
            facts = self._extract_facts(chairman_preview)
            if facts:
                sem = self.semantic.store(
                    topic=topic,
                    facts=facts,
                    source_conversation_id=conversation_id,
                    source_query=query,
                    confidence=grounding_score,
                    tags=tags,
                )
                learned["semantic"] = sem

        # 3. Procedural — detect if this is a "how-to" / process query
        if self._is_procedural_query(query) and grounding_score >= 0.6:
            task_type = self._extract_task_type(query)
            steps = self._extract_steps(chairman_preview)
            if steps:
                proc = self.procedural.store(
                    task_type=task_type,
                    procedure=chairman_preview[:300],
                    steps=steps,
                    source_conversations=[conversation_id],
                    confidence=grounding_score,
                    tags=tags,
                )
                learned["procedural"] = proc

        return learned

    # ── User learn/unlearn actions ──────────────────────────────────

    def user_learn(self, memory_type: str, memory_id: str) -> bool:
        """User confirms a memory should be kept active."""
        backend = get_memory_backend()
        doc = backend.get(memory_type, memory_id)
        if not doc:
            return False
        doc["status"] = "active"
        doc["user_verdict"] = "learn"
        doc.pop("unlearned_at", None)
        doc.pop("unlearn_reason", None)
        backend.put(memory_type, memory_id, doc)
        return True

    def user_unlearn(self, memory_type: str, memory_id: str, reason: str = "") -> bool:
        """User requests that a memory stop influencing future councils."""
        backend = get_memory_backend()
        doc = backend.get(memory_type, memory_id)
        if not doc:
            return False
        doc["status"] = "unlearned"
        doc["user_verdict"] = "unlearn"
        doc["unlearned_at"] = datetime.now(timezone.utc).isoformat()
        doc["unlearn_reason"] = reason
        backend.put(memory_type, memory_id, doc)
        return True

    # ── Context Awareness Cross-Session Tracking ─────────────────────

    CA_COLLECTION = "episodic"  # Store CA history alongside episode records

    def store_ca_snapshot(
        self,
        conversation_id: str,
        model: str,
        ca_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Persist a per-model Context Awareness snapshot for cross-session
        trend analysis.

        Stored in the episodic collection with type "ca_snapshot" so it
        can be queried alongside deliberation records.

        Args:
            conversation_id: The conversation this CA was measured in.
            model: Canonical model name (e.g. "claude-opus-4.6").
            ca_data: The context_awareness dict from grounding_scores.

        Returns:
            The stored document.
        """
        backend = get_memory_backend()
        entry_id = f"ca_{conversation_id}_{model.replace('/', '_')}_{uuid.uuid4().hex[:6]}"

        entry = {
            "id": entry_id,
            "type": "ca_snapshot",
            "conversation_id": conversation_id,
            "model": model,
            "score": ca_data.get("score"),
            "self_tp": ca_data.get("self_tp", 0),
            "self_fp": ca_data.get("self_fp", 0),
            "self_fn": ca_data.get("self_fn", 0),
            "round1_score": ca_data.get("round1_score"),
            "round2_score": ca_data.get("round2_score"),
            "stability": ca_data.get("stability"),
            "combined_score": ca_data.get("combined_score"),
            "adversarial_delta": ca_data.get("adversarial_delta"),
            "shuffled": ca_data.get("shuffled", False),
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        backend.put(self.CA_COLLECTION, entry_id, entry)
        logger.info(
            f"[MemoryManager] CA snapshot stored for {model} "
            f"(score={ca_data.get('score')}, conv={conversation_id})"
        )
        return entry

    def get_ca_trend(
        self,
        model: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve historical CA snapshots for a specific model, sorted
        newest-first.

        Args:
            model: Model name to query (e.g. "claude-opus-4.6").
            limit: Maximum number of snapshots to return.

        Returns:
            List of ca_snapshot documents, newest first.
        """
        backend = get_memory_backend()
        all_snapshots = backend.query(self.CA_COLLECTION, {"type": "ca_snapshot", "model": model})
        # Sort by created_at descending
        all_snapshots.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return all_snapshots[:limit]

    def get_ca_trends_all_models(
        self,
        limit_per_model: int = 10,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieve CA trends for ALL models that have snapshots.

        Returns:
            Dict mapping model name → list of snapshots (newest first).
        """
        backend = get_memory_backend()
        keys = backend.list_keys(self.CA_COLLECTION)
        model_snapshots: Dict[str, List[Dict[str, Any]]] = {}
        for k in keys:
            doc = backend.get(self.CA_COLLECTION, k)
            if doc and doc.get("type") == "ca_snapshot":
                model = doc.get("model", "unknown")
                if model not in model_snapshots:
                    model_snapshots[model] = []
                model_snapshots[model].append(doc)
        # Sort each model's snapshots newest first and limit
        for model in model_snapshots:
            model_snapshots[model].sort(
                key=lambda x: x.get("created_at", ""), reverse=True
            )
            model_snapshots[model] = model_snapshots[model][:limit_per_model]
        return model_snapshots

    # ── Statistics ───────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        sem_all = self.semantic.list_all(include_unlearned=True)
        epi_all = self.episodic.list_all(include_unlearned=True)
        proc_all = self.procedural.list_all(include_unlearned=True)
        return {
            "semantic": {
                "total": len(sem_all),
                "active": sum(1 for e in sem_all if e.get("status") == "active"),
                "unlearned": sum(1 for e in sem_all if e.get("status") == "unlearned"),
            },
            "episodic": {
                "total": len(epi_all),
                "active": sum(1 for e in epi_all if e.get("status") == "active"),
                "unlearned": sum(1 for e in epi_all if e.get("status") == "unlearned"),
            },
            "procedural": {
                "total": len(proc_all),
                "active": sum(1 for e in proc_all if e.get("status") == "active"),
                "unlearned": sum(1 for e in proc_all if e.get("status") == "unlearned"),
            },
        }

    # ── Private helpers ──────────────────────────────────────────────

    @staticmethod
    def _extract_topic(query: str) -> str:
        # Simple: use the first ~60 chars, cleaned up
        cleaned = query.strip().replace("\n", " ")[:80]
        return cleaned

    @staticmethod
    def _extract_facts(text: str) -> List[str]:
        """Extract sentence-level facts from the chairman response."""
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        facts = []
        for s in sentences:
            s = s.strip()
            if len(s) > 20 and len(s) < 500:
                facts.append(s)
            if len(facts) >= 10:
                break
        return facts

    @staticmethod
    def _is_procedural_query(query: str) -> bool:
        q = query.lower()
        procedural_signals = [
            "how to", "how do", "steps to", "process for", "procedure",
            "workflow", "best practice", "guide", "tutorial", "implement",
            "set up", "configure", "deploy", "migrate", "pipeline",
        ]
        return any(signal in q for signal in procedural_signals)

    @staticmethod
    def _extract_task_type(query: str) -> str:
        """Extract a short task type label from the query."""
        q = query.strip().replace("\n", " ")
        # Remove common prefixes
        for prefix in ("how to ", "how do i ", "what are the steps to ",
                       "what is the process for ", "how can i "):
            if q.lower().startswith(prefix):
                q = q[len(prefix):]
                break
        return q[:80].strip()

    @staticmethod
    def _extract_steps(text: str) -> List[str]:
        """Extract numbered/bulleted steps from text."""
        import re
        steps = []
        # Match numbered lists: 1. ... or 1) ...
        numbered = re.findall(r'\d+[.)]\s+(.+?)(?=\n\d+[.)]|\n\n|$)', text, re.DOTALL)
        if numbered:
            steps = [s.strip()[:200] for s in numbered if len(s.strip()) > 10]
        if not steps:
            # Try bullet points: - ... or • ...
            bullets = re.findall(r'[•\-\*]\s+(.+?)(?=\n[•\-\*]|\n\n|$)', text, re.DOTALL)
            steps = [s.strip()[:200] for s in bullets if len(s.strip()) > 10]
        return steps[:10]


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  User Profile Memory — Behaviour Learning & Relevancy Tracking      ║
# ╚══════════════════════════════════════════════════════════════════════╝

# Domain keywords for auto-classification
_DOMAIN_MAP = {
    "pharma": [
        "drug", "compound", "molecule", "clinical", "trial", "fda", "ema",
        "dosage", "pharmacokinetic", "pharmacodynamic", "pk/pd", "adme",
        "toxicology", "oncology", "cardiology", "neurology", "immunology",
        "antibody", "vaccine", "biosimilar", "formulation", "excipient",
    ],
    "chemistry": [
        "synthesis", "reaction", "smiles", "inchi", "chemical", "catalyst",
        "reagent", "yield", "stereochemistry", "chromatography", "nmr",
        "mass spec", "ic50", "ec50", "ki", "kd", "binding affinity",
    ],
    "regulatory": [
        "regulatory", "compliance", "submission", "ind", "nda", "bla",
        "ectd", "ich", "gmp", "gcp", "glp", "audit", "inspection",
    ],
    "market_access": [
        "market access", "payer", "reimbursement", "hta", "nice", "iqwig",
        "pricing", "value proposition", "competitive", "positioning",
    ],
    "data_science": [
        "machine learning", "deep learning", "neural network", "model",
        "dataset", "pipeline", "api", "python", "statistics", "bayesian",
        "regression", "classification", "nlp", "llm", "transformer",
    ],
}

_QUESTION_TYPE_MAP = {
    "how_to": ["how to", "how do", "steps to", "process for", "procedure", "guide"],
    "comparison": ["compare", "versus", "vs", "difference between", "which is better"],
    "factual": ["what is", "what are", "define", "explain", "describe"],
    "analysis": ["analyze", "evaluate", "assess", "review", "critique"],
    "recommendation": ["recommend", "suggest", "best practice", "should i", "advise"],
}


class UserProfileMemory:
    """
    Tracks per-user query behaviour, relevancy violations, domain affinity,
    and grounding performance across sessions.

    Learning signals:
      • Domain classification → repeated domains boost affinity weights.
      • Question type tracking → recurring patterns become procedural hints.
      • Relevancy violations → high violation rate triggers chairman warnings.
      • Grounding scores → running mean per domain for adaptive thresholds.

    Persistence:
      Stored in the episodic collection with ``type: "user_profile"`` so it
      co-locates with conversation data and benefits from Cosmos partition.
    """

    COLLECTION = "episodic"

    # ── Query Classification ─────────────────────────────────────────

    @staticmethod
    def classify_query(query: str) -> Dict[str, Any]:
        """
        Auto-classify a user query into domain, question_type, and complexity.

        Returns::
            {
                "domain": str,            # top-scoring domain from _DOMAIN_MAP
                "domain_scores": dict,    # all domain hit counts
                "question_type": str,     # from _QUESTION_TYPE_MAP
                "complexity": str,        # "simple" | "moderate" | "complex"
                "word_count": int,
            }
        """
        q_lower = query.lower()
        words = query.split()
        word_count = len(words)

        # Domain scoring
        domain_scores: Dict[str, int] = {}
        for domain, keywords in _DOMAIN_MAP.items():
            score = sum(1 for kw in keywords if kw in q_lower)
            if score > 0:
                domain_scores[domain] = score
        top_domain = max(domain_scores, key=domain_scores.get) if domain_scores else "general"

        # Question type
        question_type = "general"
        for qtype, triggers in _QUESTION_TYPE_MAP.items():
            if any(t in q_lower for t in triggers):
                question_type = qtype
                break

        # Complexity heuristic
        if word_count < 15:
            complexity = "simple"
        elif word_count < 50:
            complexity = "moderate"
        else:
            complexity = "complex"

        return {
            "domain": top_domain,
            "domain_scores": domain_scores,
            "question_type": question_type,
            "complexity": complexity,
            "word_count": word_count,
        }

    # ── Per-Session Interaction Recording ────────────────────────────

    def record_interaction(
        self,
        user_id: str,
        query: str,
        grounding_score: float,
        relevancy_violations: List[str],
        gated_labels: List[str],
        classification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record a single council interaction for the user profile.

        Args:
            user_id: Scoped user identifier.
            query: The original user query.
            grounding_score: Overall council grounding score (0–1).
            relevancy_violations: Labels that were gated out.
            gated_labels: Same as relevancy_violations (explicit alias).
            classification: Pre-computed classify_query() result (optional).

        Returns:
            The stored interaction document.
        """
        backend = get_memory_backend()
        cls = classification or self.classify_query(query)
        entry_id = f"upi_{user_id}_{uuid.uuid4().hex[:8]}"

        doc = {
            "id": entry_id,
            "type": "user_profile_interaction",
            "user_id": user_id,
            "query_preview": query[:200],
            "domain": cls["domain"],
            "question_type": cls["question_type"],
            "complexity": cls["complexity"],
            "grounding_score": round(grounding_score, 4),
            "relevancy_violations": relevancy_violations,
            "gated_labels": gated_labels,
            "violation_count": len(relevancy_violations),
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        backend.put(self.COLLECTION, entry_id, doc)
        logger.info(
            f"[UserProfile] Recorded interaction for {user_id}: "
            f"domain={cls['domain']}, violations={len(relevancy_violations)}"
        )
        return doc

    # ── Aggregated User Profile ──────────────────────────────────────

    def get_user_profile(self, user_id: str, limit: int = 50) -> Dict[str, Any]:
        """
        Build an aggregated behavioural profile from recent interactions.

        Returns::
            {
                "user_id": str,
                "interaction_count": int,
                "domain_affinity": {domain: count},
                "question_patterns": {type: count},
                "avg_grounding": float,
                "relevancy_violation_rate": float,     # violations / interactions
                "total_violations": int,
                "recent_domains": [str],               # last 5 domains
                "complexity_distribution": {level: count},
                "warning_level": str | None,           # "high_violations" if rate > 0.3
            }
        """
        backend = get_memory_backend()
        all_keys = backend.list_keys(self.COLLECTION)
        interactions = []
        for k in all_keys:
            doc = backend.get(self.COLLECTION, k)
            if (doc
                    and doc.get("type") == "user_profile_interaction"
                    and doc.get("user_id") == user_id
                    and doc.get("status") == "active"):
                interactions.append(doc)

        interactions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        interactions = interactions[:limit]

        if not interactions:
            return {
                "user_id": user_id,
                "interaction_count": 0,
                "domain_affinity": {},
                "question_patterns": {},
                "avg_grounding": 0.0,
                "relevancy_violation_rate": 0.0,
                "total_violations": 0,
                "recent_domains": [],
                "complexity_distribution": {},
                "warning_level": None,
            }

        # Aggregate
        domain_counts: Dict[str, int] = defaultdict(int)
        qtype_counts: Dict[str, int] = defaultdict(int)
        complexity_counts: Dict[str, int] = defaultdict(int)
        grounding_sum = 0.0
        total_violations = 0
        recent_domains: List[str] = []

        for ix in interactions:
            domain_counts[ix.get("domain", "general")] += 1
            qtype_counts[ix.get("question_type", "general")] += 1
            complexity_counts[ix.get("complexity", "moderate")] += 1
            grounding_sum += ix.get("grounding_score", 0.0)
            total_violations += ix.get("violation_count", 0)
            if len(recent_domains) < 5:
                recent_domains.append(ix.get("domain", "general"))

        n = len(interactions)
        avg_grounding = grounding_sum / n if n else 0.0
        violation_rate = total_violations / n if n else 0.0

        # Warning threshold: if >30% of sessions have violations
        warning_level = "high_violations" if violation_rate > 0.3 else None

        return {
            "user_id": user_id,
            "interaction_count": n,
            "domain_affinity": dict(domain_counts),
            "question_patterns": dict(qtype_counts),
            "avg_grounding": round(avg_grounding, 4),
            "relevancy_violation_rate": round(violation_rate, 4),
            "total_violations": total_violations,
            "recent_domains": recent_domains,
            "complexity_distribution": dict(complexity_counts),
            "warning_level": warning_level,
        }

    # ── Prompt-Injectable Context Block ──────────────────────────────

    def format_user_context(self, user_id: str) -> str:
        """
        Format the user profile into a text block suitable for chairman
        prompt injection.  Returns empty string if no meaningful profile.
        """
        profile = self.get_user_profile(user_id)
        if profile["interaction_count"] < 2:
            return ""

        parts = ["=== USER BEHAVIOUR PROFILE ==="]

        # Domain expertise
        if profile["domain_affinity"]:
            top = sorted(profile["domain_affinity"].items(),
                         key=lambda x: x[1], reverse=True)[:3]
            domains_str = ", ".join(f"{d} ({c}x)" for d, c in top)
            parts.append(f"• Domain focus: {domains_str}")

        # Performance
        parts.append(f"• Avg grounding: {profile['avg_grounding']:.0%}")

        # Relevancy warnings
        if profile["warning_level"] == "high_violations":
            parts.append(
                f"⚠️ HIGH RELEVANCY VIOLATION RATE: {profile['relevancy_violation_rate']:.0%} "
                f"({profile['total_violations']} violations in {profile['interaction_count']} sessions). "
                "Apply EXTRA-STRICT relevancy filtering."
            )

        parts.append("")
        return "\n".join(parts) + "\n"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Experiential Co-Adaptation (ECA) — Memory × Skills Pairing         ║
# ╠══════════════════════════════════════════════════════════════════════╣
# ║                                                                      ║
# ║  Informed by:                                                        ║
# ║    • arXiv 2602.03837  — Memory & skills adaptation in AI systems    ║
# ║    • arXiv 2511.00926  — Adaptation in autonomous agents             ║
# ║    • arXiv 2602.13949v1 — Experiential Reinforcement Learning        ║
# ║                                                                      ║
# ║  Mathematical Framework:                                             ║
# ║    ECA treats (Memory, Skills) as a coupled dynamical system where   ║
# ║    the reward signal R(t) from skills execution performance feeds    ║
# ║    back into memory's learning parameters.                           ║
# ║                                                                      ║
# ║    R(t) = α·Quality(t) + β·Efficiency(t) + γ·Coverage(t)            ║
# ║      Quality   = avg citation relevance from reranker scores         ║
# ║      Efficiency = 1 − (avg_latency / max_latency)                   ║
# ║      Coverage   = unique_skills_hit / total_skills_available         ║
# ║                                                                      ║
# ║    Adaptation functions use exponential moving average (EMA):        ║
# ║      θ(t+1) = λ·θ(t) + (1−λ)·f(R(t))                              ║
# ║    where λ ∈ (0,1) is the memory decay factor and f maps reward     ║
# ║    to parameter adjustments.                                         ║
# ║                                                                      ║
# ╚══════════════════════════════════════════════════════════════════════╝

# ECA hyperparameters
ECA_ALPHA = 0.4    # weight for citation quality in reward signal
ECA_BETA = 0.3     # weight for latency efficiency
ECA_GAMMA = 0.3    # weight for skill coverage
ECA_LAMBDA = 0.7   # EMA decay factor (higher = more memory inertia)
ECA_TOTAL_SKILLS = 28  # total available evidence skills


class ExperientialCoAdaptation:
    """
    Implements the Memory × Skills pairing as a coupled adaptation loop.

    Three adaptation functions:
      1. ``adapt_prompt``   — adjusts chairman system prompt emphasis based on
                              user profile + skills performance history.
      2. ``adapt_rubric``   — adjusts rubric weight distribution based on
                              historical grounding patterns.
      3. ``adapt_learning`` — adjusts auto-learn thresholds and memory
                              confidence decay using experiential reward signals.

    The reward signal R(t) is computed from skills execution data:
      - Quality:    average reranker relevance score of returned citations
      - Efficiency: normalised inverse latency (fast skills rewarded)
      - Coverage:   fraction of skills that returned ≥1 result

    Reward → adaptation mapping uses EMA for smooth temporal evolution.
    """

    COLLECTION = "episodic"

    # ── Reward Signal Computation ────────────────────────────────────

    @staticmethod
    def compute_reward(evidence_bundle: Dict[str, Any]) -> Dict[str, float]:
        """
        Compute the experiential reward R(t) from a skills execution bundle.

        Args:
            evidence_bundle: The result from ``run_evidence_skills()``, containing
                ``citations``, ``skills_used``, ``reranker``, ``benchmark``.

        Returns::
            {
                "quality":    float,   # 0–1, avg citation relevance
                "efficiency": float,   # 0–1, normalised inverse latency
                "coverage":   float,   # 0–1, skill hit fraction
                "reward":     float,   # weighted composite R(t)
            }
        """
        if not evidence_bundle:
            return {"quality": 0.0, "efficiency": 0.0, "coverage": 0.0, "reward": 0.0}

        # Quality: average reranker relevance score
        reranker = evidence_bundle.get("reranker", {})
        top_scores = reranker.get("top_scores", [])
        quality = sum(top_scores) / len(top_scores) if top_scores else 0.0
        quality = min(1.0, max(0.0, quality))

        # Efficiency: 1 − (avg_latency / max_latency)
        benchmark = evidence_bundle.get("benchmark", {})
        latencies = benchmark.get("per_skill_latency_ms", {})
        if latencies:
            vals = [v for v in latencies.values() if isinstance(v, (int, float)) and v > 0]
            if vals:
                avg_lat = sum(vals) / len(vals)
                max_lat = max(vals)
                efficiency = 1.0 - (avg_lat / max_lat) if max_lat > 0 else 0.0
            else:
                efficiency = 0.0
        else:
            efficiency = 0.0
        efficiency = min(1.0, max(0.0, efficiency))

        # Coverage: unique_skills_hit / total_available
        skills_used = evidence_bundle.get("skills_used", [])
        coverage = len(skills_used) / ECA_TOTAL_SKILLS if ECA_TOTAL_SKILLS > 0 else 0.0
        coverage = min(1.0, max(0.0, coverage))

        # Composite reward
        reward = (
            ECA_ALPHA * quality
            + ECA_BETA * efficiency
            + ECA_GAMMA * coverage
        )

        return {
            "quality": round(quality, 4),
            "efficiency": round(efficiency, 4),
            "coverage": round(coverage, 4),
            "reward": round(reward, 4),
        }

    # ── ECA State Persistence ────────────────────────────────────────

    def _get_eca_state(self, user_id: str) -> Dict[str, Any]:
        """Load or initialise the ECA state for a user."""
        backend = get_memory_backend()
        state_id = f"eca_state_{hashlib.md5(user_id.encode()).hexdigest()[:12]}"
        existing = backend.get(self.COLLECTION, state_id)
        if existing and existing.get("type") == "eca_state":
            return existing
        # Initialise default state
        return {
            "id": state_id,
            "type": "eca_state",
            "user_id": user_id,
            # EMA-smoothed parameters
            "prompt_emphasis": {
                "evidence_weight": 0.5,  # how much to emphasise evidence in chairman
                "safety_weight": 0.5,    # emphasis on safety/regulatory language
                "precision_weight": 0.5, # emphasis on precision vs breadth
            },
            "rubric_weights": {
                "relevancy": 1.0,
                "faithfulness": 1.0,
                "completeness": 1.0,
                "safety": 1.0,
                "reasoning": 1.0,
            },
            "learning_params": {
                "auto_learn_threshold": 0.75,   # current threshold
                "confidence_decay": 0.02,        # per-session decay rate
                "min_confidence": 0.3,           # floor for confidence decay
            },
            "reward_history": [],   # last N reward snapshots
            "ema_reward": 0.5,      # running EMA of reward signal
            "adaptation_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save_eca_state(self, state: Dict[str, Any]) -> None:
        """Persist the ECA state."""
        backend = get_memory_backend()
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        backend.put(self.COLLECTION, state["id"], state)

    # ── Adaptation Function 1: adapt_prompt ──────────────────────────

    def adapt_prompt(
        self,
        user_id: str,
        user_profile: Dict[str, Any],
        reward: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Adjust chairman prompt emphasis parameters based on user profile
        and current skills performance.

        Mapping logic:
          • High quality reward → increase evidence_weight (trust evidence more)
          • High violation rate → increase safety_weight (stricter filtering)
          • User domain = pharma/chemistry → increase precision_weight

        Returns the updated prompt_emphasis dict.
        """
        state = self._get_eca_state(user_id)
        pe = state["prompt_emphasis"]
        r = reward.get("reward", 0.5)

        # EMA update: θ(t+1) = λ·θ(t) + (1−λ)·f(R(t))
        # f₁: evidence_weight ← R(quality) biased
        f_evidence = 0.3 + 0.4 * reward.get("quality", 0.5)
        pe["evidence_weight"] = round(
            ECA_LAMBDA * pe["evidence_weight"] + (1 - ECA_LAMBDA) * f_evidence, 4
        )

        # f₂: safety_weight ← violation rate biased
        violation_rate = user_profile.get("relevancy_violation_rate", 0.0)
        f_safety = 0.3 + 0.5 * violation_rate  # more violations → higher safety emphasis
        pe["safety_weight"] = round(
            ECA_LAMBDA * pe["safety_weight"] + (1 - ECA_LAMBDA) * f_safety, 4
        )

        # f₃: precision_weight ← domain-type biased
        domain = user_profile.get("recent_domains", ["general"])[0] if user_profile.get("recent_domains") else "general"
        domain_precision = 0.7 if domain in ("pharma", "chemistry", "regulatory") else 0.4
        pe["precision_weight"] = round(
            ECA_LAMBDA * pe["precision_weight"] + (1 - ECA_LAMBDA) * domain_precision, 4
        )

        state["prompt_emphasis"] = pe
        self._save_eca_state(state)

        logger.info(
            f"[ECA.adapt_prompt] user={user_id} evidence={pe['evidence_weight']:.2f} "
            f"safety={pe['safety_weight']:.2f} precision={pe['precision_weight']:.2f}"
        )
        return pe

    # ── Adaptation Function 2: adapt_rubric ──────────────────────────

    def adapt_rubric(
        self,
        user_id: str,
        user_profile: Dict[str, Any],
        grounding_scores: Dict[str, Any],
    ) -> Dict[str, float]:
        """
        Adjust Stage 2 rubric weight distribution based on historical
        grounding performance patterns.

        Mapping logic:
          • Low avg grounding across sessions → boost faithfulness weight
          • High violation rate → boost relevancy weight
          • Complex queries predominant → boost reasoning weight

        Returns the updated rubric_weights dict (normalised to sum=5.0).
        """
        state = self._get_eca_state(user_id)
        rw = state["rubric_weights"]

        avg_g = user_profile.get("avg_grounding", 0.5)
        vr = user_profile.get("relevancy_violation_rate", 0.0)
        complexity = user_profile.get("complexity_distribution", {})
        complex_ratio = complexity.get("complex", 0) / max(user_profile.get("interaction_count", 1), 1)

        # Boost faithfulness when grounding has been low
        f_faith = 1.0 + 0.5 * max(0, 0.6 - avg_g)  # boost if <60% grounding
        rw["faithfulness"] = round(
            ECA_LAMBDA * rw["faithfulness"] + (1 - ECA_LAMBDA) * f_faith, 4
        )

        # Boost relevancy when violations are frequent
        f_rel = 1.0 + 1.0 * vr  # linear scale with violation rate
        rw["relevancy"] = round(
            ECA_LAMBDA * rw["relevancy"] + (1 - ECA_LAMBDA) * f_rel, 4
        )

        # Boost reasoning for complex queries
        f_reason = 1.0 + 0.5 * complex_ratio
        rw["reasoning"] = round(
            ECA_LAMBDA * rw["reasoning"] + (1 - ECA_LAMBDA) * f_reason, 4
        )

        # Normalise to sum = 5.0 (5 criteria × baseline 1.0)
        total = sum(rw.values())
        if total > 0:
            scale = 5.0 / total
            rw = {k: round(v * scale, 4) for k, v in rw.items()}

        state["rubric_weights"] = rw
        self._save_eca_state(state)

        logger.info(
            f"[ECA.adapt_rubric] user={user_id} "
            + " ".join(f"{k}={v:.2f}" for k, v in rw.items())
        )
        return rw

    # ── Adaptation Function 3: adapt_learning ────────────────────────

    def adapt_learning(
        self,
        user_id: str,
        reward: Dict[str, float],
        grounding_score: float,
    ) -> Dict[str, float]:
        """
        Adjust auto-learn threshold and confidence decay parameters
        using the experiential reward signal.

        Mathematical model (EMA):
          ema_reward(t+1) = λ·ema_reward(t) + (1−λ)·R(t)

          If ema_reward is consistently high → lower the auto-learn
          threshold (trust the system more → learn more aggressively).

          If ema_reward is consistently low → raise threshold (require
          stronger evidence before auto-learning).

          Confidence decay adapts inversely: high reward → slower decay
          (memories persist longer); low reward → faster decay.

        Returns the updated learning_params dict.
        """
        state = self._get_eca_state(user_id)
        lp = state["learning_params"]
        r = reward.get("reward", 0.5)

        # Update EMA reward
        ema = state.get("ema_reward", 0.5)
        ema_new = ECA_LAMBDA * ema + (1 - ECA_LAMBDA) * r
        state["ema_reward"] = round(ema_new, 4)

        # Append to reward history (keep last 20)
        hist = state.get("reward_history", [])
        hist.append({
            "reward": round(r, 4),
            "grounding": round(grounding_score, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        state["reward_history"] = hist[-20:]

        # Adapt auto_learn_threshold:
        #   θ_learn(t+1) = clamp(0.5 + 0.3·(1 − ema_reward), [0.5, 0.9])
        #   High ema → threshold drops toward 0.5 (more aggressive learning)
        #   Low ema  → threshold rises toward 0.8 (conservative learning)
        new_threshold = 0.5 + 0.3 * (1.0 - ema_new)
        new_threshold = min(0.9, max(0.5, new_threshold))
        lp["auto_learn_threshold"] = round(new_threshold, 4)

        # Adapt confidence_decay:
        #   decay(t+1) = clamp(0.05·(1 − ema_reward), [0.005, 0.05])
        #   High ema → low decay (memories last longer)
        #   Low ema  → high decay (memories fade faster)
        new_decay = 0.05 * (1.0 - ema_new)
        new_decay = min(0.05, max(0.005, new_decay))
        lp["confidence_decay"] = round(new_decay, 4)

        state["learning_params"] = lp
        state["adaptation_count"] = state.get("adaptation_count", 0) + 1
        self._save_eca_state(state)

        logger.info(
            f"[ECA.adapt_learning] user={user_id} ema_reward={ema_new:.3f} "
            f"threshold={new_threshold:.3f} decay={new_decay:.4f} "
            f"adaptations={state['adaptation_count']}"
        )
        return lp

    # ── Combined Adaptation Pass ─────────────────────────────────────

    # ── Gated Reflection threshold (arXiv:2602.13949 §Gated Reflection) ──
    # Only fire adaptations when grounding falls below τ.  When grounding
    # is already above the threshold the current parameter set is working
    # well; adapting would risk overfitting on a lucky trajectory.
    ADAPTATION_TAU = 0.75  # τ gate — only adapt when grounding < τ

    def run_full_adaptation(
        self,
        user_id: str,
        user_profile: Dict[str, Any],
        evidence_bundle: Dict[str, Any],
        grounding_scores: Dict[str, Any],
        grounding_score_overall: float,
    ) -> Dict[str, Any]:
        """
        Execute all three adaptation functions in sequence for a given
        council session.

        Implements **Gated Reflection** (arXiv:2602.13949): adaptations
        only fire when ``grounding_score_overall`` < ``ADAPTATION_TAU``
        (default 0.75).  When grounding is already high, the current
        parameters are working — adapting further risks overfitting on
        a lucky trajectory.  The reward signal is always recorded for
        EMA tracking even when the gate blocks adaptation.

        Args:
            user_id: Current user.
            user_profile: From UserProfileMemory.get_user_profile().
            evidence_bundle: From run_evidence_skills().
            grounding_scores: Full grounding breakdown.
            grounding_score_overall: Scalar 0–1 overall grounding.

        Returns:
            Summary dict with all adapted parameters + gating flag.
        """
        reward = self.compute_reward(evidence_bundle)

        # ── τ-gate: skip prompt/rubric adaptation if grounding is strong ──
        if grounding_score_overall >= self.ADAPTATION_TAU:
            # Still record reward history + EMA for trend monitoring,
            # but skip the weight-modifying functions.
            learning_params = self.adapt_learning(user_id, reward, grounding_score_overall)
            state = self._get_eca_state(user_id)
            logger.info(
                f"[ECA.gated] SKIPPED adaptation for user={user_id} — "
                f"grounding={grounding_score_overall:.3f} ≥ τ={self.ADAPTATION_TAU} "
                f"(ema_reward={state.get('ema_reward', 0.5):.3f})"
            )
            return {
                "reward": reward,
                "prompt_emphasis": state.get("prompt_emphasis", {}),
                "rubric_weights": state.get("rubric_weights", {}),
                "learning_params": learning_params,
                "ema_reward": state.get("ema_reward", 0.5),
                "adaptation_count": state.get("adaptation_count", 0),
                "gated": True,
                "gate_reason": f"grounding {grounding_score_overall:.2f} ≥ τ {self.ADAPTATION_TAU}",
            }

        # ── Below τ — full adaptation pass ──
        prompt_emphasis = self.adapt_prompt(user_id, user_profile, reward)
        rubric_weights = self.adapt_rubric(user_id, user_profile, grounding_scores)
        learning_params = self.adapt_learning(user_id, reward, grounding_score_overall)

        return {
            "reward": reward,
            "prompt_emphasis": prompt_emphasis,
            "rubric_weights": rubric_weights,
            "learning_params": learning_params,
            "ema_reward": self._get_eca_state(user_id).get("ema_reward", 0.5),
            "adaptation_count": self._get_eca_state(user_id).get("adaptation_count", 0),
            "gated": False,
        }

    # ── Diagnostics ──────────────────────────────────────────────────

    def get_eca_state(self, user_id: str) -> Dict[str, Any]:
        """Public accessor for the current ECA state (read-only)."""
        return self._get_eca_state(user_id)


# ── Singleton ────────────────────────────────────────────────────────

_memory_manager: Optional[MemoryManager] = None
_user_profile_memory: Optional[UserProfileMemory] = None
_eca: Optional[ExperientialCoAdaptation] = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def get_user_profile_memory() -> UserProfileMemory:
    global _user_profile_memory
    if _user_profile_memory is None:
        _user_profile_memory = UserProfileMemory()
    return _user_profile_memory


def get_eca() -> ExperientialCoAdaptation:
    global _eca
    if _eca is None:
        _eca = ExperientialCoAdaptation()
    return _eca
