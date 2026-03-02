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
where α = proportion of *peer* reviewers who provided parseable rubric scores
(so full verbalized coverage → pure VS; zero → pure synthetic).

Bias-free design:
  • Self-reviews excluded — a model never evaluates its own response.
  • Peer-reviewer counts normalised — TP/FP/FN are averaged per reviewer
    so models with fewer parseable reviews aren't penalised.
  • No rank-position fallback for claim counts — missing claims ⇒ N/A,
    not fabricated numbers that create circular dependency.
  • Synthetic criteria use uniform multipliers (no dimension-specific bias).
  • Overall council grounding uses equal weighting (not rank-weighted).

Pharma-specific safety metrics (computed from peer-reviewed claims):

  Correctness = TP / (TP + 2×FN + FP)
      — Doubles the FN penalty: missing critical data is costlier
        than including an incorrect claim in pharma contexts.

  Precision = TP / (TP + FP)   [= RAGAS Faithfulness]
      — How many claims are actually correct?

  Recall = TP / (TP + FN)      [= RAGAS Context Recall, claim-based]
      — How much of the important information was covered?

  F1 = TP / (TP + 0.5×(FP+FN))  [= RAGAS Factual Correctness]
      — Standard balanced metric — no dimension-specific penalty.

Context Awareness (Catastrophic Forgetting detection):
  Uses SELF-review data only (reviewer == response author).
  Measures whether a model maintains coherent awareness of claims
  it made in Stage 1 when reviewing its own anonymized response.

  Context Awareness = self_TP / (self_TP + self_FP + self_FN)

  High → model recognises its own claims.
  Low  → catastrophic forgetting (self-contradiction or omission).

Enhanced CA (Multi-Round + Adversarial Shuffling):
  A lightweight CA Validation Pass re-probes each model with its own
  response (paragraphs shuffled) to test position-dependent recognition.

  Round 1 = original Stage 2 self-review (side-by-side with other responses)
  Round 2 = CA validation pass (isolated, shuffled paragraphs)

  Stability = 1 − |round1 − round2|    — low delta = robust self-awareness
  Combined CA = (round1 + round2) / 2  — more robust single estimate

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
    """
    Estimate per-criteria scores from rank position only.

    All criteria use the same base multiplier (1.0) to avoid
    dimension-specific bias.  Consensus is derived from rank-
    position variance.
    """
    base = _rank_position_score(avg_rank, total_models)
    cons = _consensus_score(positions, total_models)
    return {
        "relevancy": base,
        "faithfulness": base,
        "context_recall": base,
        "output_quality": base,
        "consensus": cons,
    }


# ═══════════════════════════════════════════════════════════════════════
# Pharma Safety Metrics (TP / FP / FN based)
# ═══════════════════════════════════════════════════════════════════════

def _pharma_correctness(tp: float, fp: float, fn: float) -> float:
    """Correctness = TP / (TP + 2×FN + FP).  FN penalty doubled for pharma."""
    denom = tp + 2 * fn + fp
    return tp / denom if denom > 0 else 0.0


def _precision(tp: float, fp: float) -> float:
    """Precision = TP / (TP + FP).  RAGAS Faithfulness equivalent."""
    denom = tp + fp
    return tp / denom if denom > 0 else 0.0


def _recall(tp: float, fn: float) -> float:
    """Recall = TP / (TP + FN).  RAGAS Context Recall (claim-based) equivalent."""
    denom = tp + fn
    return tp / denom if denom > 0 else 0.0


def _factual_correctness_f1(tp: float, fp: float, fn: float) -> float:
    """RAGAS Factual Correctness = TP / (TP + 0.5×(FP + FN)).
    Standard balanced F1 — no dimension-specific penalty.
    Complements pharma_correctness which double-penalises FN."""
    denom = tp + 0.5 * (fp + fn)
    return tp / denom if denom > 0 else 0.0


def _context_awareness(self_tp: float, self_fp: float, self_fn: float) -> float:
    """Context Awareness (Catastrophic Forgetting detector).

    Measures whether a model maintains awareness of claims it made
    in Stage 1 when reviewing its own anonymized response in Stage 2.

      Context Awareness = self_TP / (self_TP + self_FP + self_FN)

    High score → model recognises its own claims accurately.
    Low score  → model contradicts itself (self_FP) or forgets
                 information it stated (self_FN) = catastrophic forgetting.

    Only computed from SELF-review data (reviewer == response author).
    """
    denom = self_tp + self_fp + self_fn
    return self_tp / denom if denom > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════
