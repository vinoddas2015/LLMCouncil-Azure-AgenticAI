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

from .config import OPENROUTER_API_KEY

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
    (re.compile(r"^claude-opus-(\d+(?:\.\d+)?)$"),           "anthropic/opus",   None),
    (re.compile(r"^claude-sonnet-(\d+(?:\.\d+)?)$"),         "anthropic/sonnet", None),
    # ── Google ──
    (re.compile(r"^gemini-(\d+(?:\.\d+)?)-pro"),             "google/pro",       None),
    (re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash"),           "google/flash",     None),
    # ── OpenAI flagship ──
    (re.compile(r"^gpt-(\d+(?:\.\d+)?)$"),                   "openai/flagship",  None),
    (re.compile(r"^gpt-(\d+)-mini$"),                         "openai/mini",      None),
    (re.compile(r"^gpt-(\d+)-nano$"),                         "openai/nano",      None),
    # ── OpenAI reasoning ("o" series) ──
    (re.compile(r"^o(\d+)-mini$"),                            "openai/o-mini",    None),
    (re.compile(r"^o(\d+)$"),                                 "openai/o",         None),
    # ── xAI ──
    (re.compile(r"^grok-(\d+(?:\.\d+)?)$"),                  "xai/grok",         None),
    # ── GPT-4o line (legacy bridge) ──
    (re.compile(r"^gpt-4o-mini$"),                            "openai/4o-mini",   lambda _: (4, 0)),
    (re.compile(r"^gpt-4o$"),                                 "openai/4o",        lambda _: (4, 0)),
    (re.compile(r"^gpt-4\.1$"),                               "openai/4.1",       lambda _: (4, 1)),
    # ── Legacy Anthropic (claude-3-X-sonnet naming) ──
    (re.compile(r"^claude-3-(\d+)-sonnet$"),                  "anthropic/sonnet", lambda m: (3, int(m.group(1)))),
]


def _parse_version(ver_str: str) -> Tuple[int, ...]:
    """Convert '4.6' → (4, 6), '5' → (5, 0), '2.5' → (2, 5)."""
    parts = ver_str.split(".")
    return tuple(int(p) for p in parts) + (0,) * (2 - len(parts))


def _classify(model_id: str) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """Return (family_key, version_tuple) or None if unrecognised."""
    for pattern, family, ver_fn in _FAMILY_RULES:
        m = pattern.match(model_id)
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


def _pick_defaults(models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Auto-select sensible defaults for the council from the live model list.

    Policy:
      - Council: one model from each major family that supports reasoning
      - Chairman: the highest-capability model (prefers anthropic/opus)
    """
    model_ids = {m["id"] for m in models}
    reasoning_ids = {m["id"] for m in models if m.get("supports_reasoning")}

    # Preferred council composition (in priority order per family)
    family_preferences = [
        ("google/pro",       ["gemini"]),
        ("anthropic/opus",   ["claude-opus"]),
        ("xai/grok",         ["grok"]),
        ("openai/mini",      ["gpt-5-mini", "gpt"]),
        ("openai/flagship",  ["gpt-5", "gpt"]),
    ]

    council = []
    for family, _ in family_preferences:
        for m in models:
            if m.get("family") == family and m["id"] in reasoning_ids:
                council.append(m["id"])
                break

    # Fallback: if we got fewer than 3, add any remaining reasoning models
    if len(council) < 3:
        for m in models:
            if m["id"] not in council and m["id"] in reasoning_ids:
                council.append(m["id"])
            if len(council) >= 4:
                break

    # Chairman: prefer anthropic/opus, then google/pro, then first reasoning model
    chairman = None
    for preferred_family in ["anthropic/opus", "google/pro", "openai/flagship"]:
        for m in models:
            if m.get("family") == preferred_family and m["id"] in reasoning_ids:
                chairman = m["id"]
                break
        if chairman:
            break
    if not chairman and council:
        chairman = council[0]

    return {
        "council_models": council[:5],  # cap at 5 for cost sanity
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
    """Return the current filtered model list (thread-safe read)."""
    return list(_live_models)


def get_defaults() -> Dict[str, Any]:
    """Return auto-computed default council + chairman from live models."""
    if not _live_models:
        # Fallback to static config if sync hasn't run yet
        from .config import DEFAULT_COUNCIL_MODELS, DEFAULT_CHAIRMAN_MODEL
        return {
            "council_models": DEFAULT_COUNCIL_MODELS,
            "chairman_model": DEFAULT_CHAIRMAN_MODEL,
        }
    return _pick_defaults(_live_models)


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
