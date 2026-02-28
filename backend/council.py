"""
3-stage LLM Council orchestration with self-healing resilience.

Research-backed enhancements:
  • Position Debiasing (arXiv:2405.19323) — shuffle response order per
    reviewer to mitigate first-position bias in peer evaluation.
  • Chairman Self-Reflection (arXiv:2602.03837 §Adversarial Reviewer;
    arXiv:2602.13949 §Experience-Reflection-Consolidation) — after initial
    synthesis the chairman reviews its own output for drift / omissions.
  • Gated Adaptation integration point (arXiv:2602.13949 §Gated Reflection)
    — ECA adapt_prompt/adapt_rubric fire only when grounding < τ.
"""

import asyncio
import copy
import logging
import random
import re
import time
from typing import List, Dict, Any, Tuple, Optional
from .openrouter import query_models_parallel, query_model
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL, DEFAULT_COUNCIL_MODELS, DEFAULT_CHAIRMAN_MODEL
from .resilience import (
    kill_switch,
    circuit_breaker,
    resolve_fallback,
    health_monitor,
    check_quorum,
    KillSwitchError,
    QuorumError,
    MIN_STAGE1_QUORUM,
    MIN_STAGE2_QUORUM,
)
from .grounding import compute_response_grounding_scores

logger = logging.getLogger("llm_council.council")