# Self-review detection helper
# ═══════════════════════════════════════════════════════════════════════

def _canonicalise_model(name: str) -> str:
    """
    Strip fallback suffixes and normalise model names so self-review
    detection works even after self-healing renames.
    """
    # "openai/gpt-5-mini (fallback for x)" → "openai/gpt-5-mini"
    base = name.split(" (fallback")[0].strip()
    return base


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

    Bias-free guarantees:
      1. Self-reviews excluded — a reviewer never evaluates its own response.
      2. TP/FP/FN averaged per peer reviewer (not raw-summed).
      3. No rank-position fallback for claim counts.
      4. Synthetic criteria use uniform multipliers.
      5. Overall council grounding uses equal weighting.

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
                        "precision": float 0–100,  (= RAGAS Faithfulness)
                        "recall": float 0–100,     (= RAGAS Context Recall)
                        "f1": float 0–100,         (= RAGAS Factual Correctness)
                        "tp": int, "fp": int, "fn": int
                    },
                    "context_awareness": {
                        "score": float 0–100 | null,
                        "self_tp": int, "self_fp": int, "self_fn": int
                    } | null,
                    "verbalized_coverage": float 0–1,
                    "peer_reviews": int,
                    "rank": int
                }
            ],
            "criteria_definitions": [...],
            "pharma_formulas": { ... },
            "ragas_alignment": { ... },
            "context_awareness_formula": str,
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

    # ── Build canonical label → model mapping ────────────────────────
    label_to_canon = {label: _canonicalise_model(model)
                      for label, model in label_to_model.items()}
    model_to_label = {v: k for k, v in label_to_canon.items()}

    # ── Build position lists per model from parsed rankings ──────────
    model_positions: Dict[str, List[int]] = defaultdict(list)
    for ranking in stage2_results:
        parsed = ranking.get("parsed_ranking", [])
        for position, label in enumerate(parsed, start=1):
            if label in label_to_model:
                model_positions[label_to_canon.get(label, label_to_model[label])].append(position)

    # ── Collect PEER-ONLY rubric scores per response label ───────────
    verbalized_per_label: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    for ranking in stage2_results:
        reviewer = _canonicalise_model(ranking.get("model", ""))
        rubric = ranking.get("rubric_scores", {})
        for label, scores in rubric.items():
            response_author = label_to_canon.get(label, "")
            # BIAS FIX #1: exclude self-reviews
            if reviewer and response_author and reviewer == response_author:
                continue
            verbalized_per_label[label].append(scores)

    # ── Collect PEER-ONLY claim counts per response label ────────────
    claims_per_label: Dict[str, List[Dict[str, int]]] = defaultdict(list)
    # ── Collect SELF-REVIEW claim counts (for Context Awareness) ─────
    self_claims_per_label: Dict[str, Dict[str, int]] = {}
    for ranking in stage2_results:
        reviewer = _canonicalise_model(ranking.get("model", ""))
        claims = ranking.get("claim_counts", {})
        for label, counts in claims.items():
            response_author = label_to_canon.get(label, "")
            if reviewer and response_author and reviewer == response_author:
                # Self-review → store separately for Context Awareness
                self_claims_per_label[label] = counts
                continue
            claims_per_label[label].append(counts)

    # ── Compute per-response scores ──────────────────────────────────
    per_response = []
    criteria_ids = [c["id"] for c in RUBRIC_CRITERIA]

    for rank_idx, agg in enumerate(aggregate_rankings):
        model = agg["model"]
        avg_rank = agg["average_rank"]
        canon = _canonicalise_model(model)
        positions = model_positions.get(canon, [])
        label = model_to_label.get(canon, "")

        # --- Synthetic Math baseline (uniform multipliers — BIAS FIX #3) ---
        synthetic = _synthetic_criteria(avg_rank, total_models, positions)

        # --- Verbalized Sampling (peer-only) ---
        vs_list = verbalized_per_label.get(label, [])
        vs_count = len(vs_list)
        # Coverage fraction based on peer reviewers (total_models - 1)
        max_peer_reviewers = max(len(stage2_results) - 1, 1)
        alpha = vs_count / max_peer_reviewers

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

        # --- Pharma claim metrics (BIAS FIX #2: averaged, no rank fallback) ---
        claim_list = claims_per_label.get(label, [])
        n_peer_reviews = len(claim_list)

        if claim_list:
            # BIAS FIX #5: average per peer reviewer for equal distribution
            avg_tp = sum(c.get("tp", 0) for c in claim_list) / n_peer_reviews
            avg_fp = sum(c.get("fp", 0) for c in claim_list) / n_peer_reviews
            avg_fn = sum(c.get("fn", 0) for c in claim_list) / n_peer_reviews

            correctness = _pharma_correctness(avg_tp, avg_fp, avg_fn)
            precision = _precision(avg_tp, avg_fp)
            recall = _recall(avg_tp, avg_fn)
            f1 = _factual_correctness_f1(avg_tp, avg_fp, avg_fn)

            # Display rounded averages for user verification
            display_tp = round(avg_tp)
            display_fp = round(avg_fp)
            display_fn = round(avg_fn)
        else:
            # BIAS FIX #2: no rank-based fabrication — report unavailable (None)
            # When claim analysis was skipped (e.g. speed mode), emit None
            # so the frontend hides the section rather than showing misleading 0%.
            pharma_block = None
            display_tp = 0
            display_fp = 0
            display_fn = 0

        if claim_list:
            pharma_block = {
                "correctness": round(correctness * 100, 1),
                "precision": round(precision * 100, 1),
                "recall": round(recall * 100, 1),
                "f1": round(f1 * 100, 1),
                "tp": display_tp,
                "fp": display_fp,
                "fn": display_fn,
            }

        # --- Context Awareness (Catastrophic Forgetting detection) ---
        # Uses SELF-review only: did the model recognise its own claims?
        self_claims = self_claims_per_label.get(label, {})
        if self_claims:
            s_tp = self_claims.get("tp", 0)
            s_fp = self_claims.get("fp", 0)
            s_fn = self_claims.get("fn", 0)
            ctx_awareness = _context_awareness(s_tp, s_fp, s_fn)
        else:
            s_tp = s_fp = s_fn = 0
            ctx_awareness = None  # no self-review data available

        per_response.append({
            "model": model,
            "grounding_score": grounding_pct,
            "criteria": {k: round(v * 100, 1) for k, v in blended.items()},
            "pharma_metrics": pharma_block,
            "context_awareness": {
                "score": round(ctx_awareness * 100, 1) if ctx_awareness is not None else None,
                "self_tp": s_tp,
                "self_fp": s_fp,
                "self_fn": s_fn,
            } if self_claims else None,
            "verbalized_coverage": round(alpha, 2),
            "peer_reviews": n_peer_reviews,
            "rank": rank_idx + 1,
        })

    # ── Overall council grounding (BIAS FIX #4: equal weighting) ─────
    if per_response:
        overall = sum(r["grounding_score"] for r in per_response) / len(per_response)
    else:
        overall = 0

    # ── Detect if claim analysis was available ─────────────────────
    claim_analysis_available = any(
        r["pharma_metrics"] is not None for r in per_response
    )

    return {
        "overall_score": round(overall, 1),
        "per_response": per_response,
        "claim_analysis_available": claim_analysis_available,
        "criteria_definitions": RUBRIC_CRITERIA,
        "pharma_formulas": {
            "correctness": "TP / (TP + 2×FN + FP)",
            "precision": "TP / (TP + FP)",
            "recall": "TP / (TP + FN)",
            "f1": "TP / (TP + 0.5×(FP + FN))",
        },
        "ragas_alignment": {
            "precision": "= RAGAS Faithfulness",
            "recall": "= RAGAS Context Recall (claim-based)",
            "f1": "= RAGAS Factual Correctness (balanced F1)",
            "correctness": "Pharma-weighted (FN penalty doubled)",
        },
        "context_awareness_formula": "self_TP / (self_TP + self_FP + self_FN)",
        "council_size": total_models,
        "reviewers_count": len(stage2_results),
    }


