"""
Model Sync — Auto-discover & version-manage models from the MyGenAssist API.

On startup (and every SYNC_INTERVAL minutes), queries /api/v2/models,
filters to usable chat-completion models, and keeps only the latest
version per model family.  Old versions are automatically dropped.

The live model list is exposed via `get_live_models()` and `get_defaults()`.
"""

import re
import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import httpx

from .config import OPENROUTER_API_KEY, GOOGLE_API_KEY, GOOGLE_AVAILABLE_MODELS

logger = logging.getLogger("llm_council.model_sync")

# ── Configuration ────────────────────────────────────────────────────────

# Bayer myGenAssist model catalog endpoint
_MODELS_URL = "https://chat.int.bayer.com/api/v2/models"

# How often to re-sync (minutes)
SYNC_INTERVAL_MINUTES = 30

# Patterns to EXCLUDE (infrastructure variants, not user-facing)
_EXCLUDE_PATTERNS = [
    r"-azure$",           # Azure-routed duplicates
    r"-non-ptu$",         # Non-PTU variants
    r"^ptu-",             # PTU infrastructure alias
    r"-batch$",           # Batch-only models
    r"-mga$",             # Self-hosted MGA clones (Llama, DeepSeek, Mistral, Cohere)
    r"^deepmind/",        # Internal embedding/rerank models
    r"-onnx-",            # ONNX runtime models
    r"-\d{4}-\d{2}-\d{2}$", # Date-stamped snapshots (e.g. gpt-4o-2024-08-06)
    r"^gpt-oss-",         # Internal OSS fine-tunes
]

# Model families we DON'T want in the council (embedding, rerank, batch, etc.)
_ALLOWED_TYPES = {"chat_completion"}

# Minimum required — model must support tool calling for council use
_REQUIRE_TOOLS = True

# ── Internal state (thread-safe via asyncio single-thread) ───────────────

_live_models: List[Dict[str, Any]] = []
_last_sync: Optional[datetime] = None
_raw_catalog: List[Dict[str, Any]] = []   # full unfiltered API response


# ── Family classification ────────────────────────────────────────────────

# Each pattern maps a model ID → (family_key, version_tuple).
# Family key groups models that are "the same thing, different version".
# version_tuple is used for comparison (higher = newer).