def build_conversation_context(conversation_history: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Build a text summary of conversation history for context.
    
    Args:
        conversation_history: List of previous messages in the conversation
        
    Returns:
        Formatted string with conversation context
    """
    if not conversation_history or len(conversation_history) == 0:
        return ""
    
    context_parts = ["Previous conversation context:"]
    for msg in conversation_history:
        if msg.get("role") == "user":
            context_parts.append(f"\nUser: {msg.get('content', '')[:500]}...")
        elif msg.get("role") == "assistant":
            # For assistant messages, just include the final synthesis if available
            if msg.get("stage3"):
                response_preview = msg["stage3"].get("response", "")[:500]
                context_parts.append(f"\nCouncil Response: {response_preview}...")
    
    return "\n".join(context_parts) + "\n\n---\n\n"


async def stage1_collect_responses(
    user_query: str,
    council_models: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.
    Self-healing: retries failed models, substitutes fallbacks, enforces quorum.

    Args:
        user_query: The user's question
        council_models: Optional list of model IDs to use (defaults to COUNCIL_MODELS)
        conversation_history: Optional list of previous messages for context
        web_search_enabled: Whether to enable Google web search via MyGenAssist
        session_id: Kill switch session ID

    Returns:
        List of dicts with 'model' and 'response' keys

    Raises:
        KillSwitchError: If session was killed
        QuorumError: If minimum quorum cannot be met
    """
    # Kill switch gate
    if session_id and kill_switch.is_session_killed(session_id):
        raise KillSwitchError(f"Session {session_id} killed before Stage 1")

    models_to_use = council_models or COUNCIL_MODELS
    
    # Build context-aware prompt for follow-up questions
    context = build_conversation_context(conversation_history)
    if context:
        full_query = f"{context}Current question (follow-up): {user_query}"
    else:
        full_query = user_query
    
    messages = [{"role": "user", "content": full_query}]

    # Query all models in parallel (openrouter handles retries + circuit breaker)
    responses = await query_models_parallel(
        models_to_use, messages,
        web_search_enabled=web_search_enabled,
        session_id=session_id,
    )

    # Collect successful results
    stage1_results = []
    failed_models = []
    used_models = set(models_to_use)

    for model, response in responses.items():
        if response is not None:
            stage1_results.append({
                "model": model,
                "response": response.get('content', ''),
                "usage": response.get('usage'),
            })
        else:
            failed_models.append(model)

    # Self-healing: attempt fallback models for any that failed
    if failed_models and len(stage1_results) < len(models_to_use):
        logger.info(f"[Stage1] {len(failed_models)} model(s) failed, attempting fallbacks...")
        for failed_model in failed_models:
            # Kill switch check before each fallback attempt
            if session_id and kill_switch.is_session_killed(session_id):
                raise KillSwitchError(f"Session {session_id} killed during Stage 1 fallback")

            fallback = resolve_fallback(failed_model, used_models)
            if fallback:
                used_models.add(fallback)
                fb_response = await query_model(
                    fallback, messages,
                    web_search_enabled=web_search_enabled,
                    session_id=session_id,
                )
                if fb_response is not None:
                    stage1_results.append({
                        "model": f"{fallback} (fallback for {failed_model})",
                        "response": fb_response.get('content', ''),
                        "usage": fb_response.get('usage'),
                    })
                    health_monitor.log_healing_action("stage1_fallback_success", {
                        "failed_model": failed_model,
                        "fallback_model": fallback,
                    })
                else:
                    health_monitor.log_healing_action("stage1_fallback_failed", {
                        "failed_model": failed_model,
                        "fallback_model": fallback,
                    })

    # Quorum check
    if not check_quorum(stage1_results, "Stage 1", MIN_STAGE1_QUORUM):
        health_monitor.log_healing_action("stage1_quorum_failure", {
            "successful": len(stage1_results),
            "required": MIN_STAGE1_QUORUM,
        })
        raise QuorumError(
            f"Stage 1 quorum not met: got {len(stage1_results)}, "
            f"need {MIN_STAGE1_QUORUM}"
        )

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    council_models: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.
    Self-healing: retries failed rankers, accepts partial rankings if quorum met.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1
        council_models: Optional list of model IDs to use (defaults to COUNCIL_MODELS)
        conversation_history: Optional list of previous messages for context
        web_search_enabled: Whether to enable Google web search via MyGenAssist
        session_id: Kill switch session ID

    Returns:
        Tuple of (rankings list, label_to_model mapping)

    Raises:
        KillSwitchError: If session was killed
        QuorumError: If minimum ranking quorum cannot be met
    """
    # Kill switch gate
    if session_id and kill_switch.is_session_killed(session_id):
        raise KillSwitchError(f"Session {session_id} killed before Stage 2")

    models_to_use = council_models or COUNCIL_MODELS
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt with optional context
    context = build_conversation_context(conversation_history)
    context_note = ""
    if context:
        context_note = f"""
Note: This is a follow-up question in an ongoing conversation.
{context}
"""

    # ── Position Debiasing (arXiv:2405.19323) ──────────────────────
    # Shuffle presentation order PER REVIEWER to mitigate first-position
    # bias. Labels stay the same, only the display order changes.
    # Build per-model prompts with independent shuffled orderings.
    per_model_prompts: Dict[str, str] = {}
    for model in models_to_use:
        shuffled_indices = list(range(len(stage1_results)))
        random.shuffle(shuffled_indices)

        responses_text = "\n\n".join([
            f"Response {labels[i]}:\n{stage1_results[i]['response']}"
            for i in shuffled_indices
        ])
        per_model_prompts[model] = responses_text

    # Default responses_text for backwards compat (original order)
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    ranking_prompt_template = """You are a pharmaceutical domain expert evaluating different responses to the following question:
{context_note}
Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

═══════════════════════════════════════════════════════════
PART 1 — RUBRIC EVALUATION (Verbalized Sampling)
═══════════════════════════════════════════════════════════
For EACH response, provide a score from 0 to 10 on each criterion below.
After each score, give a brief justification (1-2 sentences).

Criteria:
  • Relevancy (0-10): How directly and completely the response addresses the original question
  • Faithfulness (0-10): Factual accuracy, absence of hallucinations, grounded in evidence
  • Context Recall (0-10): Coverage of key concepts, dimensions, and nuances raised across all responses
  • Output Quality (0-10): Clarity, structure, depth, readability, and overall coherence
  • Consensus (0-10): Would other domain experts broadly agree with the claims made?

Format EXACTLY as follows for each response:

RUBRIC Response X:
  Relevancy: <score>/10 — <justification>
  Faithfulness: <score>/10 — <justification>
  Context Recall: <score>/10 — <justification>
  Output Quality: <score>/10 — <justification>
  Consensus: <score>/10 — <justification>

═══════════════════════════════════════════════════════════
PART 2 — CLAIM CLASSIFICATION (Pharma Safety)
═══════════════════════════════════════════════════════════
For EACH response, classify its major claims in pharmaceutical context:
  TP (True Positive)  = Correct, verifiable claim relevant to the question
  FP (False Positive) = Incorrect, misleading, or hallucinated claim
  FN (False Negative) = Important information the response FAILED to mention

Format EXACTLY as follows for each response:

CLAIMS Response X:
  TP: <count> — <brief summary of correct claims>
  FP: <count> — <brief summary of incorrect/hallucinated claims, or "None detected">
  FN: <count> — <brief summary of important omissions, or "None detected">

═══════════════════════════════════════════════════════════
PART 3 — FINAL RANKING
═══════════════════════════════════════════════════════════
Based on your rubric evaluation and claim analysis above, provide
your final ranking from best to worst.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")

Now provide your complete evaluation:"""

    # Build per-model messages using the per-model debiased prompts
    per_model_messages: Dict[str, List[Dict[str, str]]] = {}
    for model in models_to_use:
        model_prompt = ranking_prompt_template.format(
            context_note=context_note,
            user_query=user_query,
            responses_text=per_model_prompts.get(model, responses_text),
        )
        per_model_messages[model] = [{"role": "user", "content": model_prompt}]

    messages = [{"role": "user", "content": ranking_prompt_template.format(
        context_note=context_note,
        user_query=user_query,
        responses_text=responses_text,
    )}]

    # Get rankings from all council models in parallel (with resilience)
    # Pass per-model messages for position-debiased evaluation
    responses = await query_models_parallel(
        models_to_use, messages,
        web_search_enabled=web_search_enabled,
        session_id=session_id,
        per_model_messages=per_model_messages,
    )

    # Format results
    stage2_results = []
    failed_rankers = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            rubric = parse_rubric_scores(full_text)
            claims = parse_claim_counts(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed,
                "rubric_scores": rubric,
                "claim_counts": claims,
                "usage": response.get('usage'),
            })
        else:
            failed_rankers.append(model)

    # Self-healing: log ranker failures but accept partial results if quorum met
    if failed_rankers:
        health_monitor.log_healing_action("stage2_rankers_failed", {
            "failed": failed_rankers,
            "successful": len(stage2_results),
        })

    # Quorum check for Stage 2
    if not check_quorum(stage2_results, "Stage 2", MIN_STAGE2_QUORUM):
        health_monitor.log_healing_action("stage2_quorum_failure", {
            "successful": len(stage2_results),
            "required": MIN_STAGE2_QUORUM,
        })
        raise QuorumError(
            f"Stage 2 quorum not met: got {len(stage2_results)} rankings, "
            f"need {MIN_STAGE2_QUORUM}"
        )

    return stage2_results, label_to_model


# ═══════════════════════════════════════════════════════════════════════
# Stage 2.5 — Relevancy Gate
# ═══════════════════════════════════════════════════════════════════════

RELEVANCY_GATE_THRESHOLD = 5.0   # avg Relevancy < 5/10 → gated out
RELEVANCY_GATE_MIN_REVIEWERS = 2  # need ≥2 reviewers to trigger gate


def compute_relevancy_gate(
    stage2_results: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate Relevancy rubric scores per response across all Stage 2
    reviewers.  Any response with avg relevancy < RELEVANCY_GATE_THRESHOLD/10
    across ≥ RELEVANCY_GATE_MIN_REVIEWERS reviewers is **gated out**.

    Returns:
        Dict mapping each response label (e.g. 'Response A') to:
            {
                'avg_relevancy': float (0–10 scale),
                'reviewer_count': int,
                'gated_out': bool,
            }
    """
    # Collect relevancy scores per response label across all reviewers
    label_scores: Dict[str, List[float]] = {}
    for result in stage2_results:
        rubric = result.get("rubric_scores", {})
        for label, scores in rubric.items():
            rel = scores.get("relevancy")
            if rel is not None:
                label_scores.setdefault(label, []).append(rel * 10.0)  # un-normalise to 0–10

    gate: Dict[str, Dict[str, Any]] = {}
    for label, scores in label_scores.items():
        avg = sum(scores) / len(scores) if scores else 0.0
        reviewer_count = len(scores)
        gated_out = (
            avg < RELEVANCY_GATE_THRESHOLD
            and reviewer_count >= RELEVANCY_GATE_MIN_REVIEWERS
        )
        gate[label] = {
            "avg_relevancy": round(avg, 2),
            "reviewer_count": reviewer_count,
            "gated_out": gated_out,
        }
        if gated_out:
            logger.warning(
                f"[RelevancyGate] {label} GATED OUT — avg_relevancy={avg:.1f}/10 "
                f"across {reviewer_count} reviewers (threshold={RELEVANCY_GATE_THRESHOLD})"
            )

    return gate


# ═══════════════════════════════════════════════════════════════════════
# Stage 3 — Adaptive Prompt Optimisation Helpers
# ═══════════════════════════════════════════════════════════════════════

_VP_KEYWORDS = re.compile(
    r'value\s*proposition|competitive\s*position|brand\s*strategy|'
    r'messaging\s*framework|market\s*positioning|differentiation',
    re.IGNORECASE,
)
_CHEM_KEYWORDS = re.compile(
    r'molecule|compound|drug\s*structure|SMILES|chemical|pharmacophore|'
    r'synthesis\s*route|reaction|IC50|EC50|Ki\b|Kd\b|binding\s*affinity|'
    r'molecular\s*weight|log\s*P',
    re.IGNORECASE,
)
_COMPARISON_KEYWORDS = re.compile(
    r'compar|versus|vs\.?\b|head.to.head|difference\s*between|'
    r'advantage|disadvantage|which\s*is\s*better',
    re.IGNORECASE,
)


def _detect_query_features(query: str, stage1_responses: str) -> Dict[str, bool]:
    """Quick heuristic to detect what output features the query needs."""
    combined = query + " " + stage1_responses[:2000]
    return {
        "needs_vp": bool(_VP_KEYWORDS.search(combined)),
        "needs_chemistry": bool(_CHEM_KEYWORDS.search(combined)),
        "needs_comparison": bool(_COMPARISON_KEYWORDS.search(combined)),
    }


# ── Static system message (cacheable by LLM APIs) ───────────────────

_SYSTEM_MSG_BASE = """You are the Chairman of an LLM Council. Your operating context is pharmaceutical / life-sciences, but you MUST adapt your synthesis depth and framing to match the actual question — not every question requires clinical-grade rigor or pharma-specific safety analysis. For clinical, pharmacological, or patient-safety questions, accuracy is paramount and missing critical information (FN) is more dangerous than including minor inaccuracies (FP). For general, educational, or non-clinical questions, prioritise clarity, relevance, and directness over exhaustive inclusion.

Your task is to synthesize individual model responses and peer review rankings into a single, comprehensive, accurate answer that **directly addresses the original question**.

═══════════════════════════════════════════════════════════
ANTI-DRIFT RULES (override all other guidelines)
═══════════════════════════════════════════════════════════
0a. You MUST NOT incorporate content from ⛔ EXCLUDED responses (marked below), regardless of factual correctness.
0b. Only incorporate insights that DIRECTLY ADDRESS the original question.
0c. Every piece of information you include must pass this test: "Does this directly help answer the user's original question?" If not, omit it.

Core principles:
1. RELEVANCY FIRST — read the original question carefully. Only include content that is directly relevant to what was asked. Exclude tangential, off-topic, or loosely-related material regardless of its accuracy. A correct fact that does not answer the question is noise, not value.
2. For clinical/safety questions: put patient-safety and factual accuracy first — prefer responses with high Faithfulness scores and low FN counts. For non-clinical questions: prioritise clarity and practical usefulness.
3. Weight reviewer consensus: if multiple reviewers agree a response is strong on Relevancy and Context Recall, lean on that response. Conversely, responses scored LOW on Relevancy by reviewers should be de-weighted or excluded even if they are factually correct.
4. Incorporate unique correct insights from lower-ranked responses ONLY IF those insights directly address the original question. Do not include tangential content merely because it is accurate — relevancy to the user's question is the gating criterion. Lower-ranked insights are included ONLY IF relevant; off-topic material is omitted even if factually correct.
5. Flag any claims where reviewers disagreed on TP/FP classification — note the uncertainty explicitly.
6. Structure your answer clearly with appropriate headings when the subject matter warrants it.
7. When evidence citations are provided, reference them inline using their tags (e.g. [FDA-L1], [CT-2], [PM-3]) and include a REFERENCES section at the end with clickable URLs.
8. SCIENTIFIC INTELLIGENCE: Cross-reference web-sourced findings with council responses. Use citation counts and journal impact to weight reliability. Highlight recent findings that supersede older knowledge. Flag arXiv preprints as non-peer-reviewed. Use Wikipedia as background only, not a primary source.
9. RICH SCIENTIFIC OUTPUT (Markdown rendered):
   - Use Markdown TABLES for comparative data.
   - Use ordered/unordered LISTS for protocols, criteria, mechanisms.
   - Use subscript/superscript HTML tags for chemical formulas (H<sub>2</sub>O).
   - Use LaTeX math for quantitative data: inline $K_d$ or display $$AUC$$.
10. INFOGRAPHIC DATA: After your answer, generate a structured JSON block in ```infographic markers:
   {"title": "...", "type": "summary", "key_metrics": [{"label":"...","value":"...","icon":"emoji"}], "comparison": {"headers":[...],"rows":[...]}, "process_steps": [{"step":1,"title":"...","description":"..."}], "highlights": [{"text":"...","type":"success|warning|info|danger"}]}
   Include ONLY relevant fields. key_metrics for quantitative facts, comparison only if comparing items, process_steps only for mechanisms/pathways, highlights always 2-4 takeaways."""

_CHEMISTRY_ADDON = """
MOLECULAR STRUCTURES: ALWAYS use SMILES code blocks for molecules/drugs/compounds:
```smiles
CC(=O)Oc1ccccc1C(=O)O
```
NEVER use external image URLs for chemical structures. Include SMILES whenever you mention a specific molecule by name."""

_VP_ADDON = """
VALUE PROPOSITION MODE: Structure your answer as:
- **TITLE**: Product + therapeutic area
- **CHALLENGE**: Unmet need, disease burden, limitations of current treatments
- **SOLUTION**: Mechanism, clinical differentiation, key efficacy data
- **OUTCOME**: Clinical benefits, safety, transformative impact
After the VP text, generate infographic JSON with type "value_proposition" and sections: challenge, solution, outcome."""

_MEMORY_ADDON = """
MEMORY-AWARE SYNTHESIS: You have access to the council's memory system.
- When a PRIOR DELIBERATION CONTEXT section is present, the user has asked a question similar to one already processed.
- If a near-duplicate is detected, BEGIN your response with a brief "Memory Advisory" section:
  > ⚠️ **Memory Advisory**: This query closely matches a previous deliberation (similarity: X%). The council previously answered this with a grounding score of Y%. Consider reviewing the prior result first.
  > **Suggested alternatives**: <list 2-3 alternative follow-up questions that would build on the prior answer>
- After the advisory, still provide the full synthesis — the user may want a fresh perspective.
- When prior domain knowledge or past deliberations are provided, actively cross-reference them with the current council responses. Highlight what is NEW compared to the prior answer, and flag any contradictions.
- Leverage procedural memories (learned workflows) when applicable to structure your response.
- NEVER fabricate memory references — only reference memories explicitly provided in the prompt."""


def _build_system_message(features: Dict[str, bool]) -> str:
    """Assemble the system message with only the relevant instruction addons."""
    parts = [_SYSTEM_MSG_BASE]
    if features.get("needs_chemistry"):
        parts.append(_CHEMISTRY_ADDON)
    if features.get("needs_vp"):
        parts.append(_VP_ADDON)
    if features.get("has_memory_context"):
        parts.append(_MEMORY_ADDON)
    return "\n".join(parts)


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    chairman_model: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
    evidence_context: str = "",
    relevancy_gate: Optional[Dict[str, Dict[str, Any]]] = None,
    memory_context: str = "",
    duplicate_episode: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.
    Self-healing: retries chairman, falls back to alternate models if chairman fails.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2
        chairman_model: Optional chairman model ID (defaults to CHAIRMAN_MODEL)
        conversation_history: Optional list of previous messages for context
        web_search_enabled: Whether to enable Google web search via MyGenAssist
        session_id: Kill switch session ID

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Kill switch gate
    if session_id and kill_switch.is_session_killed(session_id):
        raise KillSwitchError(f"Session {session_id} killed before Stage 3")

    chairman_to_use = chairman_model or CHAIRMAN_MODEL
    t0 = time.perf_counter()

    # Build context for follow-up questions
    context = build_conversation_context(conversation_history)
    context_note = ""
    if context:
        context_note = f"""
Note: This is a follow-up question in an ongoing conversation. Consider the previous context when synthesizing your response.
{context}
"""

    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    # Build rubric summary for chairman visibility
    rubric_lines = []
    for r in stage2_results:
        rubric = r.get("rubric_scores", {})
        claims = r.get("claim_counts", {})
        reviewer = r.get("model", "Reviewer")
        if rubric:
            for label, scores in rubric.items():
                score_str = ", ".join(f"{k}: {v:.1f}" for k, v in scores.items())
                rubric_lines.append(f"  {reviewer} → {label}: {score_str}")
        if claims:
            for label, c in claims.items():
                rubric_lines.append(
                    f"  {reviewer} → {label}: TP={c.get('tp',0)}, FP={c.get('fp',0)}, FN={c.get('fn',0)}"
                )
    rubric_section = "\n".join(rubric_lines) if rubric_lines else "  (No structured rubric data parsed)"

    # ── OPT: Adaptive prompt — detect query features, trim prompt ────
    features = _detect_query_features(user_query, stage1_text)
    # Activate memory addon when memory context or duplicate is present
    if memory_context or duplicate_episode:
        features["has_memory_context"] = True
    system_msg = _build_system_message(features)

    # ── Memory context: prior deliberations & domain knowledge ──
    memory_section = ""
    if duplicate_episode:
        sim = duplicate_episode.get("duplicate_similarity", 0)
        gs = duplicate_episode.get("grounding_score", 0)
        prev_preview = duplicate_episode.get("chairman_response_preview", "")[:400]
        prev_query = duplicate_episode.get("query_preview", "")[:200]
        memory_section += (
            f"PRIOR DELIBERATION CONTEXT — NEAR-DUPLICATE DETECTED\n"
            f"  Similarity: {sim:.0%} | Prior Grounding: {gs:.0%}\n"
            f"  Previous query: \"{prev_query}\"\n"
            f"  Previous chairman summary: {prev_preview}...\n"
            f"  ── This user has submitted a very similar query/document before.\n"
            f"  ── Begin with a Memory Advisory noting this, suggest 2-3 alternative\n"
            f"     follow-up questions, then provide your full fresh synthesis.\n\n"
        )
    if memory_context:
        memory_section += memory_context + "\n"

    # ── Relevancy Gate: annotate excluded responses in the user prompt ──
    gate_section = ""
    if relevancy_gate:
        excluded = [lbl for lbl, g in relevancy_gate.items() if g.get("gated_out")]
        if excluded:
            lines = ["RELEVANCY GATE — The following responses scored below the relevancy threshold and are EXCLUDED:"]
            for lbl in excluded:
                g = relevancy_gate[lbl]
                lines.append(f"  ⛔ {lbl}: avg Relevancy {g['avg_relevancy']:.1f}/10 across {g['reviewer_count']} reviewers — EXCLUDED")
            lines.append("You MUST NOT use content from excluded responses.")
            gate_section = "\n".join(lines) + "\n\n"

    # User message contains only the data (system msg has all instructions)
    user_prompt = f"""{context_note}
Original Question: {user_query}

{gate_section}STAGE 1 — Individual Responses:
{stage1_text}

STAGE 2 — Peer Rankings:
{stage2_text}

STAGE 2 — Rubric Evaluation & Claim Analysis:
{rubric_section}

{evidence_context}
{memory_section}{f'Consider the context from the previous conversation.' if context else ''}

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_prompt},
    ]

    # ── OPT: Speculative Racing — fire chairman + 1 racer in parallel ──
    # If the primary chairman fails or is slow, the racer provides a
    # fast fallback.  We cancel the slower task once one completes.
    racer_model = resolve_fallback(chairman_to_use, {chairman_to_use})

    async def _query_with_label(model: str, label: str):
        """Wrapper that tags the result with model/label for identification."""
        resp = await query_model(
            model, messages,
            web_search_enabled=web_search_enabled,
            session_id=session_id,
        )
        return (model, label, resp)

    if racer_model:
        # Fire both in parallel, take whichever finishes first
        primary_task = asyncio.create_task(_query_with_label(chairman_to_use, "primary"))
        racer_task = asyncio.create_task(_query_with_label(racer_model, "racer"))

        done, pending = await asyncio.wait(
            {primary_task, racer_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=150,
        )

        # Process the winner
        response = None
        winner_model = chairman_to_use
        winner_label = "primary"

        for task in done:
            try:
                model, label, resp = task.result()
                if resp is not None:
                    response = resp
                    winner_model = model
                    winner_label = label
                    break
            except Exception as e:
                logger.warning(f"[Stage3] Speculative {label} error: {e}")

        # If the winner succeeded, cancel the loser
        if response is not None:
            for task in pending:
                task.cancel()
            elapsed = time.perf_counter() - t0
            logger.info(
                f"[Stage3] Speculative racing: {winner_label} ({winner_model}) "
                f"won in {elapsed:.1f}s"
            )

            model_desc = winner_model
            if winner_label == "racer":
                model_desc = f"{winner_model} (speculative racer for {chairman_to_use})"
                health_monitor.log_healing_action("stage3_racer_won", {
                    "chairman": chairman_to_use,
                    "racer": winner_model,
                    "elapsed_s": round(elapsed, 1),
                })

            return {
                "model": model_desc,
                "response": response.get('content', ''),
                "usage": response.get('usage'),
            }

        # Both returned but neither succeeded — await the second
        for task in pending:
            try:
                model, label, resp = await task
                if resp is not None:
                    elapsed = time.perf_counter() - t0
                    logger.info(f"[Stage3] Late {label} ({model}) succeeded in {elapsed:.1f}s")
                    return {
                        "model": model,
                        "response": resp.get('content', ''),
                        "usage": resp.get('usage'),
                    }
            except Exception as e:
                logger.warning(f"[Stage3] Late {label} error: {e}")

    else:
        # No racer available — single primary query
        response = await query_model(
            chairman_to_use, messages,
            web_search_enabled=web_search_enabled,
            session_id=session_id,
        )
        if response is not None:
            elapsed = time.perf_counter() - t0
            logger.info(f"[Stage3] Chairman {chairman_to_use} responded in {elapsed:.1f}s")
            return {
                "model": chairman_to_use,
                "response": response.get('content', ''),
                "usage": response.get('usage'),
            }

    # ── Self-healing: Chairman failed — try fallback chairmen ───────────
    logger.warning(f"[Stage3] Chairman {chairman_to_use} failed, attempting fallbacks...")
    health_monitor.log_healing_action("chairman_primary_failed", {
        "chairman": chairman_to_use,
    })

    used = {chairman_to_use}
    fallback_chairman = resolve_fallback(chairman_to_use, used)

    while fallback_chairman:
        # Kill switch check before each fallback
        if session_id and kill_switch.is_session_killed(session_id):
            raise KillSwitchError(f"Session {session_id} killed during Stage 3 fallback")

        logger.info(f"[Stage3] Trying fallback chairman: {fallback_chairman}")
        fb_response = await query_model(
            fallback_chairman, messages,
            web_search_enabled=web_search_enabled,
            session_id=session_id,
        )
        if fb_response is not None:
            health_monitor.log_healing_action("chairman_fallback_success", {
                "original_chairman": chairman_to_use,
                "fallback_chairman": fallback_chairman,
            })
            return {
                "model": f"{fallback_chairman} (acting chairman, fallback for {chairman_to_use})",
                "response": fb_response.get('content', ''),
                "usage": fb_response.get('usage'),
            }

        used.add(fallback_chairman)
        fallback_chairman = resolve_fallback(chairman_to_use, used)

    # ── Last resort: use the top-ranked Stage 1 response directly ──────
    logger.error("[Stage3] All chairmen failed — using top-ranked Stage 1 response")
    health_monitor.log_healing_action("chairman_all_failed_using_stage1", {
        "attempted_chairmen": list(used),
    })

    if stage1_results:
        return {
            "model": f"{stage1_results[0]['model']} (emergency: direct Stage 1 response)",
            "response": stage1_results[0]['response']
        }

    return {
        "model": "error",
        "response": "Error: All chairman models and fallbacks failed. Unable to generate final synthesis."
    }


def parse_rubric_scores(text: str) -> Dict[str, Dict[str, float]]:
    """
    Parse Verbalized Sampling rubric scores from Stage 2 output.

    Looks for blocks like:
        RUBRIC Response A:
          Relevancy: 8/10 — justification...
          Faithfulness: 7/10 — ...

    Returns:
        Dict mapping response label (e.g. "Response A") to a dict of
        criteria scores normalised to 0–1.
    """
    import re
    results: Dict[str, Dict[str, float]] = {}
    criteria_ids = ["relevancy", "faithfulness", "context_recall", "output_quality", "consensus"]
    criteria_patterns = {
        "relevancy": r"Relevancy:\s*(\d+(?:\.\d+)?)\s*/\s*10",
        "faithfulness": r"Faithfulness:\s*(\d+(?:\.\d+)?)\s*/\s*10",
        "context_recall": r"Context\s*Recall:\s*(\d+(?:\.\d+)?)\s*/\s*10",
        "output_quality": r"Output\s*Quality:\s*(\d+(?:\.\d+)?)\s*/\s*10",
        "consensus": r"Consensus:\s*(\d+(?:\.\d+)?)\s*/\s*10",
    }

    # Split by RUBRIC Response X: blocks
    blocks = re.split(r'RUBRIC\s+(Response\s+[A-Z]):', text, flags=re.IGNORECASE)
    # blocks = ['before', 'Response A', 'block_text', 'Response B', 'block_text', ...]
    for i in range(1, len(blocks) - 1, 2):
        label = blocks[i].strip()
        block = blocks[i + 1]
        scores = {}
        for cid, pattern in criteria_patterns.items():
            m = re.search(pattern, block, re.IGNORECASE)
            if m:
                scores[cid] = min(1.0, float(m.group(1)) / 10.0)
        if scores:
            results[label] = scores

    return results


def parse_claim_counts(text: str) -> Dict[str, Dict[str, int]]:
    """
    Parse TP / FP / FN claim counts from Stage 2 output.

    Looks for blocks like:
        CLAIMS Response A:
          TP: 5 — correct claims about...
          FP: 1 — incorrectly stated that...
          FN: 2 — missed important info about...

    Returns:
        Dict mapping response label to {"tp": int, "fp": int, "fn": int}.
    """
    import re
    results: Dict[str, Dict[str, int]] = {}

    blocks = re.split(r'CLAIMS\s+(Response\s+[A-Z]):', text, flags=re.IGNORECASE)
    for i in range(1, len(blocks) - 1, 2):
        label = blocks[i].strip()
        block = blocks[i + 1]
        counts = {"tp": 0, "fp": 0, "fn": 0}
        for key in ("TP", "FP", "FN"):
            m = re.search(rf'{key}:\s*(\d+)', block)
            if m:
                counts[key.lower()] = int(m.group(1))
        results[label] = counts

    return results


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    # NOTE: Bayer API uses model IDs without vendor prefixes
    response = await query_model("gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


# ═══════════════════════════════════════════════════════════════════════
# CA Validation Pass — Multi-Round + Adversarial Shuffling
# ═══════════════════════════════════════════════════════════════════════

def _shuffle_paragraphs(text: str) -> Tuple[str, bool]:
    """
    Shuffle paragraphs in a response for adversarial CA testing.

    Returns (shuffled_text, was_shuffled) — was_shuffled is False when
    the text has ≤1 paragraph and therefore can't be reordered.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) <= 1:
        # Try single-newline splitting
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paragraphs) <= 1:
        return text, False
    original_order = list(paragraphs)
    random.shuffle(paragraphs)
    # Ensure the order actually changed (re-shuffle if identical)
    if paragraphs == original_order and len(paragraphs) > 1:
        paragraphs.reverse()
    return "\n\n".join(paragraphs), True


