"""Google AI Studio provider — Gemini models via generativelanguage.googleapis.com."""

import httpx
import logging
import os
from typing import List, Dict, Any, Optional

from .config import GOOGLE_API_KEY
from .security import redact_pii

logger = logging.getLogger("llm_council.google_provider")

GOOGLE_AI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _openai_to_google_messages(messages: List[Dict[str, str]]) -> List[Dict]:
    """
    Convert OpenAI-style messages to Google Generative AI contents format.

    OpenAI: [{"role": "system"|"user"|"assistant", "content": "..."}]
    Google: [{"role": "user"|"model", "parts": [{"text": "..."}]}]

    System messages are prepended to the first user message.
    """
    contents = []
    system_text = ""

    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")

        if role == "system":
            system_text += text + "\n\n"
            continue

        google_role = "model" if role == "assistant" else "user"

        # Prepend accumulated system text to the first user message
        if system_text and google_role == "user":
            text = system_text + text
            system_text = ""

        contents.append({
            "role": google_role,
            "parts": [{"text": text}],
        })

    # Edge case: system-only messages → wrap as user
    if system_text and not contents:
        contents.append({"role": "user", "parts": [{"text": system_text.strip()}]})

    return contents


async def query_google_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    web_search_enabled: bool = False,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Call a Google AI Studio model.  Returns the same dict structure as
    openrouter._raw_query_model(): {content, reasoning_details, usage}.

    Args:
        model: Google model ID WITHOUT prefix (e.g. "gemini-2.5-pro")
        messages: OpenAI-style messages list
        timeout: HTTP timeout in seconds
        web_search_enabled: Unused (Google manages grounding separately)

    Raises:
        httpx.HTTPStatusError on 4xx/5xx
        ValueError if GOOGLE_API_KEY is not set
    """
    if not GOOGLE_API_KEY:
        raise ValueError(
            "GOOGLE_API_KEY is not set. "
            "Get one at https://aistudio.google.com/apikey and add it to .env"
        )

    # ── PII redaction ──
    sanitized = [
        {
            **m,
            "content": redact_pii(m["content"]) if isinstance(m.get("content"), str) else m.get("content"),
        }
        for m in messages
    ]

    contents = _openai_to_google_messages(sanitized)

    url = f"{GOOGLE_AI_BASE}/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": GOOGLE_API_KEY,
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {"contents": contents}

    # Speed Mode: cap response length
    if max_tokens is not None:
        payload["generationConfig"] = {"maxOutputTokens": max_tokens}

    # Optional: enable Google Search grounding
    if web_search_enabled:
        payload["tools"] = [{"google_search": {}}]

    # Corporate environment: disable SSL verification
    async with httpx.AsyncClient(http2=True, timeout=timeout, verify=False) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

        data = response.json()

        # Extract text from candidates
        candidates = data.get("candidates", [])
        if not candidates:
            # Log blockReason if present (e.g. SAFETY, PROHIBITED_CONTENT)
            block_reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
            safety_ratings = data.get("promptFeedback", {}).get("safetyRatings", [])
            logger.error(
                f"[Google] No candidates for {model} — "
                f"blockReason={block_reason}, safetyRatings={safety_ratings}"
            )
            raise ValueError(
                f"Google API returned no candidates for {model} "
                f"(blockReason={block_reason})"
            )

        # Check finishReason — may be SAFETY, RECITATION, MAX_TOKENS, etc.
        finish_reason = candidates[0].get("finishReason", "STOP")
        if finish_reason in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST"):
            safety_ratings = candidates[0].get("safetyRatings", [])
            logger.warning(
                f"[Google] {model} response blocked — "
                f"finishReason={finish_reason}, safetyRatings={safety_ratings}"
            )
            raise ValueError(
                f"Google API blocked response for {model} "
                f"(finishReason={finish_reason})"
            )

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        content = "".join(text_parts)

        # Guard against empty content (model returned candidates but no text)
        if not content.strip():
            logger.warning(
                f"[Google] {model} returned empty content — "
                f"finishReason={finish_reason}, parts={len(parts)}"
            )
            raise ValueError(f"Google API returned empty content for {model}")

        # Extract usage metadata
        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)

        # Extract thinking/reasoning if present (Gemini 2.5 models)
        reasoning = None
        thought_parts = [p.get("thought", "") for p in parts if "thought" in p]
        if thought_parts:
            reasoning = "".join(thought_parts)

        return {
            "content": content,
            "reasoning_details": reasoning,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }


async def list_google_models() -> List[Dict[str, str]]:
    """
    List available models from Google AI Studio.
    Returns list of {"id": ..., "name": ..., "description": ...}.
    """
    if not GOOGLE_API_KEY:
        return []

    url = f"{GOOGLE_AI_BASE}/models"
    headers = {"x-goog-api-key": GOOGLE_API_KEY}

    try:
        async with httpx.AsyncClient(http2=True, timeout=15, verify=False) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

            data = response.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")  # e.g. "models/gemini-2.5-pro"
                model_id = name.replace("models/", "")
                display = m.get("displayName", model_id)
                desc = m.get("description", "")
                # Only include generateContent-capable models
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    models.append({
                        "id": f"google/{model_id}",
                        "name": f"[Google] {display}",
                        "description": desc[:120],
                        "provider": "google",
                    })
            return models

    except Exception as e:
        logger.error(f"Failed to list Google models: {e}")
        return []
