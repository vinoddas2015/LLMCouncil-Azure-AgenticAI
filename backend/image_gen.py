"""Multi-provider image generation engine with quality validation.

Providers (priority order):
1. Google Imagen 4.0 Fast   — highest quality, ~10s per image  (:predict endpoint)
2. Gemini Flash Image       — fast fallback, generates via chat completions

Quality features:
- Parallel async generation for speed
- Per-image quality validation using Gemini vision model
- Automatic retry with refined prompt on low-quality images
- Graceful fallback: Imagen → Gemini Flash → None
"""

import asyncio
import base64
import io
import hashlib
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import httpx

from .config import GOOGLE_API_KEY

logger = logging.getLogger(__name__)

# ── Provider config ──────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_DALLE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT", "dalle3")

IMAGEN_MODEL = "imagen-4.0-fast-generate-001"
GEMINI_IMAGE_MODEL = "gemini-2.0-flash-exp-image-generation"

# Quality validation model (fast vision model)
QUALITY_VALIDATOR_MODEL = "gemini-2.5-flash"

# ── In-memory image cache (per-process) ──────────────────────────────────
_image_cache: Dict[str, bytes] = {}
_MAX_CACHE_SIZE = 50  # max cached images


def _cache_key(prompt: str, aspect: str) -> str:
    return hashlib.md5(f"{prompt}:{aspect}".encode()).hexdigest()


# ── Provider: Google Imagen 4.0 Fast ─────────────────────────────────────
async def _generate_imagen(prompt: str, aspect_ratio: str = "16:9") -> Optional[bytes]:
    """Generate image via Google Imagen 4.0 Fast (:predict endpoint)."""
    if not GOOGLE_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGEN_MODEL}:predict"
    headers = {"x-goog-api-key": GOOGLE_API_KEY, "Content-Type": "application/json"}
    payload = {
        "instances": [{"prompt": prompt[:500]}],
        "parameters": {"sampleCount": 1, "aspectRatio": aspect_ratio},
    }

    try:
        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            for attempt in range(3):
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", 5 * (attempt + 1)))
                    logger.info("Imagen 429 — retrying in %ds (attempt %d/3)", retry_after, attempt + 1)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                data = resp.json()
                predictions = data.get("predictions", [])
                if not predictions:
                    return None
                b64 = predictions[0].get("bytesBase64Encoded") or predictions[0].get("image")
                if not b64:
                    return None
                return base64.b64decode(b64)
            return None  # exhausted retries
    except Exception as e:
        logger.warning("Imagen generation failed: %s", e)
        return None


# ── Provider: Gemini Flash Image Generation ──────────────────────────────
async def _generate_gemini_flash(prompt: str) -> Optional[bytes]:
    """Generate image via Gemini 2.0 Flash Exp Image Generation (generateContent)."""
    if not GOOGLE_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
    headers = {"x-goog-api-key": GOOGLE_API_KEY, "Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": f"Generate a professional illustration: {prompt[:400]}"}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    try:
        async with httpx.AsyncClient(timeout=60, verify=False) as client:
            for attempt in range(3):
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", 5 * (attempt + 1)))
                    logger.info("Gemini Flash 429 — retrying in %ds (attempt %d/3)", retry_after, attempt + 1)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return None
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    inline = part.get("inlineData", {})
                    if inline.get("mimeType", "").startswith("image/"):
                        return base64.b64decode(inline["data"])
                return None
            return None  # exhausted retries
    except Exception as e:
        logger.warning("Gemini Flash image generation failed: %s", e)
        return None


