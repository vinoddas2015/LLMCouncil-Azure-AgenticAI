"""OpenRouter API client for making LLM requests — with self-healing resilience."""

import httpx
import asyncio
import logging
from typing import List, Dict, Any, Optional
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL
from .resilience import (
    kill_switch,
    circuit_breaker,
    retry_with_backoff,
    resolve_fallback,
    health_monitor,
    KillSwitchError,
)

logger = logging.getLogger("llm_council.openrouter")


async def _raw_query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    web_search_enabled: bool = False,
) -> Dict[str, Any]:
    """
    Low-level HTTP call to the API.  Raises on failure (no swallowing).
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    # Enable multi-modal (text + image) output for Gemini models
    if model.startswith("gemini"):
        payload["modalities"] = ["text", "image"]

    if web_search_enabled:
        payload["plugins"] = ["web_search_google"]

    # Disable SSL verification for corporate environments (Bayer internal)
    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        response = await client.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

        data = response.json()
        message = data["choices"][0]["message"]

        # Extract token usage from API response
        usage = data.get("usage", {})

        # Handle multi-modal responses (Gemini may return text + image parts)
        raw_content = message.get("content")
        if isinstance(raw_content, list):
            # Multi-part response: assemble text and inline base64 images
            parts = []
            for part in raw_content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url:
                            parts.append(f"\n\n![Generated Image]({url})\n\n")
                elif isinstance(part, str):
                    parts.append(part)
            content = "".join(parts)
        else:
            content = raw_content

        return {
            "content": content,
            "reasoning_details": message.get("reasoning_details"),
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            },
        }


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
    max_retries: int = 2,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model with self-healing resilience:
      1. Circuit breaker check — skip if model circuit is OPEN
      2. Retry with exponential backoff (respects kill switch)
      3. Record success/failure in circuit breaker

    Args:
        model: Model identifier
        messages: Chat messages
        timeout: Request timeout in seconds
        web_search_enabled: Enable web search plugins
        session_id: Kill-switch session ID (None = no kill switch check)
        max_retries: Number of retry attempts

    Returns:
        Response dict or None if all attempts failed
    """
    # Kill switch check
    if session_id and kill_switch.is_session_killed(session_id):
        logger.warning(f"[query_model] Session {session_id} killed — skipping {model}")
        return None
    if kill_switch.is_halted:
        logger.warning(f"[query_model] Global halt active — skipping {model}")
        return None

    # Circuit breaker check
    if not circuit_breaker.can_attempt(model):
        logger.warning(f"[query_model] Circuit OPEN for {model} — skipping")
        return None

    try:
        result = await retry_with_backoff(
            _raw_query_model,
            model,
            messages,
            timeout,
            web_search_enabled,
            max_retries=max_retries,
            base_delay=1.5,
            max_delay=8.0,
            session_id=session_id,
        )

        if result is not None:
            circuit_breaker.record_success(model)
            return result
        else:
            circuit_breaker.record_failure(model, "All retries exhausted (returned None)")
            health_monitor.log_healing_action("retries_exhausted", {"model": model})
            return None

    except KillSwitchError:
        logger.info(f"[query_model] Kill switch activated during {model} query")
        return None
    except Exception as e:
        circuit_breaker.record_failure(model, str(e))
        logger.error(f"[query_model] {model} failed: {e}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    web_search_enabled: bool = False,
    session_id: Optional[str] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel with self-healing:
      - Skips models whose circuit is OPEN
      - Each model retries independently
      - Respects kill switch per-request

    Args:
        models: List of model identifiers
        messages: Chat messages
        web_search_enabled: Enable web search plugins
        session_id: Kill-switch session ID

    Returns:
        Dict mapping model → response (or None)
    """
    tasks = [
        query_model(
            model, messages,
            web_search_enabled=web_search_enabled,
            session_id=session_id,
        )
        for model in models
    ]

    responses = await asyncio.gather(*tasks, return_exceptions=True)

    result = {}
    for model, response in zip(models, responses):
        if isinstance(response, Exception):
            logger.error(f"[parallel] {model} raised: {response}")
            circuit_breaker.record_failure(model, str(response))
            result[model] = None
        else:
            result[model] = response

    return result
