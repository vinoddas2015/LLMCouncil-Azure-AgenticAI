"""
Grounding Score computation — Hybrid Verbalized Sampling + Synthetic Math.

Computes a confidence score (0–100%) for each response and an overall
council grounding score, based on a multi-criteria rubric using TWO
complementary signals:

  A) Verbalized Sampling — real per-criteria scores (0–10) parsed from
     each reviewer's structured output (rubric_scores).

  B) Synthetic Math — rank-position-derived estimates used as a fallback
     when verbalized data is missing or sparse.

The final per-criteria score is a weighted blend:
    score = α × verbalized  +  (1 − α) × synthetic
where α = proportion of reviewers who provided parseable rubric scores
(so full verbalized coverage → pure VS; zero → pure synthetic).

Additionally, pharma-specific safety metrics are computed from the
claim counts (TP, FP, FN) parsed from each reviewer's output:

  Correctness = TP / (TP + 2×FN + FP)
      — Doubles the FN penalty: missing critical data is costlier
        than including an incorrect claim in pharma contexts.

  Precision = TP / (TP + FP)
      — How many claims are actually correct?

  Recall = TP / (TP + FN)
      — How much of the important information was covered?

Rubric criteria:
  1. Relevancy       — Direct & complete answer to the question
  2. Faithfulness    — Factual accuracy, no hallucinations
  3. Context Recall  — Coverage of key concepts across responses
  4. Output Quality  — Clarity, structure, depth, coherence
  5. Consensus       — Agreement among peer reviewers
"""

from typing import List, Dict, Any, Optional
from collections import defaultdict
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


# ═══════════════════════════════════════════════════════════════════════
# Synthetic Math helpers (rank-derived, used as fallback)
# ═══════════════════════════════════════════════════════════════════════

def _rank_position_score(avg_rank: float, total_models: int) -> float:
    """rank 1 → ~1.0, rank N → ~0.2."""
    if total_models <= 1:
        return 1.0
    score = 1.0 - 0.8 * (avg_rank - 1) / (total_models - 1)
    return max(0.0, min(1.0, score))


def _consensus_score(positions: List[int], total_models: int) -> float:
    """Low variance in rank positions → high consensus."""
    if len(positions) <= 1:
        return 0.7
    mean = sum(positions) / len(positions)
    variance = sum((p - mean) ** 2 for p in positions) / len(positions)
    max_variance = ((total_models - 1) ** 2) / 4.0
    if max_variance == 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (variance / max_variance)))


def _synthetic_criteria(avg_rank: float, total_models: int, positions: List[int]) -> Dict[str, float]:
    """Estimate per-criteria scores from rank position only."""
    base = _rank_position_score(avg_rank, total_models)
    cons = _consensus_score(positions, total_models)
    return {
        "relevancy": min(1.0, base * 1.05),
        "faithfulness": min(1.0, base * 0.98),
        "context_recall": min(1.0, base * 0.95),
        "output_quality": min(1.0, base * 1.02),
        "consensus": cons,
    }


# ═══════════════════════════════════════════════════════════════════════
# Pharma Safety Metrics (TP / FP / FN based)
# ═══════════════════════════════════════════════════════════════════════

def _pharma_correctness(tp: int, fp: int, fn: int) -> float:
    """Correctness = TP / (TP + 2×FN + FP).  FN penalty doubled for pharma."""
    denom = tp + 2 * fn + fp
    return tp / denom if denom > 0 else 0.0


def _precision(tp: int, fp: int) -> float:
    """Precision = TP / (TP + FP)."""
    denom = tp + fp
    return tp / denom if denom > 0 else 0.0


def _recall(tp: int, fn: int) -> float:
    """Recall = TP / (TP + FN)."""
    denom = tp + fn
    return tp / denom if denom > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════
# Main scoring function
# ═══════════════════════════════════════════════════════════════════════

