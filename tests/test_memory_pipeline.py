"""
LLM Council MGA — Memory Pipeline Test Suite
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tests all three memory tiers (Semantic, Episodic, Procedural), the cloud-
agnostic storage backend, orchestrator stage-gate agents, and end-to-end
pipeline simulation.

Run:
    python -m pytest tests/test_memory_pipeline.py -v
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_memory_dir(tmp_path):
    """
    Redirect the memory backend to a temp directory so tests never
    touch the real data/ folder.  Resets singletons after each test.
    """
    import backend.memory_store as ms
    import backend.memory as mem

    original_dir = ms.MEMORY_DIR
    test_dir = str(tmp_path / "memory")
    ms.MEMORY_DIR = test_dir

    # Reset singletons
    ms._backend_instance = None
    mem._memory_manager = None

    # Create fresh backend pointing to temp dir
    backend_inst = ms.LocalJSONBackend(base_dir=test_dir)
    ms.set_memory_backend(backend_inst)

    yield test_dir

    # Restore
    ms.MEMORY_DIR = original_dir
    ms._backend_instance = None
    mem._memory_manager = None


# ════════════════════════════════════════════════════════════════════
# 1. Memory Store Backend Tests
# ════════════════════════════════════════════════════════════════════

class TestLocalJSONBackend:

    def test_put_and_get(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        doc = {"id": "test-1", "content": "hello world", "score": 0.9}
        backend.put("semantic", "test-1", doc)
        retrieved = backend.get("semantic", "test-1")
        assert retrieved is not None
        assert retrieved["id"] == "test-1"
        assert retrieved["content"] == "hello world"

    def test_get_missing_key(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        result = backend.get("semantic", "nonexistent")
        assert result is None

    def test_delete(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        backend.put("semantic", "del-1", {"id": "del-1"})
        assert backend.delete("semantic", "del-1") is True
        assert backend.get("semantic", "del-1") is None
        assert backend.delete("semantic", "del-1") is False  # Already gone

    def test_list_keys(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        backend.put("semantic", "k1", {"id": "k1"})
        backend.put("semantic", "k2", {"id": "k2"})
        backend.put("episodic", "e1", {"id": "e1"})
        sem_keys = backend.list_keys("semantic")
        assert set(sem_keys) == {"k1", "k2"}
        epi_keys = backend.list_keys("episodic")
        assert epi_keys == ["e1"]

    def test_query_with_filters(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        backend.put("semantic", "a", {"id": "a", "status": "active", "topic": "python"})
        backend.put("semantic", "b", {"id": "b", "status": "unlearned", "topic": "java"})
        backend.put("semantic", "c", {"id": "c", "status": "active", "topic": "rust"})
        active = backend.query("semantic", {"status": "active"})
        assert len(active) == 2
        assert all(d["status"] == "active" for d in active)

    def test_search_relevance(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        backend.put("semantic", "py", {
            "id": "py", "topic": "python programming", "facts": ["Python is dynamically typed"]
        })
        backend.put("semantic", "rs", {
            "id": "rs", "topic": "rust systems programming", "facts": ["Rust is memory safe"]
        })
        results = backend.search("semantic", "python programming language")
        assert len(results) >= 1
        assert results[0]["id"] == "py"  # Python should rank higher

    def test_search_no_results(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        results = backend.search("semantic", "xyzzy")
        assert results == []

    def test_collections_isolated(self):
        from backend.memory_store import get_memory_backend
        backend = get_memory_backend()
        backend.put("semantic", "s1", {"id": "s1", "tier": "semantic"})
        backend.put("episodic", "s1", {"id": "s1", "tier": "episodic"})
        assert backend.get("semantic", "s1")["tier"] == "semantic"
        assert backend.get("episodic", "s1")["tier"] == "episodic"


# ════════════════════════════════════════════════════════════════════
# 2. Semantic Memory Tests
# ════════════════════════════════════════════════════════════════════

class TestSemanticMemory:

    def test_store_and_recall(self):
        from backend.memory import SemanticMemory
        sm = SemanticMemory()
        entry = sm.store(
            topic="FastAPI middleware",
            facts=["Middleware runs before route handlers", "Order matters"],
            source_conversation_id="conv-1",
            source_query="How does FastAPI middleware work?",
            confidence=0.85,
        )
        assert entry["status"] == "active"
        assert len(entry["facts"]) == 2

        results = sm.recall("FastAPI middleware", limit=5)
        assert len(results) >= 1
        assert results[0]["topic"] == "FastAPI middleware"

    def test_merge_facts(self):
        from backend.memory import SemanticMemory
        sm = SemanticMemory()
        sm.store(
            topic="Docker",
            facts=["Containers are lightweight"],
            source_conversation_id="conv-1",
            source_query="What is Docker?",
            confidence=0.7,
        )
        sm.store(
            topic="Docker",
            facts=["Images are built from Dockerfiles", "Containers are lightweight"],
            source_conversation_id="conv-2",
            source_query="How to build Docker images?",
            confidence=0.9,
        )
        entries = sm.list_all()
        # Should be merged into one entry
        docker_entries = [e for e in entries if "Docker" in e.get("topic", "")]
        assert len(docker_entries) == 1
        assert len(docker_entries[0]["facts"]) == 2  # Deduplicated
        assert docker_entries[0]["confidence"] == 0.9  # Max

    def test_unlearn_and_relearn(self):
        from backend.memory import SemanticMemory
        sm = SemanticMemory()
        sm.store(
            topic="Outdated info",
            facts=["This is wrong"],
            source_conversation_id="conv-1",
            source_query="test",
            confidence=0.6,
        )
        # Unlearn
        assert sm.unlearn("Outdated info", reason="Incorrect") is True
        # Recall should not return unlearned entries
        results = sm.recall("Outdated info")
        assert len(results) == 0
        # List with include_unlearned
        all_entries = sm.list_all(include_unlearned=True)
        assert any(e.get("status") == "unlearned" for e in all_entries)
        # Relearn
        assert sm.relearn("Outdated info") is True
        results = sm.recall("Outdated info")
        assert len(results) >= 1
        assert results[0]["status"] == "active"

    def test_unlearn_nonexistent(self):
        from backend.memory import SemanticMemory
        sm = SemanticMemory()
        assert sm.unlearn("No such topic") is False


# ════════════════════════════════════════════════════════════════════
# 3. Episodic Memory Tests
# ════════════════════════════════════════════════════════════════════

class TestEpisodicMemory:

    def _make_episode(self, em, conv_id="conv-1", grounding=0.82, verdict="pending"):
        return em.store(
            conversation_id=conv_id,
            query="How to optimize database queries?",
            stage1_summary=[
                {"model": "gpt-5-mini", "response": "Use indexes"},
                {"model": "claude-opus-4.5", "response": "Analyze query plans"},
            ],
            aggregate_rankings=[
                {"model": "claude-opus-4.5", "average_rank": 1.2},
                {"model": "gpt-5-mini", "average_rank": 1.8},
            ],
            chairman_model="claude-opus-4.5",
            chairman_response_preview="To optimize database queries, start by...",
            grounding_score=grounding,
            cost_summary={"total_cost": 0.05},
            user_verdict=verdict,
        )

    def test_store_and_recall(self):
        from backend.memory import EpisodicMemory
        em = EpisodicMemory()
        entry = self._make_episode(em)
        assert entry["status"] == "active"
        assert entry["grounding_score"] == 0.82

        results = em.recall("database query optimization")
        assert len(results) >= 1

    def test_recall_by_conversation(self):
        from backend.memory import EpisodicMemory
        em = EpisodicMemory()
        self._make_episode(em, conv_id="conv-abc")
        self._make_episode(em, conv_id="conv-xyz")
        results = em.recall_by_conversation("conv-abc")
        assert len(results) >= 1
        assert all(r["conversation_id"] == "conv-abc" for r in results)

    def test_update_verdict(self):
        from backend.memory import EpisodicMemory
        em = EpisodicMemory()
        entry = self._make_episode(em, verdict="pending")
        entry_id = entry["id"]
        assert em.update_verdict(entry_id, "learn") is True
        # Check verdict was applied
        from backend.memory_store import get_memory_backend
        doc = get_memory_backend().get("episodic", entry_id)
        assert doc["user_verdict"] == "learn"
        assert doc["status"] == "active"

    def test_update_verdict_unlearn(self):
        from backend.memory import EpisodicMemory
        em = EpisodicMemory()
        entry = self._make_episode(em)
        assert em.update_verdict(entry["id"], "unlearn", reason="Bad answer") is True
        from backend.memory_store import get_memory_backend
        doc = get_memory_backend().get("episodic", entry["id"])
        assert doc["status"] == "unlearned"


# ════════════════════════════════════════════════════════════════════
# 4. Procedural Memory Tests
# ════════════════════════════════════════════════════════════════════

class TestProceduralMemory:

    def test_store_and_recall(self):
        from backend.memory import ProceduralMemory
        pm = ProceduralMemory()
        entry = pm.store(
            task_type="Deploy to Kubernetes",
            procedure="Build image, push to registry, apply manifests",
            steps=["Build Docker image", "Push to container registry", "Apply K8s manifests"],
            source_conversations=["conv-1"],
            confidence=0.88,
        )
        assert entry["reinforcement_count"] == 1
        results = pm.recall("deploy kubernetes")
        assert len(results) >= 1

    def test_reinforcement(self):
        from backend.memory import ProceduralMemory
        pm = ProceduralMemory()
        pm.store(
            task_type="CI/CD pipeline setup",
            procedure="Configure triggers, add build steps, deploy",
            steps=["Setup triggers", "Build", "Test", "Deploy"],
            source_conversations=["conv-1"],
            confidence=0.75,
        )
        entry2 = pm.store(
            task_type="CI/CD pipeline setup",
            procedure="Configure triggers, add build and test steps, deploy with rollback",
            steps=["Setup triggers", "Build", "Test", "Deploy", "Verify"],
            source_conversations=["conv-2"],
            confidence=0.9,
        )
        assert entry2["reinforcement_count"] == 2
        assert entry2["confidence"] == 0.9

    def test_unlearn_and_relearn(self):
        from backend.memory import ProceduralMemory
        pm = ProceduralMemory()
        pm.store(
            task_type="Old workflow",
            procedure="Deprecated",
            steps=["Step 1"],
            source_conversations=["conv-1"],
            confidence=0.5,
        )
        assert pm.unlearn("Old workflow", reason="Deprecated") is True
        assert len(pm.recall("Old workflow")) == 0
        assert pm.relearn("Old workflow") is True
        assert len(pm.recall("Old workflow")) >= 1


# ════════════════════════════════════════════════════════════════════
# 5. MemoryManager Facade Tests
# ════════════════════════════════════════════════════════════════════

class TestMemoryManager:

    def test_recall_for_query(self):
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        # Store some data first
        mm.semantic.store(
            topic="Python async",
            facts=["asyncio event loop", "await suspends execution"],
            source_conversation_id="conv-1",
            source_query="How does Python async work?",
            confidence=0.85,
        )
        mm.procedural.store(
            task_type="Setup async server",
            procedure="Use uvicorn with async FastAPI",
            steps=["Install uvicorn", "Create async routes", "Run server"],
            source_conversations=["conv-1"],
            confidence=0.8,
        )
        memories = mm.recall_for_query("how to use Python asyncio")
        assert memories["total"] >= 1

    def test_format_memory_context(self):
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        mm.semantic.store(
            topic="Testing best practices",
            facts=["Write unit tests", "Use fixtures", "Mock external deps"],
            source_conversation_id="conv-1",
            source_query="testing",
            confidence=0.9,
        )
        memories = mm.recall_for_query("testing")
        context = mm.format_memory_context(memories)
        assert "PRIOR DOMAIN KNOWLEDGE" in context
        assert "Testing best practices" in context

    def test_format_empty_context(self):
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        memories = mm.recall_for_query("xyzzy totally unrelated")
        context = mm.format_memory_context(memories)
        assert context == ""

    def test_learn_from_council(self):
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        learned = mm.learn_from_council(
            conversation_id="conv-100",
            query="How to set up a CI/CD pipeline with GitHub Actions?",
            stage1_results=[
                {"model": "gpt-5-mini", "response": "Use GitHub Actions YAML files"},
                {"model": "claude-opus-4.5", "response": "Create workflow files in .github/"},
            ],
            aggregate_rankings=[
                {"model": "claude-opus-4.5", "average_rank": 1.2},
                {"model": "gpt-5-mini", "average_rank": 1.8},
            ],
            stage3_result={
                "model": "claude-opus-4.5",
                "response": "To set up CI/CD: 1. Create .github/workflows dir. 2. Add workflow YAML. 3. Configure triggers. 4. Add build steps. 5. Deploy.",
            },
            grounding_score=0.88,
            cost_summary={"total_cost": 0.04},
        )
        # Should learn all three tiers (high grounding + procedural query)
        assert learned["episodic"] is not None
        assert learned["semantic"] is not None
        assert learned["procedural"] is not None

    def test_learn_low_grounding_only_episodic(self):
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        learned = mm.learn_from_council(
            conversation_id="conv-101",
            query="What is the meaning of life?",
            stage1_results=[{"model": "gpt-5-mini", "response": "42"}],
            aggregate_rankings=[{"model": "gpt-5-mini", "average_rank": 1.0}],
            stage3_result={"model": "gpt-5-mini", "response": "The answer is 42."},
            grounding_score=0.3,
        )
        # Low grounding: only episodic stored
        assert learned["episodic"] is not None
        assert learned["semantic"] is None
        assert learned["procedural"] is None

    def test_user_learn_and_unlearn(self):
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        entry = mm.semantic.store(
            topic="Test topic",
            facts=["fact1"],
            source_conversation_id="c1",
            source_query="test",
            confidence=0.7,
        )
        entry_id = entry["id"]
        # Unlearn
        assert mm.user_unlearn("semantic", entry_id, reason="wrong") is True
        from backend.memory_store import get_memory_backend
        doc = get_memory_backend().get("semantic", entry_id)
        assert doc["status"] == "unlearned"
        # Learn back
        assert mm.user_learn("semantic", entry_id) is True
        doc = get_memory_backend().get("semantic", entry_id)
        assert doc["status"] == "active"

    def test_stats(self):
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        mm.semantic.store(
            topic="A", facts=["f1"], source_conversation_id="c1",
            source_query="q", confidence=0.8,
        )
        mm.semantic.store(
            topic="B", facts=["f2"], source_conversation_id="c2",
            source_query="q", confidence=0.6,
        )
        mm.semantic.unlearn("B")
        stats = mm.stats()
        assert stats["semantic"]["total"] == 2
        assert stats["semantic"]["active"] == 1
        assert stats["semantic"]["unlearned"] == 1

    def test_is_procedural_query(self):
        from backend.memory import MemoryManager
        assert MemoryManager._is_procedural_query("How to deploy to K8s?") is True
        assert MemoryManager._is_procedural_query("What is Python?") is False
        assert MemoryManager._is_procedural_query("Steps to configure NGINX") is True
        assert MemoryManager._is_procedural_query("best practice for testing") is True


# ════════════════════════════════════════════════════════════════════
# 6. Orchestrator Agent Tests
# ════════════════════════════════════════════════════════════════════

class TestOrchestratorAgents:

    @pytest.fixture(autouse=True)
    def _seed_memory(self):
        """Seed some memory entries for orchestrator tests."""
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        mm.semantic.store(
            topic="React hooks",
            facts=["useState for state", "useEffect for side effects", "Custom hooks for reuse"],
            source_conversation_id="seed-1",
            source_query="React hooks",
            confidence=0.9,
        )
        mm.episodic.store(
            conversation_id="seed-1",
            query="How to use React hooks?",
            stage1_summary=[{"model": "gpt-5-mini", "response": "..."}],
            aggregate_rankings=[{"model": "gpt-5-mini", "average_rank": 1.0}],
            chairman_model="claude-opus-4.5",
            chairman_response_preview="React hooks allow functional components...",
            grounding_score=0.85,
        )
        mm.procedural.store(
            task_type="Create React component",
            procedure="Define function, add hooks, return JSX",
            steps=["Create file", "Import React", "Add state hooks", "Return JSX"],
            source_conversations=["seed-1"],
            confidence=0.82,
        )

    @pytest.mark.asyncio
    async def test_pre_stage1_with_memories(self):
        from backend.orchestrator import pre_stage1_agent
        result = await pre_stage1_agent("How to use React hooks effectively?", "conv-test")
        assert result["gate"] == "pre_stage1"
        assert result["memories_found"] > 0
        assert result["influence_score"] > 0
        assert "Current question:" in result["augmented_query"]

    @pytest.mark.asyncio
    async def test_pre_stage1_no_memories(self):
        from backend.orchestrator import pre_stage1_agent
        result = await pre_stage1_agent("Quantum physics simulation xyzzy", "conv-test")
        assert result["gate"] == "pre_stage1"
        # May or may not find results, but should not crash
        assert "augmented_query" in result

    @pytest.mark.asyncio
    async def test_post_stage2_high_confidence(self):
        from backend.orchestrator import post_stage2_agent
        result = await post_stage2_agent(
            user_query="React hooks best practices",
            grounding_scores={"overall_score": 0.92},
            aggregate_rankings=[{"model": "claude-opus-4.5", "average_rank": 1.0}],
        )
        assert result["gate"] == "post_stage2"
        assert result["recommendation"] == "high_confidence"
        assert result["current_grounding"] == 0.92

    @pytest.mark.asyncio
    async def test_post_stage2_low_confidence(self):
        from backend.orchestrator import post_stage2_agent
        result = await post_stage2_agent(
            user_query="Something obscure",
            grounding_scores={"overall_score": 0.35},
            aggregate_rankings=[],
        )
        assert result["recommendation"] == "low_confidence"

    @pytest.mark.asyncio
    async def test_post_stage3_auto_learn(self):
        from backend.orchestrator import post_stage3_agent
        result = await post_stage3_agent(
            conversation_id="conv-auto",
            user_query="How to optimize React rendering?",
            stage1_results=[{"model": "gpt-5-mini", "response": "Use memo"}],
            aggregate_rankings=[{"model": "gpt-5-mini", "average_rank": 1.0}],
            stage3_result={"model": "claude-opus-4.5", "response": "1. Use React.memo. 2. Avoid re-renders."},
            grounding_score=0.88,
            auto_learn_threshold=0.75,
        )
        assert result["gate"] == "post_stage3"
        assert result["action"] == "auto_learned"
        assert result["learned"]["episodic"] is not None

    @pytest.mark.asyncio
    async def test_post_stage3_pending(self):
        from backend.orchestrator import post_stage3_agent
        result = await post_stage3_agent(
            conversation_id="conv-pending",
            user_query="What is the best cloud?",
            stage1_results=[{"model": "gpt-5-mini", "response": "AWS"}],
            aggregate_rankings=[{"model": "gpt-5-mini", "average_rank": 1.0}],
            stage3_result={"model": "gpt-5-mini", "response": "AWS is widely used."},
            grounding_score=0.55,
            auto_learn_threshold=0.75,
        )
        assert result["action"] == "pending_user_decision"

    @pytest.mark.asyncio
    async def test_user_gate_learn(self):
        from backend.orchestrator import user_gate_agent
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        entry = mm.semantic.store(
            topic="Gate test",
            facts=["fact"],
            source_conversation_id="c1",
            source_query="test",
            confidence=0.7,
        )
        # Unlearn first, then re-learn via user gate
        mm.user_unlearn("semantic", entry["id"])
        result = await user_gate_agent("learn", "semantic", entry["id"])
        assert result["success"] is True
        from backend.memory_store import get_memory_backend
        doc = get_memory_backend().get("semantic", entry["id"])
        assert doc["status"] == "active"

    @pytest.mark.asyncio
    async def test_user_gate_unlearn(self):
        from backend.orchestrator import user_gate_agent
        from backend.memory import get_memory_manager
        mm = get_memory_manager()
        entry = mm.semantic.store(
            topic="To unlearn",
            facts=["fact"],
            source_conversation_id="c1",
            source_query="test",
            confidence=0.7,
        )
        result = await user_gate_agent("unlearn", "semantic", entry["id"], reason="Wrong info")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_user_gate_invalid_decision(self):
        from backend.orchestrator import user_gate_agent
        result = await user_gate_agent("invalid_action", "semantic", "some-id")
        assert result["success"] is False
        assert "Unknown decision" in result.get("error", "")


# ════════════════════════════════════════════════════════════════════
# 7. End-to-End Pipeline Simulation
# ════════════════════════════════════════════════════════════════════

class TestEndToEndPipeline:
    """
    Simulates the full council pipeline with memory:
      Pre-Stage1 → Stage1 (mocked) → Stage2 (mocked) → Post-Stage2 →
      Stage3 (mocked) → Post-Stage3 → User Gate
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_auto_learn(self):
        """High grounding → auto-learn → memories persist."""
        from backend.orchestrator import (
            pre_stage1_agent, post_stage2_agent,
            post_stage3_agent, user_gate_agent,
        )
        from backend.memory import get_memory_manager

        conv_id = "sim-conv-001"
        user_query = "How to implement authentication in FastAPI?"

        # ── Pre-Stage 1: Memory Recall ──
        pre = await pre_stage1_agent(user_query, conv_id)
        assert "augmented_query" in pre
        augmented_query = pre["augmented_query"]

        # ── Stage 1 (mocked) ──
        stage1_results = [
            {"model": "gpt-5-mini", "response": "Use OAuth2 with JWT tokens in FastAPI."},
            {"model": "claude-opus-4.5", "response": "FastAPI has built-in security utilities."},
            {"model": "gemini-2.5-pro", "response": "Implement OAuth2PasswordBearer dependency."},
        ]

        # ── Stage 2 (mocked) ──
        aggregate_rankings = [
            {"model": "claude-opus-4.5", "average_rank": 1.3},
            {"model": "gemini-2.5-pro", "average_rank": 1.7},
            {"model": "gpt-5-mini", "average_rank": 2.0},
        ]
        grounding_scores = {"overall_score": 0.87}

        # ── Post-Stage 2: Evaluate ──
        post2 = await post_stage2_agent(user_query, grounding_scores, aggregate_rankings)
        assert post2["recommendation"] == "high_confidence"

        # ── Stage 3 (mocked) ──
        stage3_result = {
            "model": "claude-opus-4.5",
            "response": (
                "To implement authentication in FastAPI:\n"
                "1. Install python-jose and passlib.\n"
                "2. Create OAuth2PasswordBearer scheme.\n"
                "3. Define JWT token creation function.\n"
                "4. Add dependency injection for current user.\n"
                "5. Protect routes with Depends(get_current_user)."
            ),
        }

        # ── Post-Stage 3: Learning Decision ──
        post3 = await post_stage3_agent(
            conversation_id=conv_id,
            user_query=user_query,
            stage1_results=stage1_results,
            aggregate_rankings=aggregate_rankings,
            stage3_result=stage3_result,
            grounding_score=0.87,
            cost_summary={"total_cost": 0.05},
        )
        assert post3["action"] == "auto_learned"
        assert post3["learned"]["episodic"] is not None

        # ── Verify memory was stored ──
        mm = get_memory_manager()
        stats = mm.stats()
        assert stats["episodic"]["active"] >= 1
        assert stats["semantic"]["active"] >= 1

    @pytest.mark.asyncio
    async def test_full_pipeline_user_decision(self):
        """Low grounding → pending → user decides to unlearn."""
        from backend.orchestrator import (
            pre_stage1_agent, post_stage2_agent,
            post_stage3_agent, user_gate_agent,
        )
        from backend.memory import get_memory_manager

        conv_id = "sim-conv-002"
        user_query = "What is the best programming language?"

        # ── Pre-Stage 1 ──
        pre = await pre_stage1_agent(user_query, conv_id)

        # ── Stages 1-3 (mocked) ──
        stage1_results = [{"model": "gpt-5-mini", "response": "Depends on the use case."}]
        aggregate_rankings = [{"model": "gpt-5-mini", "average_rank": 1.0}]
        stage3_result = {"model": "gpt-5-mini", "response": "There is no single best language."}

        # ── Post-Stage 2: Low confidence ──
        post2 = await post_stage2_agent(
            user_query, {"overall_score": 0.45}, aggregate_rankings
        )
        assert post2["recommendation"] == "low_confidence"

        # ── Post-Stage 3: Pending ──
        post3 = await post_stage3_agent(
            conversation_id=conv_id,
            user_query=user_query,
            stage1_results=stage1_results,
            aggregate_rankings=aggregate_rankings,
            stage3_result=stage3_result,
            grounding_score=0.45,
        )
        assert post3["action"] == "pending_user_decision"
        episode_id = post3["learned"]["episodic"]
        assert episode_id is not None

        # ── User Gate: Unlearn ──
        gate = await user_gate_agent("unlearn", "episodic", episode_id, reason="Subjective")
        assert gate["success"] is True

        # Verify unlearned
        from backend.memory_store import get_memory_backend
        doc = get_memory_backend().get("episodic", episode_id)
        assert doc["status"] == "unlearned"

    @pytest.mark.asyncio
    async def test_memory_recall_influences_next_query(self):
        """
        First query learns → second query on similar topic recalls it.
        """
        from backend.orchestrator import pre_stage1_agent, post_stage3_agent
        from backend.memory import get_memory_manager

        # First conversation: learn about testing
        await post_stage3_agent(
            conversation_id="learn-conv",
            user_query="How to write unit tests in Python?",
            stage1_results=[{"model": "gpt-5-mini", "response": "Use pytest"}],
            aggregate_rankings=[{"model": "gpt-5-mini", "average_rank": 1.0}],
            stage3_result={
                "model": "gpt-5-mini",
                "response": "1. Install pytest. 2. Write test functions. 3. Use assertions. 4. Run pytest.",
            },
            grounding_score=0.9,
        )

        # Second conversation: related query should recall memory
        pre = await pre_stage1_agent("Best practices for Python testing", "new-conv")
        assert pre["memories_found"] >= 1
        assert pre["influence_score"] > 0

    @pytest.mark.asyncio
    async def test_confidence_feedback_loop(self):
        """
        Sequential episodes with varying grounding scores should produce
        an anomaly detection when score diverges from historical mean.
        """
        from backend.orchestrator import post_stage2_agent
        from backend.memory import get_memory_manager

        mm = get_memory_manager()
        query = "How to handle errors in Python?"

        # Store 5 episodes with consistent grounding ~0.8
        for i in range(5):
            mm.episodic.store(
                conversation_id=f"hist-{i}",
                query=query,
                stage1_summary=[{"model": "gpt-5-mini", "response": "try/except"}],
                aggregate_rankings=[{"model": "gpt-5-mini", "average_rank": 1.0}],
                chairman_model="claude-opus-4.5",
                chairman_response_preview="Use try-except blocks...",
                grounding_score=0.78 + (i * 0.01),  # 0.78 to 0.82
            )

        # Now a query with significantly lower grounding
        result = await post_stage2_agent(
            query, {"overall_score": 0.50}, []
        )
        # With historical mean ~0.80 and current 0.50, delta ~= -0.30
        assert result["anomaly"] == "below_average"
        assert result["delta"] < -0.15

    @pytest.mark.asyncio
    async def test_multi_tier_learning_flow(self):
        """A procedural query with high grounding should learn into all 3 tiers."""
        from backend.orchestrator import post_stage3_agent
        from backend.memory import get_memory_manager

        result = await post_stage3_agent(
            conversation_id="multi-tier",
            user_query="How to deploy a FastAPI app to production?",
            stage1_results=[
                {"model": "gpt-5-mini", "response": "Use Docker and Gunicorn."},
                {"model": "claude-opus-4.5", "response": "Containerize with Docker, deploy to K8s."},
            ],
            aggregate_rankings=[
                {"model": "claude-opus-4.5", "average_rank": 1.1},
                {"model": "gpt-5-mini", "average_rank": 1.9},
            ],
            stage3_result={
                "model": "claude-opus-4.5",
                "response": (
                    "To deploy a FastAPI app:\n"
                    "1. Create a Dockerfile with uvicorn.\n"
                    "2. Build the container image.\n"
                    "3. Push to a container registry.\n"
                    "4. Deploy to Kubernetes or a cloud service.\n"
                    "5. Configure health checks and auto-scaling."
                ),
            },
            grounding_score=0.92,
        )

        assert result["action"] == "auto_learned"
        # Should have episodic (always), semantic (grounding>=0.5), procedural (how-to + grounding>=0.6)
        assert result["learned"]["episodic"] is not None
        assert result["learned"]["semantic"] is not None
        assert result["learned"]["procedural"] is not None

        # Verify stats
        mm = get_memory_manager()
        stats = mm.stats()
        assert stats["episodic"]["active"] >= 1
        assert stats["semantic"]["active"] >= 1
        assert stats["procedural"]["active"] >= 1


# ════════════════════════════════════════════════════════════════════
# 8. Cloud-Agnostic Backend Swap Test
# ════════════════════════════════════════════════════════════════════

class TestBackendSwap:
    """Verify that swapping the backend at runtime correctly routes operations."""

    def test_swap_backend(self, tmp_path):
        from backend.memory_store import (
            LocalJSONBackend, get_memory_backend, set_memory_backend,
        )
        # Create a second temp backend
        alt_dir = str(tmp_path / "alt_memory")
        alt_backend = LocalJSONBackend(base_dir=alt_dir)

        # Write to alt backend
        alt_backend.put("semantic", "swap-test", {"id": "swap-test", "data": "alt"})

        # Current backend should NOT have it
        assert get_memory_backend().get("semantic", "swap-test") is None

        # Swap
        set_memory_backend(alt_backend)
        assert get_memory_backend().get("semantic", "swap-test")["data"] == "alt"