async def stage2_ca_validation_pass(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str],
    council_models: Optional[List[str]] = None,
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    CA Validation Pass: Re-evaluate each model's OWN anonymized response
    with adversarial paragraph shuffling to detect position-sensitive
    forgetting.

    This is the "second round" of self-review, run as a lightweight
    claims-only probe (no rubric or ranking).  Combined with the
    original self-review from Stage 2, it provides:

      • Multi-round comparison — two independent self-evaluations
      • Adversarial shuffling — paragraph order randomised
      • Stability metric — |round1 − round2| detects inconsistency

    Each model evaluates ONLY its own response (in isolation, shuffled).
    Cost: 1 API call per council model (short prompt, claims-only).

    Args:
        user_query: The original user query
        stage1_results: Stage 1 individual model responses
        label_to_model: Mapping from "Response X" label to model name
        council_models: Council model list (for filtering)
        web_search_enabled: Whether to enable web search
        session_id: Kill switch session ID

    Returns:
        Dict mapping model_name → {
            "claims": {"tp": int, "fp": int, "fn": int},
            "shuffled": bool,
            "raw_text": str,
        }
    """
    if session_id and kill_switch.is_session_killed(session_id):
        return {}

    models_to_use = council_models or COUNCIL_MODELS

    # Build model → (label, response) mapping
    model_to_info: Dict[str, Dict[str, str]] = {}
    for label, model_name in label_to_model.items():
        for result in stage1_results:
            if result["model"] == model_name:
                model_to_info[model_name] = {
                    "label": label,
                    "response": result["response"],
                }
                break

    async def _probe_model(model_name: str) -> Optional[Dict[str, Any]]:
        """Send a claims-only self-review probe to one model."""
        info = model_to_info.get(model_name)
        if not info:
            return None

        shuffled_text, was_shuffled = _shuffle_paragraphs(info["response"])
        label = info["label"]

        prompt = f"""You are a pharmaceutical domain expert. Evaluate the following response to a question by classifying its major claims.

