"""OpenRouter API client for making LLM requests — with self-healing resilience."""

import httpx
import asyncio
import logging
from typing import List, Dict, Any, Optional
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL, is_google_model, strip_google_prefix
from .resilience import (
    kill_switch,
    circuit_breaker,
    retry_with_backoff,
    resolve_fallback,
    health_monitor,
    KillSwitchError,
)
from .security import redact_pii

logger = logging.getLogger("llm_council.openrouter")


def _sanitize_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Scrub PII from message contents once (avoid redundant per-model calls)."""
    return [
        {
            **msg,
            "content": redact_pii(msg["content"]) if isinstance(msg.get("content"), str) else msg.get("content"),
        }
        for msg in messages
    ]


# ── Persistent HTTP connection pool ──────────────────────────────────
# Reuse TCP connections + TLS sessions across all API calls within a
# worker process.  Avoids 200-500ms TLS handshake overhead per request.
# httpx.AsyncClient is safe for concurrent use via asyncio.gather().
_shared_client: Optional[httpx.AsyncClient] = None


def _get_shared_client() -> httpx.AsyncClient:
    """Lazy-init a module-level httpx.AsyncClient with connection pooling."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            verify=False,
            limits=httpx.Limits(
                max_connections=40,
                max_keepalive_connections=20,
                keepalive_expiry=120,
            ),
        )
    return _shared_client


async def close_shared_client():
    """Gracefully close the shared client (call on app shutdown)."""
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None


async def _raw_query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    web_search_enabled: bool = False,
    _pre_sanitized: bool = False,
) -> Dict[str, Any]:
    """
    Low-level HTTP call to the API.  Raises on failure (no swallowing).
    Routes google/* models to Google AI Studio, everything else to Bayer myGenAssist.
    """
    # ── Google AI Studio routing ──
    if is_google_model(model):
        from .google_provider import query_google_model
        raw_model = strip_google_prefix(model)
        return await query_google_model(raw_model, messages, timeout, web_search_enabled)

    # ── Bayer myGenAssist (default) ──
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    sanitized_messages = messages if _pre_sanitized else _sanitize_messages(messages)

    payload = {
        "model": model,
        "messages": sanitized_messages,
    }

    # Enable multi-modal (text + image) output for Gemini models
    if model.startswith("gemini"):
        payload["modalities"] = ["text", "image"]

    if web_search_enabled:
        payload["plugins"] = ["web_search_google"]

    client = _get_shared_client()
    response = await client.post(
        OPENROUTER_API_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
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
    _pre_sanitized: bool = False,
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
        _pre_sanitized: If True, skip PII redaction (caller already sanitized)

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

    sanitized = messages if _pre_sanitized else _sanitize_messages(messages)

    try:
        result = await retry_with_backoff(
            _raw_query_model,
            model,
            sanitized,
            timeout,
            web_search_enabled,
            True,  # _pre_sanitized — always True here, we sanitized above
            max_retries=max_retries,
            base_delay=0.5,
            max_delay=3.0,
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
    # Sanitize PII once for the entire batch instead of N times per model
    sanitized = _sanitize_messages(messages)

    tasks = [
        query_model(
            model, sanitized,
            web_search_enabled=web_search_enabled,
            session_id=session_id,
            _pre_sanitized=True,
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
