"""3-stage LLM Council orchestration with self-healing resilience."""

import logging
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

    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    ranking_prompt = f"""You are a pharmaceutical domain expert evaluating different responses to the following question:
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

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council models in parallel (with resilience)
    responses = await query_models_parallel(
        models_to_use, messages,
        web_search_enabled=web_search_enabled,
        session_id=session_id,
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


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    chairman_model: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
    evidence_context: str = "",
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

    chairman_prompt = f"""You are the Chairman of an LLM Council operating in a pharmaceutical / life-sciences context where accuracy is paramount and missing critical information (FN) is more dangerous than including minor inaccuracies (FP).
{context_note}
Original Question: {user_query}

STAGE 1 — Individual Responses:
{stage1_text}

STAGE 2 — Peer Rankings:
{stage2_text}

STAGE 2 — Rubric Evaluation & Claim Analysis:
{rubric_section}

{evidence_context}

Your task as Chairman is to synthesize the above into a single, comprehensive, accurate answer. Guidelines:
1. Put patient-safety and factual accuracy FIRST — prefer responses with high Faithfulness scores and low FN counts.
2. Weight reviewer consensus: if multiple reviewers agree a response is strong on Relevancy and Context Recall, lean on that response.
3. Incorporate unique correct insights from lower-ranked responses; do not discard valuable information just because the source ranked lower.
4. Flag any claims where reviewers disagreed on TP/FP classification — note the uncertainty explicitly.
5. Structure your answer clearly with appropriate headings when the subject matter warrants it.
6. When evidence citations are provided above, reference them inline using their tags (e.g. [FDA-L1], [CT-2], [PM-3], [SS-1], [CR-1], [EPMC-1], [WEB-1], [AX-1], [PAT-1], [WIKI-1], [ORC-1]) and include a REFERENCES section at the end with clickable URLs.
7. SCIENTIFIC INTELLIGENCE FROM DIVERSE SOURCES: The evidence may include data from a broad, diverse set of sources — not just pharma APIs but also scientific preprints (arXiv), patents (Google Patents), encyclopaedic context (Wikipedia), and researcher profiles (ORCID). When processing these sources:
   - Cross-reference web-sourced findings with the council members' responses to validate or refute claims.
   - Use citation counts, journal impact, and patent filing dates to weight the reliability of evidence.
   - Highlight any recent findings (last 2 years) from web sources that update or supersede older council member knowledge.
   - Extract mechanistic insights, pharmacokinetic parameters, clinical endpoints, and safety signals from abstracts and integrate them into the synthesis.
   - When web evidence contradicts a council member's claim, clearly flag the discrepancy and explain which source is more authoritative.
   - For arXiv preprints, note they are not peer-reviewed and flag confidence level accordingly.
   - For patents, extract relevant claims and invention descriptions that pertain to the query.
   - For Wikipedia, use as context and background — never as a primary scientific source.
   - For ORCID profiles, identify key researchers and their publication records relevant to the topic.