Question: {user_query}

{label}:
{shuffled_text}

Classify the major claims in this response:
  TP (True Positive)  = Correct, verifiable claim relevant to the question
  FP (False Positive) = Incorrect, misleading, or hallucinated claim
  FN (False Negative) = Important information the response FAILED to mention

Format EXACTLY:

CLAIMS {label}:
  TP: <count> — <brief summary of correct claims>
  FP: <count> — <brief summary of incorrect/hallucinated claims, or "None detected">
  FN: <count> — <brief summary of important omissions, or "None detected">"""

        try:
            result = await query_model(
                model_name,
                [{"role": "user", "content": prompt}],
                web_search_enabled=web_search_enabled,
                timeout=60.0,
            )
            if result:
                text = result.get("content", "")
                claims = parse_claim_counts(text)
                label_claims = claims.get(label, {})
                return {
                    "model": model_name,
                    "claims": label_claims,
                    "shuffled": was_shuffled,
                    "raw_text": text,
                    "usage": result.get("usage"),
                }
        except Exception as e:
            logger.warning(f"[CA Validation] Probe failed for {model_name}: {e}")
        return None

    # Fire all probes in parallel
    probes = await asyncio.gather(
        *[_probe_model(m) for m in models_to_use if m in model_to_info],
        return_exceptions=True,
    )

    results: Dict[str, Dict[str, Any]] = {}
    for probe in probes:
        if isinstance(probe, dict) and probe is not None:
            results[probe["model"]] = {
                "claims": probe["claims"],
                "shuffled": probe["shuffled"],
                "raw_text": probe.get("raw_text", ""),
                "usage": probe.get("usage"),
            }
        elif isinstance(probe, Exception):
            logger.warning(f"[CA Validation] Probe exception: {probe}")

    logger.info(
        f"[CA Validation] Completed {len(results)}/{len(model_to_info)} probes"
    )
    return results


# ═══════════════════════════════════════════════════════════════════════
# Doubting Thomas — Chairman "Detect-and-Fix" Self-Reflection Loop
# (arXiv:2602.03837 §Adversarial Reviewer; arXiv:2602.13949 §Reflection)
# ═══════════════════════════════════════════════════════════════════════

# Minimum word count to trigger the loop (skip for short/simple answers)
_DT_MIN_WORDS = 150

# The Doubting Thomas is intentionally adversarial — it assumes the
# chairman's draft is wrong until proven otherwise.  The critique is
# structured so the chairman can parse defects and produce a targeted
# fix pass without rewriting from scratch.

_DOUBTING_THOMAS_PROMPT = """You are the Doubting Thomas — a relentlessly sceptical peer reviewer
whose ONLY job is to find flaws in the Chairman's draft synthesis below.

