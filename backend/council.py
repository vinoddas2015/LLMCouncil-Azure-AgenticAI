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

    ranking_prompt = f"""You are evaluating different responses to the following question:
{context_note}
Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

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
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed,
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

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.
{context_note}
Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement
{f'- The context from the previous conversation' if context else ''}

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
