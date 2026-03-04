"""Multi-provider image generation engine with quality validation.

Providers (priority order):
1. Azure GPT-Image-1.5       — Microsoft Copilot quality, clean text-free images
2. Google Imagen 4.0 Fast    — fast fallback (:predict endpoint)
3. Gemini Flash Image        — chat-completions fallback

Caching (3-tier serverless — see image_cache.py):
  L1: In-memory (10 items, same-request dedup)
  L2: Redis Enterprise (shared across instances, 1h TTL)
  L3: Azure Blob Storage (permanent, unlimited, content-addressed)

Quality features:
- Parallel async generation for speed
- Per-image quality validation using Gemini vision model
- Automatic retry with refined prompt on low-quality images
- Graceful fallback chain: GPT-Image → Imagen → Gemini Flash → None
"""

import asyncio
import base64
import io
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import httpx

from .config import GOOGLE_API_KEY

logger = logging.getLogger(__name__)

# ── Provider config ──────────────────────────────────────────────────────
# GPT-Image-1.5 via Azure OpenAI (East US 2) — Microsoft Copilot quality
GPT_IMAGE_ENDPOINT = os.getenv("GPT_IMAGE_ENDPOINT", "")
GPT_IMAGE_KEY = os.getenv("GPT_IMAGE_KEY", "")
GPT_IMAGE_DEPLOYMENT = os.getenv("GPT_IMAGE_DEPLOYMENT", "gpt-image")

# Legacy Azure OpenAI DALL-E (deprecated March 2026)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_DALLE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT", "dalle3")

IMAGEN_MODEL = "imagen-4.0-fast-generate-001"
GEMINI_IMAGE_MODEL = "gemini-2.0-flash-exp-image-generation"

# Quality validation model (fast vision model)
QUALITY_VALIDATOR_MODEL = "gemini-2.5-flash"

# ── 3-tier serverless image cache ────────────────────────────────────────
# L1 memory → L2 Redis → L3 Azure Blob  (see image_cache.py)
from . import image_cache as _icache

# Legacy aliases kept for backward compat (Image Quality Agent reads these)
_image_cache = _icache._l1_cache   # L1 reference for agents introspection
_MAX_CACHE_SIZE = _icache._L1_MAX  # L1 max (tiny — dedup only)


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


