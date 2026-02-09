"""
Grounding Score computation for Stage 2 peer rankings.

Computes a confidence score (0–100%) for each response and an overall
council grounding score, based on a multi-criteria rubric:

  1. Relevancy       — How directly the response addresses the question
  2. Faithfulness    — Factual accuracy and absence of hallucinations
  3. Context Recall  — Coverage of key concepts from other responses
  4. Output Quality  — Clarity, structure, depth, and coherence
  5. Consensus       — Agreement level across peer reviewers

These scores are derived from the Stage 2 ranking data (parsed rankings +
aggregate positions) rather than requiring an additional LLM call.
"""

from typing import List, Dict, Any, Optional
import re
import math


# ── Rubric Criteria Definitions ──────────────────────────────────────────

RUBRIC_CRITERIA = [
    {
        "id": "relevancy",
        "name": "Relevancy",
        "weight": 0.25,
        "description": "How directly and completely the response addresses the original question",
    },
    {
        "id": "faithfulness",
        "name": "Faithfulness",
        "weight": 0.25,
        "description": "Factual accuracy, absence of hallucinations, and groundedness in evidence",
    },
    {
        "id": "context_recall",
        "name": "Context Recall",
        "weight": 0.15,
        "description": "Coverage of key concepts, dimensions, and nuances raised across all responses",
    },
    {
        "id": "output_quality",
        "name": "Output Quality",
        "weight": 0.20,
        "description": "Clarity, structure, depth, readability, and overall coherence of the response",
    },
    {
        "id": "consensus",
        "name": "Consensus",
        "weight": 0.15,
        "description": "Degree of agreement across peer reviewers on the response's ranking position",
    },
]


def get_rubric_criteria() -> List[Dict[str, Any]]:
    """Return the rubric criteria definitions for API/documentation use."""
    return RUBRIC_CRITERIA


# ── Per-Response Grounding Scores ────────────────────────────────────────

def _rank_position_score(avg_rank: float, total_models: int) -> float:
    """
    Convert an average rank (1 = best) to a 0–1 score.
    rank 1 → ~1.0, rank N → ~0.2 (never zero — each response has some value).
    """
    if total_models <= 1:
        return 1.0
    # Linear mapping: rank 1 → 1.0, rank N → 0.2
    score = 1.0 - 0.8 * (avg_rank - 1) / (total_models - 1)
    return max(0.0, min(1.0, score))


def _consensus_score(positions: List[int], total_models: int) -> float:
    """
    Measure how much the reviewers agree on a response's position.
    Low variance = high consensus.
    """
    if len(positions) <= 1:
        return 0.7  # neutral if only one reviewer
    mean = sum(positions) / len(positions)
    variance = sum((p - mean) ** 2 for p in positions) / len(positions)
    # Max possible variance for ranks 1..N
    max_variance = ((total_models - 1) ** 2) / 4.0
    if max_variance == 0:
        return 1.0
    # Low variance → high score
    return max(0.0, min(1.0, 1.0 - (variance / max_variance)))


def _estimate_criteria_scores(
    avg_rank: float,
    total_models: int,
    positions: List[int],
) -> Dict[str, float]:
    """
    Estimate per-criteria scores from ranking data.
    
    Since we derive scores from peer rankings (not a separate LLM evaluation),
    the rank position is the primary signal, modulated by consensus.
    Better-ranked responses score higher on all quality criteria.
    """
    base = _rank_position_score(avg_rank, total_models)
    cons = _consensus_score(positions, total_models)

    # Criteria are influenced primarily by rank position,
    # with small perturbations to reflect that different criteria
    # may vary slightly for a given ranked position.
    return {
        "relevancy": min(1.0, base * 1.05),       # Top responses tend to be most relevant
        "faithfulness": min(1.0, base * 0.98),     # Slightly conservative — harder to verify
        "context_recall": min(1.0, base * 0.95),   # Coverage correlates with but lags rank
        "output_quality": min(1.0, base * 1.02),   # Quality strongly correlates with rank
        "consensus": cons,                          # Independent dimension
    }


def compute_response_grounding_scores(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str],
    aggregate_rankings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compute per-response grounding scores and an overall council grounding score.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names
        aggregate_rankings: Pre-computed aggregate rankings

    Returns:
        {
            "overall_score": float (0–100),
            "per_response": [
                {
                    "model": str,
                    "grounding_score": float (0–100),
                    "criteria": { "relevancy": float, ... },
                    "rank": int
                }
            ],
            "criteria_definitions": [...],
            "council_size": int,
            "reviewers_count": int
        }
    """
    from collections import defaultdict

    total_models = len(aggregate_rankings)
    if total_models == 0:
        return {
            "overall_score": 0,
            "per_response": [],
            "criteria_definitions": RUBRIC_CRITERIA,
            "council_size": 0,
            "reviewers_count": len(stage2_results),
        }

    # Build position lists per model from parsed rankings
    model_positions: Dict[str, List[int]] = defaultdict(list)
    for ranking in stage2_results:
        parsed = ranking.get("parsed_ranking", [])
        for position, label in enumerate(parsed, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    per_response = []
    for rank_idx, agg in enumerate(aggregate_rankings):
        model = agg["model"]
        avg_rank = agg["average_rank"]
        positions = model_positions.get(model, [])

        criteria_scores = _estimate_criteria_scores(avg_rank, total_models, positions)

        # Weighted grounding score
        weighted_score = sum(
            criteria_scores[c["id"]] * c["weight"]
            for c in RUBRIC_CRITERIA
        )
        grounding_pct = round(weighted_score * 100, 1)

        per_response.append({
            "model": model,
            "grounding_score": grounding_pct,
            "criteria": {k: round(v * 100, 1) for k, v in criteria_scores.items()},
            "rank": rank_idx + 1,
        })

    # Overall council grounding score: weighted average biased toward top responses
    # Top-ranked response gets more weight in the overall score
    if per_response:
        weights = [1.0 / (i + 1) for i in range(len(per_response))]
        total_weight = sum(weights)
        overall = sum(
            r["grounding_score"] * w
            for r, w in zip(per_response, weights)
        ) / total_weight
    else:
        overall = 0

    return {
        "overall_score": round(overall, 1),
        "per_response": per_response,
        "criteria_definitions": RUBRIC_CRITERIA,
        "council_size": total_models,
        "reviewers_count": len(stage2_results),
    }
