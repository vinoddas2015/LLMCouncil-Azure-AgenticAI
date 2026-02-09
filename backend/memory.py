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

import uuid
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .memory_store import get_memory_backend

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
                if include_unlearned or doc.get("status") != "unlearned":
                    entries.append(doc)
        entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return entries


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


# ── Singleton ────────────────────────────────────────────────────────

_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
