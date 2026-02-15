"""Configuration for the LLM Council - Pharmaceutical Domain (Bayer)."""

import os
from dotenv import load_dotenv

load_dotenv()

# Bayer myGenAssist API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# All available models for the council (users can select from these)
# NOTE: Model IDs must match exactly as shown in the API (no vendor prefixes)
AVAILABLE_MODELS = [
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Google's best reasoning model, 1M context"},
    {"id": "claude-opus-4.5", "name": "Claude Opus 4.5", "description": "Strongest tool-using & reasoning model"},
    {"id": "grok-3", "name": "Grok 3", "description": "Strong reasoning, 1M context window"},
    {"id": "gpt-5-mini", "name": "GPT-5 Mini", "description": "Balanced OpenAI model"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "Fast and efficient for quick tasks"},
]

# Default council members (used when no custom selection)
DEFAULT_COUNCIL_MODELS = [
    "gemini-2.5-pro",
    "claude-opus-4.5",
    "grok-3",
    "gpt-5-mini",
]

# Default chairman model
DEFAULT_CHAIRMAN_MODEL = "claude-opus-4.5"

# For backward compatibility
COUNCIL_MODELS = DEFAULT_COUNCIL_MODELS
CHAIRMAN_MODEL = DEFAULT_CHAIRMAN_MODEL

# Bayer Internal API endpoint
# Prefer runtime env var (ECS secret injection), then fallback to default.
OPENROUTER_API_URL = os.getenv(
    "OPENROUTER_API_URL",
    os.getenv("API_BASE_URL", "https://chat.int.bayer.com/api/v2/chat/completions"),
)

# Data directory for conversation storage
DATA_DIR = "data/conversations"
