"""Configuration for the LLM Council - Pharmaceutical Domain (Bayer)."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Provider API keys ──────────────────────────────────────────────────────
# Bayer myGenAssist API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Google AI Studio API key (get one at https://aistudio.google.com/apikey)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# ── Bayer myGenAssist models (static fallback — auto-synced at runtime) ───
# NOTE: These are only used if live sync hasn't populated yet.
# Model IDs must match exactly as shown in the MyGenAssist API.
AVAILABLE_MODELS = [
    # ── Anthropic (latest per family) ──
    {"id": "claude-opus-4.6", "name": "Claude Opus 4.6", "description": "Latest Anthropic flagship — strongest reasoning, tools & vision", "provider": "bayer"},
    {"id": "claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "description": "Fast Anthropic model — reasoning + tools, cost-efficient", "provider": "bayer"},
    # ── Google (via Bayer proxy) ──
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Google's best reasoning model, 1M context", "provider": "bayer"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "Fast reasoning, 1M context, cost-efficient", "provider": "bayer"},
    # ── OpenAI (latest per family) ──
    {"id": "gpt-5.2", "name": "GPT-5.2", "description": "Latest OpenAI flagship model", "provider": "bayer"},
    {"id": "gpt-5-mini", "name": "GPT-5 Mini", "description": "Balanced OpenAI model with reasoning", "provider": "bayer"},
    {"id": "o4-mini", "name": "O4 Mini", "description": "OpenAI reasoning specialist — deep chain-of-thought", "provider": "bayer"},
    # ── xAI ──
    {"id": "grok-3", "name": "Grok 3", "description": "Strong reasoning, 1M context window", "provider": "bayer"},
]

# ── Google AI Studio models (direct) ─────────────────────────────────────
# Prefix: "google/" — routed to generativelanguage.googleapis.com
# These are available when GOOGLE_API_KEY is set
GOOGLE_AVAILABLE_MODELS = [
    # ── Gemini 3.x (latest generation) ──
    {"id": "google/gemini-3-pro-preview", "name": "Gemini 3 Pro", "description": "Latest Gemini — cutting-edge reasoning & tools", "provider": "google"},
    {"id": "google/gemini-3-flash-preview", "name": "Gemini 3 Flash", "description": "Next-gen fast model — multimodal reasoning", "provider": "google"},
    # ── Gemini 2.5 (stable) ──
    {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Best stable reasoning, 1M context, thinking", "provider": "google"},
    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "Fast reasoning, 1M context, cost-efficient", "provider": "google"},
    {"id": "google/gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash-Lite", "description": "Ultra-lightweight, lowest cost", "provider": "google"},
    # ── Deep Research ──
    {"id": "google/deep-research-pro-preview-12-2025", "name": "Deep Research Pro", "description": "Agentic deep research — multi-step web exploration", "provider": "google"},
]

# Default council members (used when no custom selection)
# Cross-provider: picks the latest/best from BOTH Bayer + Google.
# At runtime, model_sync auto-selects from live catalogs instead.
DEFAULT_COUNCIL_MODELS = [
    "google/gemini-3-pro-preview",                # Google — latest Gemini reasoning
    "claude-sonnet-4.6",                           # Bayer  — Anthropic fast reasoner
    "gpt-5.2",                                     # Bayer  — OpenAI flagship
    "grok-3",                                      # Bayer  — xAI flagship
]

# Default chairman model (Stage 3 synthesis — prefer strong reasoning)
DEFAULT_CHAIRMAN_MODEL = "claude-opus-4.6"

# For backward compatibility
COUNCIL_MODELS = DEFAULT_COUNCIL_MODELS
CHAIRMAN_MODEL = DEFAULT_CHAIRMAN_MODEL

# Bayer Internal API endpoint
# Prefer runtime env var (ECS secret injection), then fallback to default.
OPENROUTER_API_URL = os.getenv(
    "OPENROUTER_API_URL",
    os.getenv("API_BASE_URL", "https://chat.int.bayer.com/api/v2/chat/completions"),
)

# Data directory for local-dev conversation storage (file-based fallback)
DATA_DIR = "data/conversations"

# ── Azure Blob Storage (dedicated containers per data type) ───────────────
# Storage account: llmcouncilmga  |  Resource group: rg-llmcouncil
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_BLOB_CONVERSATIONS_CONTAINER = os.getenv("AZURE_BLOB_CONVERSATIONS_CONTAINER", "conversations")
AZURE_BLOB_ATTACHMENTS_CONTAINER  = os.getenv("AZURE_BLOB_ATTACHMENTS_CONTAINER", "attachments")
AZURE_BLOB_MEMORY_CONTAINER       = os.getenv("AZURE_BLOB_MEMORY_CONTAINER", "memory")
AZURE_BLOB_SKILLS_CONTAINER       = os.getenv("AZURE_BLOB_SKILLS_CONTAINER", "skills")

# Backward-compat aliases (used by storage.py blob fallback)
AZURE_STORAGE_CONTAINER = AZURE_BLOB_CONVERSATIONS_CONTAINER
BLOB_CONVERSATIONS_PREFIX = "conversations"

# ── Azure Cosmos DB (conversation history + memory in cloud) ──────────────
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "")
COSMOS_KEY = os.getenv("COSMOS_KEY", "")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "llm-council")
COSMOS_CONVERSATIONS_CONTAINER = os.getenv("COSMOS_CONVERSATIONS_CONTAINER", "conversations")
COSMOS_MEMORY_CONTAINER = os.getenv("COSMOS_MEMORY_CONTAINER", "memory")
COSMOS_SKILLS_CONTAINER = os.getenv("COSMOS_SKILLS_CONTAINER", "skills")

# ── Entra ID (Azure AD) SSO — JWT validation ─────────────────────────────
# These are used by the backend to validate Bearer tokens issued by MSAL.
ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "fcb2b37b-5da0-466b-9b83-0014b67a7c78")
ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "a73fe3b0-6f94-4093-ba33-441d25772636")
ENTRA_AUTHORITY = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
ENTRA_ISSUER = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
ENTRA_JWKS_URI = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/discovery/v2.0/keys"
ENTRA_AUDIENCE = f"api://{ENTRA_CLIENT_ID}"
# Set to False to skip JWT validation (local dev / testing)
ENTRA_SSO_ENABLED = os.getenv("ENTRA_SSO_ENABLED", "false").lower() in ("1", "true", "yes")


def get_all_available_models():
    """Return merged list of Bayer + Google models (Google only if key is set)."""
    models = list(AVAILABLE_MODELS)
    if GOOGLE_API_KEY:
        models.extend(GOOGLE_AVAILABLE_MODELS)
    return models


def is_google_model(model_id: str) -> bool:
    """Check if a model ID routes to Google AI Studio."""
    return model_id.startswith("google/")


def strip_google_prefix(model_id: str) -> str:
    """Remove 'google/' prefix to get the raw model name for the API."""
    return model_id[len("google/"):] if model_id.startswith("google/") else model_id