_FAMILY_RULES: List[Tuple[re.Pattern, str, Any]] = [
    # ── Anthropic ──
    (re.compile(r"^claude-opus-(\d+(?:\.\d+)?)$"),           "anthropic/opus",      None),
    (re.compile(r"^claude-sonnet-(\d+(?:\.\d+)?)$"),         "anthropic/sonnet",    None),
    # ── Google ──
    (re.compile(r"^gemini-(\d+(?:\.\d+)?)-pro"),             "google/pro",          None),
    (re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash-lite"),      "google/flash-lite",   None),
    (re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash"),           "google/flash",        None),
    (re.compile(r"^deep-research-pro"),                       "google/deep-research",lambda _: (1, 0)),
    # ── OpenAI flagship ──
    (re.compile(r"^gpt-(\d+(?:\.\d+)?)$"),                   "openai/flagship",     None),
    (re.compile(r"^gpt-(\d+)-mini$"),                         "openai/mini",         None),
    (re.compile(r"^gpt-(\d+)-nano$"),                         "openai/nano",         None),
    # ── OpenAI reasoning ("o" series) ──
    (re.compile(r"^o(\d+)-mini$"),                            "openai/o-mini",       None),
    (re.compile(r"^o(\d+)$"),                                 "openai/o",            None),
    # ── xAI ──
    (re.compile(r"^grok-(\d+(?:\.\d+)?)$"),                  "xai/grok",            None),
    # ── GPT-4o line (legacy bridge) ──
    (re.compile(r"^gpt-4o-mini$"),                            "openai/4o-mini",      lambda _: (4, 0)),
    (re.compile(r"^gpt-4o$"),                                 "openai/4o",           lambda _: (4, 0)),
    (re.compile(r"^gpt-4\.1$"),                               "openai/4.1",          lambda _: (4, 1)),
    # ── Legacy Anthropic (claude-3-X-sonnet naming) ──
    (re.compile(r"^claude-3-(\d+)-sonnet$"),                  "anthropic/sonnet",    lambda m: (3, int(m.group(1)))),
    # ── Open-source / niche (Google AI Studio) ──
    (re.compile(r"^gemma-(\d+)"),                             "google/gemma",        None),
]


def _parse_version(ver_str: str) -> Tuple[int, ...]:
    """Convert '4.6' → (4, 6), '5' → (5, 0), '2.5' → (2, 5)."""
    parts = ver_str.split(".")
    return tuple(int(p) for p in parts) + (0,) * (2 - len(parts))


def _normalize_model_id(model_id: str) -> str:
    """Strip provider prefix and preview/date suffixes for family classification.

    Examples:
      google/gemini-3.1-pro-preview         → gemini-3.1-pro
      google/deep-research-pro-preview-12-2025 → deep-research-pro
      claude-opus-4.6                        → claude-opus-4.6  (unchanged)
    """
    mid = model_id
    if mid.startswith("google/"):
        mid = mid[len("google/"):]
    # Strip -preview and optional date suffix (-MM-YYYY)
    mid = re.sub(r"-preview(?:-\d{2}-\d{4})?$", "", mid)
    return mid


def _classify(model_id: str) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """Return (family_key, version_tuple) or None if unrecognised.

    Normalises google/-prefixed and -preview suffixed IDs first so that
    both Bayer-proxy and Google-direct models land in the same families.
    """
    normalized = _normalize_model_id(model_id)
    for pattern, family, ver_fn in _FAMILY_RULES:
        m = pattern.match(normalized)
        if m:
            if ver_fn:
                version = ver_fn(m)
            else:
                version = _parse_version(m.group(1))
            return (family, version)
    return None


def _is_excluded(model_id: str) -> bool:
    """Check if model matches any exclusion pattern."""
    return any(re.search(p, model_id) for p in _EXCLUDE_PATTERNS)


def _friendly_name(model: Dict[str, Any]) -> str:
    """Build a user-friendly display name from API metadata."""
    return model.get("name") or model.get("id", "Unknown")


def _description_for(model: Dict[str, Any]) -> str:
    """Generate a short description from API metadata."""
    parts = []
    if model.get("supports_reasoning"):
        parts.append("Reasoning")
    if model.get("supports_tools"):
        parts.append("Tools")
    cost_in = model.get("input_cost_per_million_token")
    cost_out = model.get("output_cost_per_million_token")
    if cost_in is not None and cost_out is not None:
        parts.append(f"${cost_in}/${cost_out} per M tokens")
    model_type = model.get("model_type", "")
    if model_type:
        parts.append(model_type.replace("_", " ").title())
    return " · ".join(parts) if parts else "Available via MyGenAssist"


# ── Core sync logic ─────────────────────────────────────────────────────

async def _fetch_catalog() -> List[Dict[str, Any]]:
    """Fetch the raw model catalog from MyGenAssist."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        resp = await client.get(_MODELS_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", data.get("models", []))


def _filter_and_dedupe(raw_models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter → keep latest per family → return sorted list.

    Steps:
      1. Drop non-chat, unavailable, excluded, tool-less models
      2. Classify into families
      3. Keep only the highest version per family
      4. Include "standalone" models that don't match any family
    """
    # Step 1: basic filtering
    candidates = []
    standalone = []

    for m in raw_models:
        mid = m.get("id", "")
        mtype = m.get("model_type", "")
        status = m.get("model_status", "")

        # Must be chat_completion + available
        if mtype not in _ALLOWED_TYPES:
            continue
        if status != "available":
            continue
        # Exclusion patterns
        if _is_excluded(mid):
            continue
        # Must support tools (required for council function calling)
        if _REQUIRE_TOOLS and not m.get("supports_tools"):
            continue

        classification = _classify(mid)
        if classification:
            candidates.append((classification, m))
        else:
            standalone.append(m)

    # Step 2: group by family, keep highest version
    best: Dict[str, Tuple[Tuple[int, ...], Dict[str, Any]]] = {}
    replaced: List[str] = []  # track which models were superseded

    for (family, version), model in candidates:
        if family not in best or version > best[family][0]:
            if family in best:
                old_id = best[family][1].get("id")
                replaced.append(old_id)
                logger.info(
                    f"⬆️  {family}: {old_id} → {model.get('id')} (version upgrade)"
                )
            best[family] = (version, model)
        else:
            replaced.append(model.get("id"))

    if replaced:
        logger.info(f"🗑️  Superseded models removed: {', '.join(replaced)}")

    # Step 3: assemble final list
    result = []
    for family, (version, model) in sorted(best.items()):
        result.append({
            "id": model["id"],
            "name": _friendly_name(model),
            "description": _description_for(model),
            "family": family,
            "version": ".".join(str(v) for v in version),
            "supports_tools": model.get("supports_tools", False),
            "supports_reasoning": model.get("supports_reasoning", False),
            "input_cost": model.get("input_cost_per_million_token"),
            "output_cost": model.get("output_cost_per_million_token"),
            "source": "mygenassist_api",
        })

    # Also include standalone available models (no family match)
    for model in standalone:
        result.append({
            "id": model["id"],
            "name": _friendly_name(model),
            "description": _description_for(model),
            "family": "other",
            "version": "0",
            "supports_tools": model.get("supports_tools", False),
            "supports_reasoning": model.get("supports_reasoning", False),
            "input_cost": model.get("input_cost_per_million_token"),
            "output_cost": model.get("output_cost_per_million_token"),
            "source": "mygenassist_api",
        })

    return result


# ── Cross-provider helpers ───────────────────────────────────────────────

def _classify_static_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add family/version classification to static model entries (e.g. Google config).

    Static models from GOOGLE_AVAILABLE_MODELS lack the ``family`` and
    ``version`` fields that ``_filter_and_dedupe`` adds to Bayer models.
    This function classifies them identically so they can participate in
    cross-provider dedup and default-selection.
    """
    result = []
    for m in models:
        mid = m.get("id", "")
        classification = _classify(mid)
        if classification:
            family, version = classification
        else:
            family, version = "other", (0,)
        result.append({
            **m,
            "family": family,
            "version": ".".join(str(v) for v in version),
            "supports_tools": m.get("supports_tools", True),
            "supports_reasoning": m.get("supports_reasoning", True),
            "source": m.get("provider", "google"),
        })
    return result


def _cross_provider_dedupe(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only the highest version per family regardless of provider.

    When Bayer offers gemini-2.5-pro and Google direct offers
    google/gemini-3.1-pro-preview, both land in ``google/pro`` — the 3.1
    model wins, the 2.5 is auto-removed.  Non-family ("other") models
    are kept as-is.
    """
    best: Dict[str, Tuple[Tuple[int, ...], Dict[str, Any]]] = {}
    standalone: List[Dict[str, Any]] = []

    for m in models:
        family = m.get("family", "other")
        if family == "other":
            standalone.append(m)
            continue

        version = _parse_version(m.get("version", "0"))
        if family not in best or version > best[family][0]:
            if family in best:
                old = best[family][1]
                logger.info(
                    f"⬆️  Cross-provider dedup: {old['id']} → {m['id']} "
                    f"({family} {old.get('version')} → {'.'.join(str(v) for v in version)})"
                )
            best[family] = (version, m)

    result = [m for _, m in sorted(best.values(), key=lambda x: x[1].get("family", ""))]
    result.extend(standalone)
    return result


def _pick_defaults(models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Auto-select sensible defaults for the council from the MERGED model list.

    Policy (cross-provider):
      - Council: one model from each major family, highest version wins
        regardless of provider (Bayer vs Google).
      - Chairman: prefer anthropic/opus for synthesis strength, then
        google/pro, then openai/flagship.

    Family priority order for council:
      1. google/pro           — best Gemini reasoning (latest version wins)
      2. anthropic/sonnet     — Anthropic fast reasoner (diverse vendor)
      3. openai/flagship      — GPT-5.x from Bayer
      4. xai/grok             — Grok from Bayer
      5. anthropic/opus       — Claude Opus (fallback if not chairman)

    Note: google/deep-research is excluded — agentic model that uses a
    different API flow (not compatible with generateContent).
    """
    model_ids = {m["id"] for m in models}
    reasoning_ids = {m["id"] for m in models if m.get("supports_reasoning")}

    # Preferred council composition (in priority order per family)
    family_preferences = [
        "google/pro",
        "anthropic/sonnet",
        "openai/flagship",
        "xai/grok",
        "anthropic/opus",
    ]

    council = []
    for family in family_preferences:
        for m in models:
            if m.get("family") == family:
                # Prefer reasoning-capable, but accept any if no reasoning model
                council.append(m["id"])
                break

    # Fallback: if we got fewer than 3, add remaining reasoning models
    if len(council) < 3:
        for m in models:
            if m["id"] not in council and m["id"] in reasoning_ids:
                council.append(m["id"])
            if len(council) >= 4:
                break

    # Chairman: prefer anthropic/opus (strongest synthesis), then google/pro
    chairman = None
    for preferred_family in ["anthropic/opus", "google/pro", "openai/flagship"]:
        for m in models:
            if m.get("family") == preferred_family:
                chairman = m["id"]
                break
        if chairman:
            break
    if not chairman and council:
        chairman = council[0]

    # Exclude chairman from the council — it acts as Stage 3 synthesizer only
    council = [mid for mid in council if mid != chairman]

    return {
        "council_models": council[:4],  # cap at 4 for cost sanity
        "chairman_model": chairman,
    }


# ── Public API ───────────────────────────────────────────────────────────

async def sync_models() -> Dict[str, Any]:
    """
    Fetch the latest catalog, filter/dedupe, update internal state.
    Returns a summary dict.
    """
    global _live_models, _last_sync, _raw_catalog

    try:
        logger.info("🔄 Model sync: fetching catalog from MyGenAssist...")
        raw = await _fetch_catalog()
        _raw_catalog = raw

        before_ids = {m["id"] for m in _live_models}
        _live_models = _filter_and_dedupe(raw)
        after_ids = {m["id"] for m in _live_models}
        _last_sync = datetime.utcnow()

        added = after_ids - before_ids
        removed = before_ids - after_ids

        if added:
            logger.info(f"✅ Models ADDED: {', '.join(sorted(added))}")
        if removed:
            logger.info(f"🗑️  Models REMOVED: {', '.join(sorted(removed))}")

        summary = {
            "status": "ok",
            "synced_at": _last_sync.isoformat() + "Z",
            "total_in_catalog": len(raw),
            "total_after_filter": len(_live_models),
            "added": sorted(added),
            "removed": sorted(removed),
            "models": [m["id"] for m in _live_models],
        }
        logger.info(
            f"✅ Model sync complete: {len(_live_models)} usable models "
            f"(+{len(added)} / -{len(removed)})"
        )
        return summary

    except Exception as e:
        logger.error(f"❌ Model sync failed: {e}")
        # Keep previous list on failure (graceful degradation)
        return {"status": "error", "error": str(e)}


def get_live_models() -> List[Dict[str, Any]]:
    """Return the current filtered model list — Bayer + Google (if key is set).

    Google models are classified and cross-provider deduped so the UI only
    shows the latest version per family.  E.g. if Google has gemini-3.1-pro
    and Bayer has gemini-2.5-pro, only the 3.1 is returned for google/pro.
    """
    models = list(_live_models)
    if GOOGLE_API_KEY:
        google_classified = _classify_static_models(GOOGLE_AVAILABLE_MODELS)
        models.extend(google_classified)
        models = _cross_provider_dedupe(models)
    return models


def get_defaults() -> Dict[str, Any]:
    """Return auto-computed default council + chairman from MERGED models.

    Cross-provider: considers both Bayer (live sync) and Google (static config)
    models, keeping only the highest version per family for default selection.
    """
    if not _live_models:
        # Fallback to static config if sync hasn't run yet
        from .config import DEFAULT_COUNCIL_MODELS, DEFAULT_CHAIRMAN_MODEL
        return {
            "council_models": DEFAULT_COUNCIL_MODELS,
            "chairman_model": DEFAULT_CHAIRMAN_MODEL,
        }
    # Merge Bayer (already classified from sync) + Google (classify now)
    merged = list(_live_models)
    if GOOGLE_API_KEY:
        google_classified = _classify_static_models(GOOGLE_AVAILABLE_MODELS)
        merged.extend(google_classified)
        merged = _cross_provider_dedupe(merged)
    return _pick_defaults(merged)


def get_sync_status() -> Dict[str, Any]:
    """Return metadata about the last sync."""
    return {
        "last_sync": _last_sync.isoformat() + "Z" if _last_sync else None,
        "model_count": len(_live_models),
        "catalog_size": len(_raw_catalog),
        "sync_interval_minutes": SYNC_INTERVAL_MINUTES,
        "models": [{"id": m["id"], "name": m["name"], "family": m["family"]} for m in _live_models],
    }


async def periodic_sync_loop():
    """Background loop — re-syncs every SYNC_INTERVAL_MINUTES."""
    while True:
        await asyncio.sleep(SYNC_INTERVAL_MINUTES * 60)
        await sync_models()