Assume the draft is WRONG until you can verify each claim against the
original model responses.  Be harsh but fair.

══════════════════════════════════════════════════════════
ORIGINAL QUESTION:
{user_query}

══════════════════════════════════════════════════════════
STAGE 1 — ORIGINAL MODEL RESPONSES:
{stage1_text}

══════════════════════════════════════════════════════════
CHAIRMAN'S DRAFT SYNTHESIS:
{draft_response}
{gate_note}
══════════════════════════════════════════════════════════
EVALUATE the draft on EXACTLY these 5 criteria.  For each, give a
1-sentence verdict + severity (PASS / MINOR / MAJOR / CRITICAL).

1. DRIFT — Does the draft stay on-topic for the original question, or
   does it wander into tangential territory?
2. HALLUCINATION — Does the draft assert facts not present in ANY Stage 1
   response?  (A claim in the draft must trace to ≥1 model response.)
3. OMISSION — Are key claims from the top-ranked responses missing?
4. GATE VIOLATION — Does the draft incorporate content from ⛔ excluded
   (gated-out) responses?  (If no responses were gated, mark PASS.)
5. BALANCE — Does the draft over-represent one model while ignoring
   others of comparable quality?

After the 5 criteria, provide:

DEFECT_COUNT: <number of MINOR + MAJOR + CRITICAL findings>
NEEDS_FIX: YES | NO