# ── Provider: Azure OpenAI GPT-Image-1.5 (Microsoft Copilot quality) ─────
async def _generate_gpt_image(prompt: str, aspect_ratio: str = "16:9") -> Optional[bytes]:
    """Generate image via Azure OpenAI GPT-Image-1.5 deployment.

    Sizes supported by gpt-image-1.5:
      1536x1024 (landscape/16:9), 1024x1536 (portrait), 1024x1024 (square)
    """
    if not GPT_IMAGE_ENDPOINT or not GPT_IMAGE_KEY:
        return None

    size_map = {
        "16:9": "1536x1024",
        "3:4": "1024x1536",
        "9:16": "1024x1536",
        "1:1": "1024x1024",
    }
    size = size_map.get(aspect_ratio, "1536x1024")

    url = (
        f"{GPT_IMAGE_ENDPOINT.rstrip('/')}/openai/deployments/{GPT_IMAGE_DEPLOYMENT}"
        f"/images/generations?api-version=2025-04-01-preview"
    )
    headers = {"api-key": GPT_IMAGE_KEY, "Content-Type": "application/json"}
    payload = {
        "prompt": prompt[:4000],
        "n": 1,
        "size": size,
        "quality": "high",
        "response_format": "b64_json",
    }

    try:
        async with httpx.AsyncClient(timeout=120, verify=False) as client:
            for attempt in range(3):
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", 10 * (attempt + 1)))
                    logger.info("GPT-Image 429 — retrying in %ds (attempt %d/3)", retry_after, attempt + 1)
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                data = resp.json()
                images = data.get("data", [])
                if not images:
                    return None
                b64 = images[0].get("b64_json")
                if not b64:
                    return None
                return base64.b64decode(b64)
            return None  # exhausted retries
    except Exception as e:
        logger.warning("GPT-Image-1.5 generation failed: %s", e)
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
    
    Priority: GPT-Image-1.5 → Google Imagen 4.0 → Gemini Flash
    
    If validate=True, runs quality check and retries with refined prompt on low scores.
    """
    # ── Check 3-tier cache (L1 → L2 Redis → L3 Blob) ────────────────
    cached = _icache.get(prompt, aspect_ratio)
    if cached:
        return cached

    image = None

    # 1) GPT-Image-1.5 (Microsoft Copilot quality)
    if GPT_IMAGE_ENDPOINT and GPT_IMAGE_KEY:
        image = await _generate_gpt_image(prompt, aspect_ratio)
        if image:
            logger.info("Image generated via GPT-Image-1.5 (%d bytes)", len(image))

    # 2) Fallback: Google Imagen 4.0 Fast
    if not image:
        image = await _generate_imagen(prompt, aspect_ratio)
        if image:
            logger.info("Image generated via Imagen 4.0 Fast (%d bytes)", len(image))

    # 3) Fallback: Gemini Flash
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

    # Write through all 3 cache tiers (L3 Blob → L2 Redis → L1 memory)
    _icache.put(prompt, aspect_ratio, image)

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

# Visual perspectives cycled across chunks to ensure unique imagery per slide
_PERSPECTIVES = [
    "wide establishing shot, panoramic composition",
    "close-up detail view, macro focus",
    "isometric 3D diagram style, birds-eye view",
    "split-screen comparison layout, side by side",
    "dynamic diagonal composition, action perspective",
    "minimalist flat illustration, clean geometric shapes",
    "layered depth composition, foreground-midground-background",
    "circular radial composition, hub-and-spoke layout",
]


def build_slide_prompt(
    model_name: str,
    content_snippet: str,
    stage: int,
    user_question: str = "",
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> str:
    """Build a unique image prompt for a specific slide chunk.

    Each chunk gets a different visual perspective to eliminate duplicate imagery.
    Strong no-text directive prevents garbled text artifacts in generated images.
    """
    snippet = content_snippet[:200].strip()

    stage_context = {
        1: "scientific research and data analysis",
        2: "peer review evaluation and quality assessment",
        3: "executive synthesis and strategic decision",
    }
    base = stage_context.get(stage, "scientific illustration")

    # Cycle through perspectives based on chunk index
    perspective = _PERSPECTIVES[chunk_index % len(_PERSPECTIVES)]

    prompt = (
        f"Professional photorealistic illustration for a pharma presentation slide. "
        f"Visual style: {perspective}. "
        f"Theme: {base}. "
        f"Topic: {user_question[:100]}. "
        f"Visual focus: {snippet}. "
        f"Clean, modern, corporate design with rich colour palette. "
        f"ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS, NO LABELS, "
        f"NO WATERMARKS anywhere in the image. Pure visual imagery only."
    )

    return prompt[:4000]


def build_section_prompt(stage: int, user_question: str) -> str:
    """Build a hero image prompt for a stage section divider slide."""
    prompts = {
        1: (
            f"Wide cinematic photorealistic illustration: scientific brainstorm session, "
            f"multiple perspectives analyzing complex data, pharma research laboratory setting. "
            f"Topic: {user_question[:150]}. "
            f"ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS in the image."
        ),
        2: (
            f"Wide cinematic photorealistic illustration: peer review evaluation panel, "
            f"quality assessment dashboard, collaborative scientific assessment. "
            f"Topic: {user_question[:150]}. "
            f"ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS in the image."
        ),
        3: (
            f"Wide cinematic photorealistic illustration: executive boardroom synthesis, "
            f"unified decision emerging from multiple data streams, strategic pharma overview. "
            f"Topic: {user_question[:150]}. "
            f"ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS in the image."
        ),
    }
    return prompts.get(stage, (
        f"Professional photorealistic pharmaceutical illustration about: "
        f"{user_question[:200]}. "
        f"ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO NUMBERS in the image."
    ))


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