# ── Provider: Azure OpenAI DALL-E (when available) ───────────────────────
async def _generate_azure_dalle(prompt: str, size: str = "1792x1024") -> Optional[bytes]:
    """Generate image via Azure OpenAI DALL-E deployment."""
    if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_KEY:
        return None

    url = f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/{AZURE_OPENAI_DALLE_DEPLOYMENT}/images/generations?api-version=2024-02-01"
    headers = {"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"}
    payload = {
        "prompt": prompt[:1000],
        "n": 1,
        "size": size,
        "quality": "hd",
        "response_format": "b64_json",
    }

    try:
        async with httpx.AsyncClient(timeout=90, verify=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            images = data.get("data", [])
            if not images:
                return None
            b64 = images[0].get("b64_json")
            if not b64:
                return None
            return base64.b64decode(b64)
    except Exception as e:
        logger.warning("Azure DALL-E generation failed: %s", e)
        return None


# ── Image Quality Validator ──────────────────────────────────────────────
async def validate_image_quality(
    image_bytes: bytes,
    expected_context: str,
) -> Tuple[float, str]:
    """Use a vision model to score image quality and relevance.
    
    Returns (score: 0.0-1.0, feedback: str).
    Score > 0.6 = acceptable, > 0.8 = good.
    """
    if not GOOGLE_API_KEY:
        return (0.7, "No API key for quality validation")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{QUALITY_VALIDATOR_MODEL}:generateContent"
    headers = {"x-goog-api-key": GOOGLE_API_KEY, "Content-Type": "application/json"}
    b64_image = base64.b64encode(image_bytes).decode()
    
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": "image/png", "data": b64_image}},
                {"text": (
                    f"Score this image for a professional pharma/science slideshow about: '{expected_context[:200]}'\n\n"
                    "Rate on these criteria (each 0-10):\n"
                    "1. Visual clarity — is the image sharp, well-composed, not blurry?\n"
                    "2. Relevance — does it relate to the topic?\n"
                    "3. Professionalism — suitable for corporate/pharma presentation?\n"
                    "4. Information value — does it add visual understanding?\n\n"
                    "Reply ONLY with this exact format:\n"
                    "CLARITY: <score>\nRELEVANCE: <score>\nPROFESSIONAL: <score>\nINFO_VALUE: <score>\n"
                    "OVERALL: <average of 4 scores>\nFEEDBACK: <one sentence>"
                )},
            ]
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
    }

    try:
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

            # Parse OVERALL score
            overall_match = re.search(r'OVERALL:\s*(\d+(?:\.\d+)?)', text)
            overall = float(overall_match.group(1)) / 10.0 if overall_match else 0.7

            feedback_match = re.search(r'FEEDBACK:\s*(.+)', text)
            feedback = feedback_match.group(1).strip() if feedback_match else "Quality validation complete"

            return (min(1.0, max(0.0, overall)), feedback)
    except Exception as e:
        logger.warning("Image quality validation failed: %s", e)
        return (0.7, f"Validation skipped: {e}")


# ── Main generation function ─────────────────────────────────────────────
async def generate_image(
    prompt: str,
    aspect_ratio: str = "16:9",
    validate: bool = False,
    context_for_validation: str = "",
) -> Optional[bytes]:
    """Generate an image with multi-provider fallback.
    
    Priority: Azure DALL-E → Google Imagen 4.0 → Gemini Flash
    
    If validate=True, runs quality check and retries with refined prompt on low scores.
    """
    key = _cache_key(prompt, aspect_ratio)
    if key in _image_cache:
        return _image_cache[key]

    image = None

    # Try Azure DALL-E first (if configured)
    if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY:
        size = "1792x1024" if aspect_ratio == "16:9" else "1024x1024"
        image = await _generate_azure_dalle(prompt, size)
        if image:
            logger.info("Image generated via Azure DALL-E (%d bytes)", len(image))

    # Fallback: Google Imagen 4.0 Fast
    if not image:
        image = await _generate_imagen(prompt, aspect_ratio)
        if image:
            logger.info("Image generated via Imagen 4.0 Fast (%d bytes)", len(image))

    # Fallback: Gemini Flash
    if not image:
        image = await _generate_gemini_flash(prompt)
        if image:
            logger.info("Image generated via Gemini Flash (%d bytes)", len(image))

    if not image:
        return None

    # Optional quality validation
    if validate and context_for_validation:
        score, feedback = await validate_image_quality(image, context_for_validation)
        logger.info("Image quality score: %.2f — %s", score, feedback)
        
        if score < 0.5:
            # Low quality — retry with refined prompt
            refined = f"High quality, sharp, professional corporate illustration. {prompt}. Clean composition, no text overlays."
            retry_image = await _generate_imagen(refined, aspect_ratio)
            if retry_image:
                retry_score, _ = await validate_image_quality(retry_image, context_for_validation)
                if retry_score > score:
                    image = retry_image
                    logger.info("Retry improved quality: %.2f → %.2f", score, retry_score)

    # Cache result
    if len(_image_cache) >= _MAX_CACHE_SIZE:
        # Evict oldest
        oldest = next(iter(_image_cache))
        del _image_cache[oldest]
    _image_cache[key] = image

    return image