If NEEDS_FIX is YES, add a section:
FIX_INSTRUCTIONS:
- <bullet 1: what to fix and how>
- <bullet 2: …>
(max 5 bullets)
"""

_CHAIRMAN_FIX_PROMPT = """You are the Chairman of an LLM Council.  A sceptical Doubting Thomas
reviewer has identified defects in your first draft.  Your job is to
produce a REVISED synthesis that fixes EVERY defect listed below while
preserving all correct content.

══════════════════════════════════════════════════════════
ORIGINAL QUESTION:
{user_query}

══════════════════════════════════════════════════════════
YOUR FIRST DRAFT:
{draft_response}

══════════════════════════════════════════════════════════
DOUBTING THOMAS CRITIQUE:
{critique}

══════════════════════════════════════════════════════════
RULES FOR THE REVISED SYNTHESIS:
1. Fix every MINOR / MAJOR / CRITICAL defect identified above.
2. Do NOT introduce new information beyond what is in the original
   model responses.
3. Keep the same overall structure / headings unless the critique
   specifically flags structure issues.
4. Preserve all correct content from the first draft verbatim where
   possible — only change what the critique requires.
5. If the critique says the draft is fine (NEEDS_FIX: NO), reproduce
   it unchanged.

Provide the FULL revised synthesis now:"""


async def doubting_thomas_review(
    user_query: str,
    draft_response: str,
    stage1_results: List[Dict[str, Any]],
    relevancy_gate: Optional[Dict[str, Dict[str, Any]]] = None,
    chairman_model: Optional[str] = None,
    reviewer_model: Optional[str] = None,
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Doubting Thomas detect-and-fix loop (arXiv:2602.03837, §Adversarial
    Reviewer; arXiv:2602.13949, §Experience-Reflection-Consolidation).

    1. A sceptical reviewer critiques the chairman's draft for drift,
       hallucination, omission, gate violations, and balance.
    2. If NEEDS_FIX == YES, the chairman receives the critique and
       produces a revised synthesis.

    The loop runs AT MOST once (detect → fix) to bound latency.

    Args:
        user_query:       The original user question.
        draft_response:   Chairman's first-pass synthesis.
        stage1_results:   Stage 1 individual model responses.
        relevancy_gate:   Optional relevancy gate data (for gate-violation check).
        chairman_model:   Model ID for the fix pass (defaults to CHAIRMAN_MODEL).
        reviewer_model:   Model ID for the critique (defaults to chairman_model).
        web_search_enabled: Enable web search.
        session_id:       Kill-switch session ID.

    Returns:
        Dict with keys:
            critique       — raw Doubting Thomas text
            defect_count   — int parsed from critique
            needs_fix      — bool
            revised_response — str (original if no fix needed)
            fix_applied    — bool
            usage          — dict of token usage (critique + fix)
    """
    chairman_to_use = chairman_model or CHAIRMAN_MODEL
    reviewer_to_use = reviewer_model or chairman_to_use

    # Skip for short answers (unlikely to have systemic flaws)
    word_count = len(draft_response.split())
    if word_count < _DT_MIN_WORDS:
        logger.info(
            f"[Doubting Thomas] Skipped — draft only {word_count} words "
            f"(threshold {_DT_MIN_WORDS})"
        )
        return {
            "critique": None,
            "defect_count": 0,
            "needs_fix": False,
            "revised_response": draft_response,
            "fix_applied": False,
            "usage": {},
        }

    # Kill switch check
    if session_id and kill_switch.is_session_killed(session_id):
        return {
            "critique": None,
            "defect_count": 0,
            "needs_fix": False,
            "revised_response": draft_response,
            "fix_applied": False,
            "usage": {},
        }

    t0 = time.perf_counter()

    # Build Stage 1 text for the reviewer to cross-reference
    stage1_text = "\n\n".join([
        f"Model: {r['model']}\nResponse: {r['response']}"
        for r in stage1_results
    ])

    # Note about gated-out responses
    gate_note = ""
    if relevancy_gate:
        excluded = [lbl for lbl, g in relevancy_gate.items() if g.get("gated_out")]
        if excluded:
            gate_note = (
                "\n\n⛔ GATED-OUT RESPONSES (should NOT appear in draft): "
                + ", ".join(excluded)
            )

    # ── Step 1: Critique ──────────────────────────────────────────────
    critique_prompt = _DOUBTING_THOMAS_PROMPT.format(
        user_query=user_query,
        stage1_text=stage1_text[:12000],  # cap to avoid token overflow
        draft_response=draft_response,
        gate_note=gate_note,
    )
    critique_messages = [{"role": "user", "content": critique_prompt}]

    critique_result = await query_model(
        reviewer_to_use,
        critique_messages,
        timeout=90.0,
        web_search_enabled=False,  # no web search for internal review
        session_id=session_id,
    )

    if not critique_result:
        logger.warning("[Doubting Thomas] Critique call failed — returning draft unchanged")
        return {
            "critique": None,
            "defect_count": 0,
            "needs_fix": False,
            "revised_response": draft_response,
            "fix_applied": False,
            "usage": {},
        }

    critique_text = critique_result.get("content", "")
    critique_usage = critique_result.get("usage", {})

    # ── Parse critique ────────────────────────────────────────────────
    defect_match = re.search(r"DEFECT_COUNT:\s*(\d+)", critique_text)
    defect_count = int(defect_match.group(1)) if defect_match else 0

    needs_fix_match = re.search(r"NEEDS_FIX:\s*(YES|NO)", critique_text, re.IGNORECASE)
    needs_fix = (
        needs_fix_match.group(1).upper() == "YES" if needs_fix_match else defect_count > 0
    )

    logger.info(
        f"[Doubting Thomas] Critique complete — "
        f"defects={defect_count}, needs_fix={needs_fix}, "
        f"elapsed={time.perf_counter() - t0:.1f}s"
    )

    if not needs_fix:
        return {
            "critique": critique_text,
            "defect_count": defect_count,
            "needs_fix": False,
            "revised_response": draft_response,
            "fix_applied": False,
            "usage": critique_usage,
        }

    # ── Step 2: Chairman Fix Pass ─────────────────────────────────────
    if session_id and kill_switch.is_session_killed(session_id):
        return {
            "critique": critique_text,
            "defect_count": defect_count,
            "needs_fix": True,
            "revised_response": draft_response,
            "fix_applied": False,
            "usage": critique_usage,
        }

    fix_prompt = _CHAIRMAN_FIX_PROMPT.format(
        user_query=user_query,
        draft_response=draft_response,
        critique=critique_text,
    )
    fix_messages = [{"role": "user", "content": fix_prompt}]

    fix_result = await query_model(
        chairman_to_use,
        fix_messages,
        timeout=120.0,
        web_search_enabled=web_search_enabled,
        session_id=session_id,
    )

    if not fix_result:
        logger.warning("[Doubting Thomas] Fix call failed — returning draft unchanged")
        return {
            "critique": critique_text,
            "defect_count": defect_count,
            "needs_fix": True,
            "revised_response": draft_response,
            "fix_applied": False,
            "usage": critique_usage,
        }

    revised = fix_result.get("content", draft_response)
    fix_usage = fix_result.get("usage", {})

    # Merge usage
    total_usage = {
        "prompt_tokens": critique_usage.get("prompt_tokens", 0) + fix_usage.get("prompt_tokens", 0),
        "completion_tokens": critique_usage.get("completion_tokens", 0) + fix_usage.get("completion_tokens", 0),
        "total_tokens": critique_usage.get("total_tokens", 0) + fix_usage.get("total_tokens", 0),
    }

    elapsed = time.perf_counter() - t0
    logger.info(
        f"[Doubting Thomas] Fix applied — {defect_count} defect(s) addressed, "
        f"total elapsed={elapsed:.1f}s"
    )

    return {
        "critique": critique_text,
        "defect_count": defect_count,
        "needs_fix": True,
        "revised_response": revised,
        "fix_applied": True,
        "usage": total_usage,
    }


async def run_full_council(
    user_query: str,
    council_models: Optional[List[str]] = None,
    chairman_model: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process with self-healing.

    Args:
        user_query: The user's question
        council_models: Optional list of model IDs to use as council (defaults to COUNCIL_MODELS)
        chairman_model: Optional chairman model ID (defaults to CHAIRMAN_MODEL)
        session_id: Kill switch session ID

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses
    stage1_results = await stage1_collect_responses(
        user_query, council_models, session_id=session_id
    )

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(
        user_query, stage1_results, council_models, session_id=session_id
    )

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        chairman_model,
        session_id=session_id,
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "council_models": council_models or COUNCIL_MODELS,
        "chairman_model": chairman_model or CHAIRMAN_MODEL
    }

    return stage1_results, stage2_results, stage3_result, metadata
