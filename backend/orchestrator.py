"""
Stage-Gate Orchestrator Agents for the LLM Council Memory Pipeline.

Deploys lightweight orchestrator "agents" at each stage gate that:
  1. Pre-gate: Recall relevant memories and inject as context
  2. Post-gate: Evaluate the stage output against memory
  3. Decision gate: Determine whether to learn/unlearn and update confidence

The orchestrator is stateless per-request and can be horizontally scaled
across any cloud provider.  Each agent function is a pure async coroutine
that can run in serverless (Lambda/Cloud Functions) or container contexts.

Stage Gates
───────────
  PRE_STAGE1   → Recall semantic + procedural memories for the user query
  POST_STAGE2  → Evaluate grounding score against episodic history
  POST_STAGE3  → Decide: auto-learn, prompt user, or auto-unlearn
  USER_GATE    → Apply user's learn/unlearn decision

Confidence Feedback Loop
────────────────────────
  grounding_score vs historical mean → boost / decay memory weights
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .memory import get_memory_manager, MemoryManager
from .memory_store import set_memory_user

logger = logging.getLogger("llm_council.orchestrator")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Pre-Stage 1 Agent: Memory Recall & Context Injection               ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def pre_stage1_agent(
    user_query: str,
    conversation_id: str,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    Runs before Stage 1 begins.
    - Recalls relevant memories across all tiers.
    - Formats them as prompt context.
    - Returns augmented query + memory metadata.
    """
    if user_id:
        set_memory_user(user_id)
    mm = get_memory_manager()
    memories = mm.recall_for_query(user_query)

    context_block = mm.format_memory_context(memories)

    # Compute a memory-influence score (how much prior knowledge we have)
    influence_score = _compute_memory_influence(memories)

    result = {
        "gate": "pre_stage1",
        "memories_found": memories["total"],
        "memory_context": context_block,
        "influence_score": round(influence_score, 4),
        "semantic_count": len(memories.get("semantic", [])),
        "episodic_count": len(memories.get("episodic", [])),
        "procedural_count": len(memories.get("procedural", [])),
    }

    if context_block:
        result["augmented_query"] = f"{context_block}Current question: {user_query}"
        logger.info(
            f"[PreStage1Agent] Injected {memories['total']} memories "
            f"(influence={influence_score:.2f})"
        )
    else:
        result["augmented_query"] = user_query
        logger.info("[PreStage1Agent] No relevant memories found")

    return result


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Post-Stage 2 Agent: Grounding Evaluation Against History           ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def post_stage2_agent(
    user_query: str,
    grounding_scores: Dict[str, Any],
    aggregate_rankings: List[Dict[str, Any]],
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    Runs after Stage 2 completes.
    - Compares current grounding score against historical episodic mean.
    - Flags if current deliberation is significantly above/below average.
    - Recommends confidence adjustment.
    """
    if user_id:
        set_memory_user(user_id)
    mm = get_memory_manager()
    current_score = grounding_scores.get("overall_score", 0)

    # Retrieve past episodes to compute historical baseline
    past_episodes = mm.episodic.recall(user_query, limit=10)
    historical_scores = [
        ep.get("grounding_score", 0) for ep in past_episodes
        if ep.get("grounding_score") is not None
    ]

    if historical_scores:
        hist_mean = sum(historical_scores) / len(historical_scores)
        hist_count = len(historical_scores)
        delta = current_score - hist_mean
    else:
        hist_mean = 0.0
        hist_count = 0
        delta = 0.0

    # Determine recommendation
    if current_score >= 0.8:
        recommendation = "high_confidence"
        message = "Council shows high agreement. Recommended for auto-learn."
    elif current_score >= 0.6:
        recommendation = "moderate_confidence"
        message = "Moderate confidence. Consider reviewing before learning."
    else:
        recommendation = "low_confidence"
        message = "Low confidence. Recommend user review before deciding."

    # Flag anomalies relative to history
    anomaly = None
    if hist_count >= 3:
        if delta > 0.15:
            anomaly = "above_average"
        elif delta < -0.15:
            anomaly = "below_average"

    result = {
        "gate": "post_stage2",
        "current_grounding": round(current_score, 4),
        "historical_mean": round(hist_mean, 4),
        "historical_count": hist_count,
        "delta": round(delta, 4),
        "recommendation": recommendation,
        "message": message,
        "anomaly": anomaly,
    }

    logger.info(
        f"[PostStage2Agent] Grounding={current_score:.2%} "
        f"(hist={hist_mean:.2%}, Δ={delta:+.2%}, rec={recommendation})"
    )
    return result


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Post-Stage 3 Agent: Learning Decision & Auto-Learn                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def post_stage3_agent(
    conversation_id: str,
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    aggregate_rankings: List[Dict[str, Any]],
    stage3_result: Dict[str, Any],
    grounding_score: float,
    cost_summary: Optional[Dict[str, Any]] = None,
    auto_learn_threshold: float = 0.75,
    tags: Optional[List[str]] = None,
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    Runs after Stage 3 (chairman synthesis) completes.
    - If grounding >= threshold → auto-learn into memory.
    - Otherwise → mark as pending for user decision.
    - Returns learning summary + prompt for user action.
    """
    if user_id:
        set_memory_user(user_id)
    try:
        mm = get_memory_manager()
    except Exception as e:
        logger.error(f"[PostStage3Agent] Failed to get memory manager: {e}")
        # Return a fallback result so the SSE event still fires
        return {
            "gate": "post_stage3",
            "action": "error",
            "grounding_score": round(grounding_score, 4),
            "auto_learn_threshold": auto_learn_threshold,
            "message": f"Memory system unavailable: {e}",
            "learned": {"semantic": None, "episodic": None, "procedural": None},
        }

    should_auto_learn = grounding_score >= auto_learn_threshold

    try:
        if should_auto_learn:
            learned = mm.learn_from_council(
                conversation_id=conversation_id,
                query=user_query,
                stage1_results=stage1_results,
                aggregate_rankings=aggregate_rankings,
                stage3_result=stage3_result,
                grounding_score=grounding_score,
                cost_summary=cost_summary,
                tags=tags,
            )
            action = "auto_learned"
            message = (
                f"Grounding score ({grounding_score:.0%}) exceeds threshold "
                f"({auto_learn_threshold:.0%}). Decision auto-learned into memory."
            )
            logger.info(f"[PostStage3Agent] Auto-learned (grounding={grounding_score:.2%})")
        else:
            # Still store episodic record with 'pending' verdict
            learned = {
                "episodic": mm.episodic.store(
                    conversation_id=conversation_id,
                    query=user_query,
                    stage1_summary=stage1_results,
                    aggregate_rankings=aggregate_rankings,
                    chairman_model=stage3_result.get("model", "unknown"),
                    chairman_response_preview=stage3_result.get("response", "")[:500],
                    grounding_score=grounding_score,
                    cost_summary=cost_summary,
                    user_verdict="pending",
                    tags=tags,
                ),
                "semantic": None,
                "procedural": None,
            }
            action = "pending_user_decision"
            message = (
                f"Grounding score ({grounding_score:.0%}) below auto-learn threshold "
                f"({auto_learn_threshold:.0%}). Please decide: Learn or Unlearn."
            )
            logger.info(f"[PostStage3Agent] Pending user decision (grounding={grounding_score:.2%})")
    except Exception as e:
        logger.error(f"[PostStage3Agent] Memory storage failed: {e}", exc_info=True)
        # Return a partial result so the SSE event still fires
        return {
            "gate": "post_stage3",
            "action": "pending_user_decision",
            "grounding_score": round(grounding_score, 4),
            "auto_learn_threshold": auto_learn_threshold,
            "message": (
                f"Grounding score ({grounding_score:.0%}). "
                f"Memory storage encountered an error — please retry Learn action manually."
            ),
            "learned": {"semantic": None, "episodic": None, "procedural": None},
        }

    result = {
        "gate": "post_stage3",
        "action": action,
        "grounding_score": round(grounding_score, 4),
        "auto_learn_threshold": auto_learn_threshold,
        "message": message,
        "learned": {
            "semantic": learned.get("semantic", {}).get("id") if learned.get("semantic") else None,
            "episodic": learned.get("episodic", {}).get("id") if learned.get("episodic") else None,
            "procedural": learned.get("procedural", {}).get("id") if learned.get("procedural") else None,
        },
    }

    return result


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  User Gate Agent: Apply Learn / Unlearn Decision                    ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def user_gate_agent(
    decision: str,  # "learn" | "unlearn"
    memory_type: str,  # "semantic" | "episodic" | "procedural"
    memory_id: str,
    reason: str = "",
    user_id: str | None = None,
) -> Dict[str, Any]:
    """
    Applies the user's explicit learn/unlearn decision.
    Can be called at any stage from the frontend.
    """
    if user_id:
        set_memory_user(user_id)
    mm = get_memory_manager()

    if decision == "learn":
        success = mm.user_learn(memory_type, memory_id)
    elif decision == "unlearn":
        success = mm.user_unlearn(memory_type, memory_id, reason)
    else:
        return {
            "gate": "user_gate",
            "success": False,
            "error": f"Unknown decision: {decision}. Use 'learn' or 'unlearn'.",
        }

    logger.info(f"[UserGateAgent] {decision} {memory_type}/{memory_id} → {'ok' if success else 'not found'}")

    return {
        "gate": "user_gate",
        "decision": decision,
        "memory_type": memory_type,
        "memory_id": memory_id,
        "success": success,
    }


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Helpers                                                            ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _compute_memory_influence(memories: Dict[str, Any]) -> float:
    """
    Compute a 0–1 score indicating how much prior memory will influence
    this council session.  Based on count × average confidence.
    """
    total_conf = 0.0
    count = 0

    for tier in ("semantic", "episodic", "procedural"):
        for m in memories.get(tier, []):
            c = m.get("confidence") or m.get("grounding_score") or 0
            total_conf += c
            count += 1

    if count == 0:
        return 0.0

    avg_conf = total_conf / count
    # Scale: 5+ memories at avg confidence 0.8 → influence ~1.0
    return min(1.0, (count / 5.0) * avg_conf)