# ═══════════════════════════════════════════════════════════════════════
# Enhanced CA — Multi-Round + Adversarial Shuffling
# ═══════════════════════════════════════════════════════════════════════

def enhance_ca_with_validation(
    grounding_scores: Dict[str, Any],
    ca_validation_results: Dict[str, Dict[str, Any]],
    label_to_model: Dict[str, str],
) -> Dict[str, Any]:
    """
    Enrich grounding_scores with multi-round CA data from the validation pass.

    For each model that has both a Round 1 (original Stage 2 self-review)
    and Round 2 (CA validation pass with shuffled paragraphs), compute:

      • round1_score — original CA from Stage 2
      • round2_score — CA from the validation probe (shuffled, isolated)
      • stability   — 1 − |round1 − round2|  (0–100, higher = more robust)
      • adversarial_delta — signed change from round1 to round2
      • combined_score — average of round1 + round2  (more robust estimate)

    Mutates grounding_scores in-place and returns it.

    Args:
        grounding_scores: The existing grounding scores dict (from
            compute_response_grounding_scores).
        ca_validation_results: Dict from stage2_ca_validation_pass(),
            mapping model_name → {claims, shuffled, raw_text}.
        label_to_model: "Response X" → model_name mapping.

    Returns:
        The enriched grounding_scores dict (same reference, mutated).
    """
    if not ca_validation_results:
        return grounding_scores

    # Build canonical model name → validation result lookup
    canon_to_validation = {}
    for model_name, val_data in ca_validation_results.items():
        canon = _canonicalise_model(model_name)
        canon_to_validation[canon] = val_data

    for resp in grounding_scores.get("per_response", []):
        model = resp.get("model", "")
        canon = _canonicalise_model(model)
        ca = resp.get("context_awareness")
        val = canon_to_validation.get(canon)

        if val is None:
            # No validation probe for this model — skip
            continue

        # Round 2 claims from validation pass
        r2_claims = val.get("claims", {})
        r2_tp = r2_claims.get("tp", 0)
        r2_fp = r2_claims.get("fp", 0)
        r2_fn = r2_claims.get("fn", 0)
        r2_denom = r2_tp + r2_fp + r2_fn
        round2_score = _context_awareness(r2_tp, r2_fp, r2_fn) if r2_denom > 0 else None

        # Round 1 score (from original Stage 2 self-review)
        if ca and ca.get("score") is not None:
            round1_score = ca["score"] / 100.0  # back to 0–1 for computation
        else:
            round1_score = None

        # Compute enhanced metrics
        if round1_score is not None and round2_score is not None:
            stability = 1.0 - abs(round1_score - round2_score)
            combined = (round1_score + round2_score) / 2.0
            adversarial_delta = round2_score - round1_score

            # Enrich the context_awareness block
            if ca is None:
                ca = {}
            ca["round1_score"] = round(round1_score * 100, 1)
            ca["round2_score"] = round(round2_score * 100, 1)
            ca["round2_tp"] = r2_tp
            ca["round2_fp"] = r2_fp
            ca["round2_fn"] = r2_fn
            ca["stability"] = round(stability * 100, 1)
            ca["adversarial_delta"] = round(adversarial_delta * 100, 1)
            ca["combined_score"] = round(combined * 100, 1)
            ca["shuffled"] = val.get("shuffled", False)
            resp["context_awareness"] = ca

        elif round2_score is not None:
            # Only round 2 available (no original self-review)
            resp["context_awareness"] = {
                "score": round(round2_score * 100, 1),
                "self_tp": r2_tp,
                "self_fp": r2_fp,
                "self_fn": r2_fn,
                "round1_score": None,
                "round2_score": round(round2_score * 100, 1),
                "round2_tp": r2_tp,
                "round2_fp": r2_fp,
                "round2_fn": r2_fn,
                "stability": None,
                "adversarial_delta": None,
                "combined_score": round(round2_score * 100, 1),
                "shuffled": val.get("shuffled", False),
            }

    # Add enhanced CA formulas to the return block
    grounding_scores["ca_enhanced"] = True
    grounding_scores["ca_stability_formula"] = "1 − |round1 − round2|"
    grounding_scores["ca_combined_formula"] = "(round1 + round2) / 2"

    return grounding_scores