# ── Batch parallel generation ────────────────────────────────────────────
async def generate_images_parallel(
    prompts: Dict[str, str],
    aspect_ratio: str = "16:9",
    max_concurrent: int = 4,
    validate: bool = False,
    context: str = "",
) -> Dict[str, Optional[bytes]]:
    """Generate multiple images in parallel with concurrency limit.
    
    Args:
        prompts: {key: prompt_text} mapping
        aspect_ratio: target aspect ratio
        max_concurrent: max parallel API calls
        validate: run quality validation
        context: base context for quality validation
    
    Returns: {key: image_bytes_or_None}
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: Dict[str, Optional[bytes]] = {}

    async def _gen(key: str, prompt: str):
        async with semaphore:
            img = await generate_image(prompt, aspect_ratio, validate, context)
            results[key] = img

    tasks = [_gen(k, p) for k, p in prompts.items()]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # Fill in any missing keys (from exceptions)
    for k in prompts:
        if k not in results:
            results[k] = None

    return results


# ── Prompt builder for slides ────────────────────────────────────────────
def build_slide_prompt(
    model_name: str,
    content_snippet: str,
    stage: int,
    user_question: str = "",
) -> str:
    """Build a contextual image prompt for a specific slide.
    
    Creates a prompt that captures the essence of the model's response content,
    suitable for a professional pharma presentation backdrop.
    """
    # Extract key topics from content (first 150 chars as seed)
    snippet = content_snippet[:150].strip()
    
    stage_context = {
        1: "scientific research, data analysis, model brainstorm",
        2: "peer review, evaluation board, ranking assessment",
        3: "executive synthesis, final decision, strategic summary",
    }
    
    base = stage_context.get(stage, "scientific illustration")
    
    prompt = (
        f"Professional pharmaceutical illustration for corporate presentation. "
        f"{base}. "
        f"Topic context: {user_question[:100]}. "
        f"Content focus: {snippet}. "
        f"Style: clean, modern, Bayer corporate, scientific, data visualization. "
        f"No text in image. High quality, sharp."
    )
    
    return prompt[:500]


def build_section_prompt(stage: int, user_question: str) -> str:
    """Build a hero image prompt for a stage section slide."""
    prompts = {
        1: f"Wide cinematic illustration: scientific brainstorm session, multiple AI models analyzing data, pharma research context. Topic: {user_question[:150]}",
        2: f"Wide cinematic illustration: peer review and evaluation board, ranking charts, collaborative assessment. Topic: {user_question[:150]}",
        3: f"Wide cinematic illustration: executive boardroom synthesis, unified decision from multiple perspectives, pharma strategy. Topic: {user_question[:150]}",
    }
    return prompts.get(stage, f"Professional pharmaceutical illustration about: {user_question[:200]}")


# ── Synchronous wrapper for non-async callers ────────────────────────────
def generate_image_sync(prompt: str, aspect_ratio: str = "16:9") -> Optional[bytes]:
    """Synchronous wrapper — creates event loop if needed."""
    try:
        loop = asyncio.get_running_loop()
        # Already in async context — use nested event loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, generate_image(prompt, aspect_ratio))
            return future.result(timeout=90)
    except RuntimeError:
        # No running loop — safe to use asyncio.run
        return asyncio.run(generate_image(prompt, aspect_ratio))


def generate_images_parallel_sync(
    prompts: Dict[str, str],
    aspect_ratio: str = "16:9",
    max_concurrent: int = 4,
) -> Dict[str, Optional[bytes]]:
    """Synchronous wrapper for batch parallel generation."""
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                generate_images_parallel(prompts, aspect_ratio, max_concurrent),
            )
            return future.result(timeout=300)
    except RuntimeError:
        return asyncio.run(generate_images_parallel(prompts, aspect_ratio, max_concurrent))