8. RICH SCIENTIFIC OUTPUT (the frontend renders full Markdown):
   - Use Markdown TABLES (pipe syntax) for comparative data such as drug properties, dosing, trial endpoints, adverse-event rates, or any structured comparison.
   - **MOLECULAR STRUCTURES — ALWAYS use SMILES code blocks.** The frontend natively renders SMILES as interactive 2D/3D molecular visualizations. NEVER use external image URLs (![image](url)) for chemical structures — those break. Instead ALWAYS write:
     ```smiles
     CC(=O)Oc1ccccc1C(=O)O
     ```
     Every time you mention a specific molecule, drug, or compound by name, ALSO include its SMILES in a ```smiles code block so the user gets an interactive 3D structure.
   - Use ordered and unordered LISTS for step-by-step protocols, criteria, mechanisms of action, etc.
   - Use subscript (<sub>x</sub>) and superscript (<sup>y</sup>) HTML tags for chemical formulas like H<sub>2</sub>O or IC<sub>50</sub>.
   - When quantitative data is involved, use LaTeX math notation: inline $K_d = 5.2 \\text{{ nM}}$ or display blocks $$AUC = \\int_0^T C(t)\\,dt$$ for pharmacokinetic equations.
   - For non-molecular images, you may include image links from public sources (e.g. RCSB PDB) when a figure would aid understanding: ![Figure caption](https://url).
9. INFOGRAPHIC DATA: After your full answer, generate a structured JSON block wrapped in ```infographic markers that the frontend will render as a visual infographic summary. The JSON must follow this schema:
   ```infographic
   {{
     "title": "Short infographic title summarising the answer",
     "type": "summary",
     "key_metrics": [
       {{"label": "Metric name", "value": "Metric value", "icon": "emoji"}},
       ...max 6 metrics
     ],
     "comparison": {{
       "headers": ["Category", "Option A", "Option B"],
       "rows": [["Row label", "Value A", "Value B"], ...]
     }},
     "process_steps": [
       {{"step": 1, "title": "Step title", "description": "Brief description"}},
       ...max 6 steps
     ],
     "highlights": [
       {{"text": "Key finding or takeaway", "type": "success|warning|info|danger"}},
       ...max 4 highlights
     ]
   }}
   ```
   RULES for infographic data:
   - Include ONLY fields that are relevant to the answer. Omit empty arrays or objects.
   - key_metrics: Extract the most important quantitative facts (e.g. "IC50: 5.2 nM", "Phase: III", "Approval: 2024").
   - comparison: Only include if the answer compares two or more items (drugs, treatments, trials).
   - process_steps: Only include if the answer describes a mechanism, pathway, protocol, or pipeline.
   - highlights: Always include 2-4 key takeaways from the answer.
   - Keep values concise (under 30 chars each).
10. VALUE PROPOSITION MODE: If the user's question asks for a value proposition, competitive positioning, messaging framework, or brand strategy for a pharmaceutical product, structure your answer using the following template:
   - **TITLE**: Product name and therapeutic area (e.g. "Acoramidis — ATTR Cardiomyopathy Value Proposition")
   - **CHALLENGE**: Describe the current unmet medical need, disease burden, limitations of existing treatments, and why patients/HCPs need a new solution. Use evidence from council members and citations.
   - **SOLUTION**: Articulate the product's mechanism of action, clinical differentiation, key efficacy data (trial names, endpoints, hazard ratios), and what makes it unique vs. standard of care.
   - **OUTCOME**: Present measurable clinical benefits (survival, hospitalization reduction, QoL), safety profile, and the transformative impact for patients and healthcare systems.
   After the full VP text, generate the infographic JSON using type "value_proposition" instead of "summary":
   ```infographic
   {{
     "title": "Product Name — Value Proposition",
     "type": "value_proposition",
     "sections": [
       {{
         "section_type": "challenge",
         "title": "The Challenge",
         "content": "2-3 sentence summary of the unmet need",
         "bullets": ["Key challenge point 1", "Key challenge point 2", "Key challenge point 3"]
       }},
       {{
         "section_type": "solution",
         "title": "The Solution",
         "content": "2-3 sentence summary of the product approach",
         "bullets": ["Differentiation point 1", "Efficacy data point", "Mechanism of action"]
       }},
       {{
         "section_type": "outcome",
         "title": "The Outcome",
         "content": "2-3 sentence summary of clinical impact",
         "bullets": ["Clinical benefit 1", "Safety profile", "Patient impact"]
       }}
     ],
     "key_metrics": [
       {{"label": "Metric", "value": "Value", "icon": "emoji"}},
       ...max 6 metrics
     ],
     "highlights": [
       {{"text": "Key takeaway", "type": "success|warning|info|danger"}},
       ...max 4 highlights
     ]
   }}
   ```
{f'11. Consider the context from the previous conversation.' if context else ''}

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model (with retries from openrouter layer)
    response = await query_model(
        chairman_to_use, messages,
        web_search_enabled=web_search_enabled,
        session_id=session_id,
    )

    if response is not None:
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