def compute_response_grounding_scores(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str],
    aggregate_rankings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compute per-response grounding scores using hybrid Verbalized Sampling
    + Synthetic Math, and pharma-specific Correctness / Precision / Recall.

    Returns:
        {
            "overall_score": float 0–100,
            "per_response": [
                {
                    "model": str,
                    "grounding_score": float 0–100,
                    "criteria": { "relevancy": float 0–100, ... },
                    "pharma_metrics": {
                        "correctness": float 0–100,
                        "precision": float 0–100,
                        "recall": float 0–100,
                        "tp": int, "fp": int, "fn": int
                    },
                    "verbalized_coverage": float 0–1,
                    "rank": int
                }
            ],
            "criteria_definitions": [...],
            "pharma_formulas": {
                "correctness": "TP / (TP + 2×FN + FP)",
                "precision": "TP / (TP + FP)",
                "recall": "TP / (TP + FN)"
            },
            "council_size": int,
            "reviewers_count": int
        }
    """
    total_models = len(aggregate_rankings)
    if total_models == 0:
        return {
            "overall_score": 0,
            "per_response": [],
            "criteria_definitions": RUBRIC_CRITERIA,
            "pharma_formulas": {
                "correctness": "TP / (TP + 2×FN + FP)",
                "precision": "TP / (TP + FP)",
                "recall": "TP / (TP + FN)",
            },
            "council_size": 0,
            "reviewers_count": len(stage2_results),
        }

    # ── Build position lists per model from parsed rankings ──────────
    model_positions: Dict[str, List[int]] = defaultdict(list)
    for ranking in stage2_results:
        parsed = ranking.get("parsed_ranking", [])
        for position, label in enumerate(parsed, start=1):
            if label in label_to_model:
                model_positions[label_to_model[label]].append(position)

    # ── Collect verbalized rubric scores per response label ──────────
    # Structure: { "Response A": [ {relevancy: 0.8, ...}, {relevancy: 0.7, ...} ] }
    verbalized_per_label: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    for ranking in stage2_results:
        rubric = ranking.get("rubric_scores", {})
        for label, scores in rubric.items():
            verbalized_per_label[label].append(scores)

    # ── Collect claim counts per response label ──────────────────────
    claims_per_label: Dict[str, List[Dict[str, int]]] = defaultdict(list)
    for ranking in stage2_results:
        claims = ranking.get("claim_counts", {})
        for label, counts in claims.items():
            claims_per_label[label].append(counts)

    # ── Reverse mapping: model → label ───────────────────────────────
    model_to_label = {v: k for k, v in label_to_model.items()}

    # ── Compute per-response scores ──────────────────────────────────
    per_response = []
    criteria_ids = [c["id"] for c in RUBRIC_CRITERIA]

    for rank_idx, agg in enumerate(aggregate_rankings):
        model = agg["model"]
        avg_rank = agg["average_rank"]
        positions = model_positions.get(model, [])
        label = model_to_label.get(model, "")

        # --- Synthetic Math baseline ---
        synthetic = _synthetic_criteria(avg_rank, total_models, positions)

        # --- Verbalized Sampling ---
        vs_list = verbalized_per_label.get(label, [])
        vs_count = len(vs_list)
        alpha = vs_count / max(len(stage2_results), 1)  # coverage fraction

        if vs_count > 0:
            vs_avg = {}
            for cid in criteria_ids:
                vals = [d[cid] for d in vs_list if cid in d]
                vs_avg[cid] = sum(vals) / len(vals) if vals else synthetic.get(cid, 0.5)
        else:
            vs_avg = synthetic

        # --- Blend: α × verbalized + (1−α) × synthetic ---
        blended = {}
        for cid in criteria_ids:
            blended[cid] = alpha * vs_avg.get(cid, 0.5) + (1 - alpha) * synthetic.get(cid, 0.5)

        # Weighted grounding score
        weighted = sum(blended[c["id"]] * c["weight"] for c in RUBRIC_CRITERIA)
        grounding_pct = round(weighted * 100, 1)

        # --- Pharma claim metrics ---
        claim_list = claims_per_label.get(label, [])
        if claim_list:
            total_tp = sum(c.get("tp", 0) for c in claim_list)
            total_fp = sum(c.get("fp", 0) for c in claim_list)
            total_fn = sum(c.get("fn", 0) for c in claim_list)
        else:
            # Fallback: estimate from rank position
            base = _rank_position_score(avg_rank, total_models)
            total_tp = max(1, round(base * 8))
            total_fp = max(0, round((1 - base) * 2))
            total_fn = max(0, round((1 - base) * 3))

        correctness = _pharma_correctness(total_tp, total_fp, total_fn)
        precision = _precision(total_tp, total_fp)
        recall = _recall(total_tp, total_fn)

        per_response.append({
            "model": model,
            "grounding_score": grounding_pct,
            "criteria": {k: round(v * 100, 1) for k, v in blended.items()},
            "pharma_metrics": {
                "correctness": round(correctness * 100, 1),
                "precision": round(precision * 100, 1),
                "recall": round(recall * 100, 1),
                "tp": total_tp,
                "fp": total_fp,
                "fn": total_fn,
            },
            "verbalized_coverage": round(alpha, 2),
            "rank": rank_idx + 1,
        })

    # ── Overall council grounding (top-weighted harmonic) ────────────
    if per_response:
        weights = [1.0 / (i + 1) for i in range(len(per_response))]
        total_weight = sum(weights)
        overall = sum(
            r["grounding_score"] * w for r, w in zip(per_response, weights)
        ) / total_weight
    else:
        overall = 0

    return {
        "overall_score": round(overall, 1),
        "per_response": per_response,
        "criteria_definitions": RUBRIC_CRITERIA,
        "pharma_formulas": {
            "correctness": "TP / (TP + 2×FN + FP)",
            "precision": "TP / (TP + FP)",
            "recall": "TP / (TP + FN)",
        },
        "council_size": total_models,
        "reviewers_count": len(stage2_results),
    }
