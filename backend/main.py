"""FastAPI backend for LLM Council."""

import logging
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import os
import asyncio
import base64
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from . import storage
from .council import run_full_council, generate_conversation_title, build_conversation_context, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings, stage2_ca_validation_pass, parse_ranking_from_text, parse_rubric_scores, parse_claim_counts, compute_relevancy_gate
from .config import OPENROUTER_API_KEY, AVAILABLE_MODELS, DEFAULT_COUNCIL_MODELS, DEFAULT_CHAIRMAN_MODEL, COUNCIL_MODELS, GOOGLE_API_KEY, is_google_model
from .model_sync import sync_models, get_live_models, get_defaults, get_sync_status, periodic_sync_loop
from .openrouter import query_model
from .resilience import (
    kill_switch,
    circuit_breaker,
    health_monitor,
    resolve_fallback,
    check_quorum,
    KillSwitchError,
    QuorumError,
    MIN_STAGE1_QUORUM,
    MIN_STAGE2_QUORUM,
)
from .grounding import compute_response_grounding_scores, get_rubric_criteria, enhance_ca_with_validation
from .skills import run_evidence_skills, format_citations_for_prompt
from .token_tracking import SessionCostTracker
from .memory import get_memory_manager, get_user_profile_memory, get_eca
from .memory_store import set_memory_user
from .prompt_guard import evaluate_prompt
from .orchestrator import (
    pre_stage1_agent,
    post_stage2_agent,
    post_stage3_agent,
    user_gate_agent,
)
from .agents import run_agent_team, enrich_stage3_citations, validate_and_fix_citations
from .openrouter import close_shared_client
from .security import get_security_status
from .infographics import extract_infographic, strip_infographic_block
from .auth import get_authenticated_user_id
from .config import ENTRA_SSO_ENABLED


from .health_probe import health_agent, periodic_health_check


def check_token_expiry():
    """Check JWT token expiration on startup."""
    if not OPENROUTER_API_KEY:
        print("⚠️  WARNING: No API key configured in .env!")
        return
    
    # Check if it's a persistent API key (mga-*) instead of JWT
    if OPENROUTER_API_KEY.startswith("mga-"):
        print(f"\n{'='*60}")
        print(f"🔐 API Key Status")
        print(f"{'='*60}")
        print(f"   Type: Persistent myGenAssist API Key (mga-*)")
        print(f"   Key: {OPENROUTER_API_KEY[:20]}...")
        print(f"   🟢 STATUS: OK (Persistent keys do not expire)")
        print(f"{'='*60}\n")
        return
    
    try:
        payload = OPENROUTER_API_KEY.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        
        exp_date = datetime.fromtimestamp(decoded.get('exp', 0))
        remaining_mins = (exp_date - datetime.now()).total_seconds() / 60
        
        print(f"\n{'='*60}")
        print(f"🔐 JWT Token Status")
        print(f"{'='*60}")
        print(f"   Expires: {exp_date.strftime('%d-%b-%Y %H:%M:%S')}")
        print(f"   Remaining: {remaining_mins:.0f} minutes")
        
        if remaining_mins <= 0:
            print(f"   ⛔ STATUS: EXPIRED!")
            print(f"\n   Run: python token_monitor.py --refresh <new_token>")
        elif remaining_mins <= 10:
            print(f"   🔴 STATUS: CRITICAL - Token expiring soon!")
        elif remaining_mins <= 30:
            print(f"   🟠 STATUS: WARNING - Consider refreshing token")
        else:
            print(f"   🟢 STATUS: OK")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"⚠️  Could not decode JWT token: {e}")


# Check token on startup
check_token_expiry()


# ── Lifespan: startup model sync + periodic refresh ─────────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(application):
    """Run model sync on startup, launch periodic refresh in background."""
    logger.info("🚀 Running initial model sync...")
    try:
        summary = await asyncio.wait_for(sync_models(), timeout=25)
        logger.info(f"   Initial sync result: {summary.get('total_after_filter', '?')} models")
    except asyncio.TimeoutError:
        logger.warning("⚠️  Model sync timed out after 25s — starting with default models")
    except Exception as e:
        logger.warning(f"⚠️  Model sync failed: {e} — starting with default models")
    # Launch periodic sync as a background task
    sync_task = asyncio.create_task(periodic_sync_loop())
    # Launch health probe agent (checks every 5 minutes)
    health_task = asyncio.create_task(periodic_health_check(interval_seconds=300))
    yield
    health_task.cancel()
    sync_task.cancel()
    await close_shared_client()


app = FastAPI(title="LLM Council API", lifespan=lifespan)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Request Logging Middleware
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log incoming requests with all headers except authorization (excluding /health endpoint)."""
    
    async def dispatch(self, request: Request, call_next):
        # Skip logging for health endpoint (used by ECS)
        if request.url.path == "/health":
            return await call_next(request)
        
        # Log endpoint
        logger.info(f"[Request] {request.method} {request.url.path}")
        
        # Log all headers except authorization
        filtered_headers = {}
        for header_name, header_value in request.headers.items():
            if header_name.lower() not in ["authorization", "auth", "token"]:
                filtered_headers[header_name] = header_value
        
        logger.info(f"[Request] Headers: {json.dumps(filtered_headers, indent=2)}")
        
        # Continue processing the request
        response = await call_next(request)
        return response


# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Enable CORS — with credentials support for Entra ID SSO
_cors_origins = [
    "http://localhost:5173",
    "https://llmcouncil-frontend.azurewebsites.net",
    "https://llmcouncil-agents.ai",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if ENTRA_SSO_ENABLED else ["*"],
    allow_credentials=ENTRA_SSO_ENABLED,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class AttachmentData(BaseModel):
    """Attachment file data."""
    name: str
    type: str
    size: int
    base64: str


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    attachments: List[AttachmentData] = []
    council_models: Optional[List[str]] = None
    chairman_model: Optional[str] = None
    web_search_enabled: bool = False


class EnhancePromptRequest(BaseModel):
    """Request to enhance a user prompt."""
    content: str


# Allowed MIME types for file attachments
ALLOWED_MIME_TYPES = {
    'application/pdf': 'PDF',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
    'text/markdown': 'Markdown',
    'text/plain': 'Text',
    'image/png': 'Image (PNG)',
    'image/jpeg': 'Image (JPEG)',
    'image/gif': 'Image (GIF)',
    'image/webp': 'Image (WebP)',
    'image/svg+xml': 'Image (SVG)',
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def validate_attachment(attachment: AttachmentData) -> str | None:
    """Validate an attachment. Returns error message if invalid, None if valid."""
    if attachment.type not in ALLOWED_MIME_TYPES:
        return f"Invalid file type: {attachment.type}. Allowed: PDF, PPTX, XLSX, DOCX"
    
    if attachment.size > MAX_FILE_SIZE:
        return f"File too large: {attachment.name}. Maximum: 10MB"
    
    return None


def extract_file_content_description(attachment: AttachmentData) -> str:
    """Extract a description of the file content for the LLM context."""
    file_type = ALLOWED_MIME_TYPES.get(attachment.type, 'Document')
    return f"[Attached {file_type} file: {attachment.name} ({attachment.size / 1024:.1f} KB)]"


async def get_user_id(user_id: str = Header(..., alias="user-id")) -> str:
    """Extract and validate the user-id header injected by the reverse proxy.
    
    DEPRECATED: Use get_authenticated_user_id from auth.py instead.
    Kept for backward compatibility with non-conversation endpoints.
    """
    sanitized = user_id.strip()
    if not sanitized or "/" in sanitized or "\\" in sanitized or ".." in sanitized:
        raise HTTPException(status_code=400, detail="Invalid user-id header")
    return sanitized


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/health")
async def health():
    """Lightweight infra health check endpoint for ALB/ECS."""
    return {"status": "ok"}


@app.get("/api/health/deep")
async def deep_health():
    """Comprehensive health check — tests all subsystems (DB, API, memory, models, resilience)."""
    return await health_agent.run_deep_check()


@app.get("/api/health/history")
async def health_history(limit: int = 20):
    """Get recent health check history."""
    return {"history": health_agent.get_history(limit=limit)}


@app.get("/api/health/failures")
async def health_failures():
    """Get subsystems with consecutive failures."""
    return health_agent.get_failure_report()


@app.get("/api/models")
async def get_available_models():
    """Get list of available models — live from MyGenAssist API + Google AI Studio."""
    live = get_live_models()
    defaults = get_defaults()
    # Fallback to static config if sync hasn't populated yet
    if not live:
        from .config import get_all_available_models
        live = get_all_available_models()
        defaults = {
            "council_models": DEFAULT_COUNCIL_MODELS,
            "chairman_model": DEFAULT_CHAIRMAN_MODEL,
        }

    # Tag Bayer models with provider if missing
    all_models = [
        {**m, "provider": m.get("provider", "bayer")} for m in live
    ]

    return {
        "models": all_models,
        "defaults": defaults,
        "google_enabled": bool(GOOGLE_API_KEY),
    }


@app.get("/api/models/google")
async def discover_google_models():
    """Live discovery of available Google AI Studio models."""
    if not GOOGLE_API_KEY:
        return {"models": [], "error": "GOOGLE_API_KEY not configured in .env"}
    from .google_provider import list_google_models
    models = await list_google_models()
    return {"models": models, "count": len(models)}


@app.post("/api/models/sync")
async def trigger_model_sync():
    """Manually trigger a model sync from the MyGenAssist catalog."""
    summary = await sync_models()
    return summary


@app.get("/api/models/sync-status")
async def model_sync_status():
    """Get the current model sync status and last sync time."""
    return get_sync_status()


@app.post("/api/enhance-prompt")
async def enhance_prompt(request: EnhancePromptRequest):
    """
    Enhance a user's prompt to be more specific, detailed, and effective.
    Uses a fast model (gemini-2.5-flash) to generate an improved version.
    """
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Prompt content is required")

    enhance_system = """You are an expert prompt engineer for a pharmaceutical research LLM council. Your job is to MODESTLY improve a user's prompt — not to inflate or fabricate.

CRITICAL RULES:
1. NEVER invent context that is not in the original prompt. If the user asks about something you do not recognise, do NOT assume it is a drug, protein, algorithm, or anything else — keep the question as-is and only add minor clarifying structure.
2. Keep enhanced prompts PROPORTIONAL to the original length. A one-sentence question should become at most 2-3 sentences. Never turn a 5-word question into a paragraph.
3. If the topic is clearly pharmaceutical/scientific, you may add relevant dimensions (mechanism of action, safety profile, clinical evidence, regulatory status) — but only dimensions that actually apply.
4. If the topic is unknown, ambiguous, or not scientific, improve ONLY clarity and specificity. Do not force it into a scientific frame.
5. PRESERVE the user's actual intent and wording. Do not replace their terminology with synonyms or generalisations.
6. Do NOT add boilerplate phrases like "Provide a comprehensive scientific and technical elucidation" or "Elaborate on its utility across stages such as…". Write naturally.
7. Do NOT answer the question — only improve the phrasing.
8. Return ONLY the improved prompt text — no preamble, no explanation, no surrounding quotes.

EXAMPLES:
- Input: "What is metformin?" → "What is metformin, including its mechanism of action, primary indications, and key safety considerations?"
- Input: "What is clawdbot?" → "What is clawdbot?"  (unknown term — return as-is or nearly as-is)
- Input: "Compare SGLT2 inhibitors" → "Compare the major SGLT2 inhibitors (empagliflozin, dapagliflozin, canagliflozin) in terms of cardiovascular outcomes, renal benefits, and safety profiles based on recent clinical trial data."
- Input: "Tell me a joke" → "Tell me a joke"  (off-topic — return as-is)"""

    messages = [
        {"role": "system", "content": enhance_system},
        {"role": "user", "content": f"Enhance this prompt (follow the critical rules strictly):\n\n{request.content}"}
    ]

    try:
        response = await query_model("gemini-2.5-flash", messages, timeout=30.0)
        if response and response.get('content'):
            enhanced = response['content'].strip().strip('"\'')
            return {
                "original": request.content,
                "enhanced": enhanced,
            }
        else:
            raise HTTPException(status_code=502, detail="Failed to generate enhanced prompt")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error enhancing prompt: {e}")
        raise HTTPException(status_code=502, detail="Failed to enhance prompt")


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(user_id: str = Depends(get_authenticated_user_id)):
    """List all conversations for the authenticated user (metadata only)."""
    return storage.list_conversations(user_id)


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(user_id, conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.get("/api/conversations/{conversation_id}/export")
async def export_conversation(conversation_id: str, user_id: str = Depends(get_authenticated_user_id), format: str = "markdown"):
    """
    Export a conversation in the specified format.
    
    Args:
        conversation_id: The conversation ID
        format: Export format - 'markdown' or 'json' (default: markdown)
    
    Returns:
        The conversation in the requested format
    """
    conversation = storage.get_conversation(user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if format == "json":
        return {
            "filename": f"{conversation['title']}.json",
            "content": json.dumps(conversation, indent=2),
            "content_type": "application/json"
        }
    
    # Default to Markdown format
    md_lines = [
        f"# {conversation['title']}",
        f"",
        f"**Created:** {conversation['created_at']}",
        f"",
        "---",
        ""
    ]
    
    for msg in conversation["messages"]:
        if msg["role"] == "user":
            md_lines.append(f"## 🧑 User")
            md_lines.append(f"")
            md_lines.append(msg["content"])
            md_lines.append("")
        else:
            # Assistant message with stages
            md_lines.append("## 🤖 Council Response")
            md_lines.append("")
            
            # Stage 1 - Individual Responses
            if "stage1" in msg and msg["stage1"]:
                md_lines.append("### Stage 1: Individual Model Responses")
                md_lines.append("")
                for response in msg["stage1"]:
                    md_lines.append(f"**{response['model']}:**")
                    md_lines.append(f"")
                    md_lines.append(response.get("response", "No response"))
                    md_lines.append("")
            
            # Stage 2 - Rankings
            if "stage2" in msg and msg["stage2"]:
                md_lines.append("### Stage 2: Peer Rankings")
                md_lines.append("")
                for ranking in msg["stage2"]:
                    md_lines.append(f"**{ranking['model']}:**")
                    md_lines.append(f"")
                    md_lines.append(ranking.get("response", "No ranking"))
                    md_lines.append("")
            
            # Stage 3 - Final Synthesis
            if "stage3" in msg and msg["stage3"]:
                md_lines.append("### Stage 3: Chairman's Final Synthesis")
                md_lines.append("")
                md_lines.append(f"**{msg['stage3'].get('model', 'Chairman')}:**")
                md_lines.append("")
                md_lines.append(msg["stage3"].get("response", "No synthesis"))
                md_lines.append("")
            
            md_lines.append("---")
            md_lines.append("")
    
    return {
        "filename": f"{conversation['title']}.md",
        "content": "\n".join(md_lines),
        "content_type": "text/markdown"
    }


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest, user_id: str = Depends(get_authenticated_user_id)):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Scope memory to this user
    set_memory_user(user_id)
    # Check if conversation exists
    conversation = storage.get_conversation(user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(user_id, conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(user_id, conversation_id, title)

    # Run the 3-stage council process with user preferences
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content,
        council_models=request.council_models,
        chairman_model=request.chairman_model
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        user_id,
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Delete a conversation."""
    success = storage.delete_conversation(user_id, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


@app.post("/api/conversations/{conversation_id}/analyze-agents")
async def analyze_agents(conversation_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Run agent team analysis on-demand for an existing conversation.

    Useful for conversations that were created before agent-team
    persistence was added, or when the original analysis failed.
    """
    set_memory_user(user_id)
    conv = storage.get_conversation(user_id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Find the last assistant message
    msgs = conv.get("messages", [])
    last_assistant = None
    for msg in reversed(msgs):
        if msg.get("role") == "assistant":
            last_assistant = msg
            break

    if not last_assistant:
        raise HTTPException(status_code=400, detail="No assistant message found")

    stage1 = last_assistant.get("stage1", [])
    stage2 = last_assistant.get("stage2", [])
    stage3 = last_assistant.get("stage3", {})
    meta = last_assistant.get("metadata", {})

    if not stage1 or not stage3:
        raise HTTPException(status_code=400, detail="Incomplete conversation data")

    # Find the user query
    last_user = None
    for msg in reversed(msgs):
        if msg.get("role") == "user":
            last_user = msg
            break

    user_query = last_user.get("content", "") if last_user else ""

    # Run agent team
    try:
        result = await run_agent_team(
            user_query=user_query,
            stage1_results=stage1,
            stage2_results=stage2,
            stage3_result=stage3,
            aggregate_rankings=meta.get("aggregate_rankings", []),
            grounding_scores=meta.get("grounding_scores", {}),
            evidence_bundle=meta.get("evidence"),
            cost_summary=None,
        )
    except Exception as e:
        logger.error(f"On-demand agent analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Persist to storage
    try:
        storage.update_last_message_metadata(
            user_id, conversation_id, {"agent_team": result}
        )
    except Exception as e:
        logger.warning(f"Failed to persist on-demand agent_team: {e}")

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Kill Switch & Health Monitoring API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class KillSessionRequest(BaseModel):
    """Request to kill a specific session."""
    session_id: str
    reason: str = "User triggered kill switch"


class GlobalHaltRequest(BaseModel):
    """Request to activate global emergency halt."""
    reason: str = "Emergency halt triggered by user"


@app.post("/api/kill-switch/session")
async def kill_session(request: KillSessionRequest):
    """
    Kill Switch — abort a specific in-flight council session.
    This is the PRIMARY user-facing kill switch.
    """
    killed = kill_switch.kill_session(request.session_id, request.reason)
    if killed:
        return {
            "status": "killed",
            "session_id": request.session_id,
            "reason": request.reason,
        }
    raise HTTPException(
        status_code=404,
        detail=f"Session {request.session_id} not found or already completed",
    )


@app.post("/api/kill-switch/halt")
async def global_halt(request: GlobalHaltRequest):
    """
    Emergency Global Halt — kill ALL active sessions and block new ones.
    Use only in emergencies.
    """
    kill_switch.global_halt(request.reason)
    return {
        "status": "halted",
        "reason": request.reason,
        "sessions_killed": kill_switch.status()["active_session_count"],
    }


@app.post("/api/kill-switch/release")
async def release_halt():
    """Release global halt so new sessions can proceed."""
    kill_switch.release_global_halt()
    return {"status": "released"}


@app.get("/api/kill-switch/status")
async def get_kill_switch_status():
    """Get current kill switch status (active sessions, halt state)."""
    return kill_switch.status()


@app.get("/api/health")
async def get_system_health():
    """
    Full system health: kill switch state, circuit breaker per-model status,
    recent self-healing actions taken, and security configuration.
    """
    status = health_monitor.full_status()
    status["security"] = get_security_status()
    return status


@app.get("/api/health/circuits")
async def get_circuit_status():
    """Get per-model circuit breaker status."""
    return circuit_breaker.status()


@app.post("/api/health/circuits/reset")
async def reset_circuits(model: Optional[str] = None):
    """Reset circuit breaker for a specific model or all models."""
    circuit_breaker.reset(model)
    return {
        "status": "reset",
        "model": model or "all",
    }


# ────────────────────────────────────────────────────────────────────────
# A2A Agent Card Discovery (/.well-known/agent-card.json)
# ────────────────────────────────────────────────────────────────────────

_WELLKNOWN_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".well-known")


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    """A2A protocol discovery endpoint — returns the main council agent card."""
    card_path = os.path.join(_WELLKNOWN_DIR, "agent-card.json")
    if not os.path.exists(card_path):
        raise HTTPException(status_code=404, detail="Agent card not found")
    return _load_json(card_path)


@app.get("/api/agent-cards")
async def list_agent_cards():
    """List all individual agent cards (core + VP)."""
    agents_dir = os.path.join(_WELLKNOWN_DIR, "agents")
    if not os.path.isdir(agents_dir):
        return {"agents": []}
    cards = []
    for fname in sorted(os.listdir(agents_dir)):
        if fname.endswith(".json"):
            cards.append(_load_json(os.path.join(agents_dir, fname)))
    return {"agents": cards, "count": len(cards)}


@app.get("/api/agent-cards/{agent_id}")
async def get_individual_agent_card(agent_id: str):
    """Get a specific agent card by ID (e.g. 'research-analyst')."""
    card_path = os.path.join(_WELLKNOWN_DIR, "agents", f"{agent_id}.json")
    if not os.path.exists(card_path):
        raise HTTPException(status_code=404, detail=f"Agent card '{agent_id}' not found")
    return _load_json(card_path)


@app.get("/api/agent-cards-download")
async def download_agent_cards():
    """Download the full A2A agent card bundle as a single JSON file."""
    from fastapi.responses import Response

    # Load the main council card
    main_card_path = os.path.join(_WELLKNOWN_DIR, "agent-card.json")
    main_card = _load_json(main_card_path) if os.path.exists(main_card_path) else {}

    # Load all individual agent cards
    agents_dir = os.path.join(_WELLKNOWN_DIR, "agents")
    agent_cards = []
    if os.path.isdir(agents_dir):
        for fname in sorted(os.listdir(agents_dir)):
            if fname.endswith(".json"):
                agent_cards.append(_load_json(os.path.join(agents_dir, fname)))

    bundle = {
        "a2a_protocol_version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "council": main_card,
        "agents": agent_cards,
        "agent_count": len(agent_cards),
    }

    content = json.dumps(bundle, indent=2, ensure_ascii=False)
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="llm-council-agent-cards.json"'
        },
    )


# ────────────────────────────────────────────────────────────────────────
# Memory Management API
# ────────────────────────────────────────────────────────────────────────

class MemoryDecisionRequest(BaseModel):
    decision: str  # "learn" | "unlearn"
    memory_type: str  # "semantic" | "episodic" | "procedural"
    memory_id: str
    reason: Optional[str] = ""


@app.get("/api/memory/stats")
async def get_memory_stats(user_id: str = Depends(get_authenticated_user_id)):
    """Get memory statistics across all three tiers for the current user."""
    set_memory_user(user_id)
    mm = get_memory_manager()
    return mm.stats()


@app.get("/api/memory/{memory_type}")
async def list_memories(memory_type: str, include_unlearned: bool = False, user_id: str = Depends(get_authenticated_user_id)):
    """List all memories for a given type (semantic, episodic, procedural), scoped to user."""
    set_memory_user(user_id)
    mm = get_memory_manager()
    if memory_type == "semantic":
        return mm.semantic.list_all(include_unlearned=include_unlearned)
    elif memory_type == "episodic":
        return mm.episodic.list_all(include_unlearned=include_unlearned)
    elif memory_type == "procedural":
        return mm.procedural.list_all(include_unlearned=include_unlearned)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown memory type: {memory_type}")


@app.get("/api/memory/{memory_type}/{memory_id}")
async def get_memory_entry(memory_type: str, memory_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Get a specific memory entry, scoped to user."""
    set_memory_user(user_id)
    from .memory_store import get_memory_backend
    backend = get_memory_backend()
    doc = backend.get(memory_type, memory_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return doc


@app.post("/api/memory/decision")
async def apply_memory_decision(request: MemoryDecisionRequest, user_id: str = Depends(get_authenticated_user_id)):
    """Apply a learn/unlearn decision from the user."""
    set_memory_user(user_id)
    result = await user_gate_agent(
        decision=request.decision,
        memory_type=request.memory_type,
        memory_id=request.memory_id,
        reason=request.reason or "",
    )
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Memory entry not found or invalid decision")
    return result


@app.get("/api/memory/search/{memory_type}")
async def search_memories(memory_type: str, q: str, limit: int = 10, user_id: str = Depends(get_authenticated_user_id)):
    """Search memories by text query, scoped to user."""
    set_memory_user(user_id)
    from .memory_store import get_memory_backend
    backend = get_memory_backend()
    return backend.search(memory_type, q, limit=limit)


@app.delete("/api/memory/{memory_type}/{memory_id}")
async def delete_memory_entry(memory_type: str, memory_id: str, user_id: str = Depends(get_authenticated_user_id)):
    """Permanently delete a memory entry, scoped to user."""
    set_memory_user(user_id)
    from .memory_store import get_memory_backend
    backend = get_memory_backend()
    if backend.delete(memory_type, memory_id):
        return {"status": "deleted", "memory_type": memory_type, "memory_id": memory_id}
    raise HTTPException(status_code=404, detail="Memory entry not found")


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest, user_id: str = Depends(get_authenticated_user_id)):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    Supports file attachments (PDF, PPTX, XLSX, DOCX).
    """
    # Check if conversation exists
    conversation = storage.get_conversation(user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Validate attachments
    for attachment in request.attachments:
        error = validate_attachment(attachment)
        if error:
            raise HTTPException(status_code=400, detail=error)

    # Build augmented content with file attachments info
    augmented_content = request.content
    if request.attachments:
        attachment_descriptions = [
            extract_file_content_description(att) for att in request.attachments
        ]
        if augmented_content:
            augmented_content = f"{augmented_content}\n\n---\nAttached Files:\n" + "\n".join(attachment_descriptions)
        else:
            augmented_content = "Please analyze the following attached files:\n" + "\n".join(attachment_descriptions)

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0
    
    # Get user preferences for council/chairman
    user_council_models = request.council_models
    user_chairman_model = request.chairman_model
    web_search_enabled = request.web_search_enabled

    # Generate a unique session ID for kill switch tracking
    session_id = f"{conversation_id}:{uuid.uuid4().hex[:8]}"

    # ── Keep-Alive wrapper ──────────────────────────────────────────
    # Corporate proxies (Zscaler, Netskope) often kill idle SSE
    # connections after ~60-120s.  We send SSE comment pings every
    # 10s to keep the TCP socket alive during long model calls.

    async def with_keepalive(inner_gen, interval=10):
        """
        Wrap an async generator so that a ': keepalive\\n\\n' SSE
        comment is emitted whenever `interval` seconds elapse between
        real data frames.

        Uses asyncio.create_task so that the inner generator's
        __anext__() is never cancelled — asyncio.wait_for would
        cancel it on timeout, corrupting the generator state.
        """
        inner_iter = inner_gen.__aiter__()
        pending_next = None          # the Task for __anext__()

        while True:
            if pending_next is None:
                pending_next = asyncio.ensure_future(inner_iter.__anext__())

            done, _ = await asyncio.wait({pending_next}, timeout=interval)

            if done:
                # The inner generator yielded a value (or raised)
                task = pending_next
                pending_next = None
                try:
                    yield task.result()          # may raise StopAsyncIteration
                except StopAsyncIteration:
                    break
            else:
                # Timeout — inner gen is still working; send keepalive
                yield ": keepalive\n\n"

    async def event_generator():
        nonlocal augmented_content
        # Register with kill switch
        kill_event = kill_switch.register_session(session_id)
        cost_tracker = SessionCostTracker()
        # Scope all memory operations to this user
        set_memory_user(user_id)
        try:
            # Emit session ID so the frontend can target the kill switch
            yield f"data: {json.dumps({'type': 'session_start', 'data': {'session_id': session_id}})}\n\n"

            # Check global halt before starting
            if kill_switch.is_halted:
                yield f"data: {json.dumps({'type': 'error', 'message': 'System is in emergency halt mode. Please try again later.', 'code': 'GLOBAL_HALT'})}\n\n"
                return

            # ── Prompt Suitability Guard ─────────────────────────────
            # Block unsuitable prompts before any stage is triggered.
            # If conversation was already blocked, reject all follow-ups.
            if conversation.get("blocked"):
                yield f"data: {json.dumps({'type': 'prompt_rejected', 'data': {'category': 'CONVERSATION_BLOCKED', 'message': 'This conversation has been closed due to a policy violation. Please start a **new conversation** with a question related to pharmaceutical sciences, clinical research, or life-science topics.'}})}\n\n"
                return

            # ── OPT-1: Prompt Guard ∥ Pre-Stage 1 Memory Recall ──────
            # Fire both in parallel — memory recall is read-only so safe
            # to discard if the guard rejects the prompt.
            # Include attachment filenames/descriptions in guard input
            # so image/file names like 'forensic medicine.png' provide
            # topic context for the relevance check.
            guard_input = request.content or ""
            if request.attachments:
                att_names = [att.name for att in request.attachments if att.name]
                if att_names:
                    guard_input = f"{guard_input} [Attachments: {', '.join(att_names)}]"
            guard_task = asyncio.create_task(evaluate_prompt(guard_input))
            memory_task = asyncio.create_task(pre_stage1_agent(augmented_content, conversation_id))

            guard_verdict = await guard_task
            if not guard_verdict.allowed:
                memory_task.cancel()  # discard memory work
                # Mark conversation as blocked so no follow-ups are accepted
                conversation["blocked"] = True
                conversation["blocked_reason"] = guard_verdict.category
                storage.save_conversation(user_id, conversation)
                storage_content_early = request.content or ""
                storage.add_user_message(user_id, conversation_id, storage_content_early)
                yield f"data: {json.dumps({'type': 'prompt_rejected', 'data': {'category': guard_verdict.category, 'message': guard_verdict.message}})}\n\n"
                return

            # Guard passed — await memory recall result
            memory_gate = await memory_task
            if memory_gate.get("memory_context"):
                augmented_content = memory_gate["augmented_query"]
            memory_recall_data = {k: v for k, v in memory_gate.items() if k != 'memory_context' and k != 'augmented_query'}
            yield f"data: {json.dumps({'type': 'memory_recall', 'data': memory_recall_data})}\n\n"

            # Build user message content for storage (include attachment info)
            storage_content = request.content
            if request.attachments:
                attachment_list = [f"📎 {att.name}" for att in request.attachments]
                if storage_content:
                    storage_content = f"{storage_content}\n\n---\nAttachments:\n" + "\n".join(attachment_list)
                else:
                    storage_content = "Attachments:\n" + "\n".join(attachment_list)
            
            # Get existing conversation history for follow-up context
            conversation_history = conversation.get("messages", [])
            
            # Add user message
            storage.add_user_message(user_id, conversation_id, storage_content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses with incremental progress
            # Instead of waiting for all models to finish before emitting
            # any data, we fire individual tasks and yield progress events
            # as each model completes — eliminating the multi-minute dead zone.
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"

            from .config import COUNCIL_MODELS as _COUNCIL_MODELS

            s1_models = user_council_models or _COUNCIL_MODELS
            s1_context = build_conversation_context(conversation_history)
            s1_query = f"{s1_context}Current question (follow-up): {augmented_content}" if s1_context else augmented_content
            s1_messages = [{"role": "user", "content": s1_query}]

            # Kill switch gate
            if session_id and kill_switch.is_session_killed(session_id):
                raise KillSwitchError(f"Session {session_id} killed before Stage 1")

            # Fire all model queries as individual tasks (max_retries=1
            # since the self-healing fallback mechanism already substitutes
            # a different model on failure — no need for 2 retries + 4.5s
            # of backoff delay per failing model).
            pending_tasks = {}
            for model in s1_models:
                task = asyncio.create_task(
                    query_model(model, s1_messages,
                                web_search_enabled=web_search_enabled,
                                session_id=session_id,
                                max_retries=1)
                )
                pending_tasks[task] = model

            stage1_results = []
            s1_failed_models = []
            s1_used_models = set(s1_models)
            s1_total = len(s1_models)

            while pending_tasks:
                done, _ = await asyncio.wait(
                    pending_tasks.keys(), return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    model = pending_tasks.pop(task)
                    try:
                        response = task.result()
                        if response is not None:
                            result_item = {
                                "model": model,
                                "response": response.get('content', ''),
                                "usage": response.get('usage'),
                            }
                            stage1_results.append(result_item)
                            yield f"data: {json.dumps({'type': 'stage1_model_complete', 'data': result_item, 'progress': {'completed': len(stage1_results), 'failed': len(s1_failed_models), 'total': s1_total}})}\n\n"
                        else:
                            s1_failed_models.append(model)
                    except Exception as e:
                        logger.error(f"[Stage1] {model} raised: {e}")
                        circuit_breaker.record_failure(model, str(e))
                        s1_failed_models.append(model)

            # Self-healing: attempt fallback models for any that failed
            if s1_failed_models and len(stage1_results) < len(s1_models):
                logger.info(f"[Stage1] {len(s1_failed_models)} model(s) failed, attempting fallbacks...")
                for failed_model in s1_failed_models:
                    if session_id and kill_switch.is_session_killed(session_id):
                        raise KillSwitchError(f"Session {session_id} killed during Stage 1 fallback")
                    fallback = resolve_fallback(failed_model, s1_used_models)
                    if fallback:
                        s1_used_models.add(fallback)
                        fb_response = await query_model(
                            fallback, s1_messages,
                            web_search_enabled=web_search_enabled,
                            session_id=session_id,
                        )
                        if fb_response is not None:
                            result_item = {
                                "model": f"{fallback} (fallback for {failed_model})",
                                "response": fb_response.get('content', ''),
                                "usage": fb_response.get('usage'),
                            }
                            stage1_results.append(result_item)
                            health_monitor.log_healing_action("stage1_fallback_success", {
                                "failed_model": failed_model, "fallback_model": fallback,
                            })
                            yield f"data: {json.dumps({'type': 'stage1_model_complete', 'data': result_item, 'progress': {'completed': len(stage1_results), 'failed': len(s1_failed_models), 'total': s1_total}})}\n\n"
                        else:
                            health_monitor.log_healing_action("stage1_fallback_failed", {
                                "failed_model": failed_model, "fallback_model": fallback,
                            })

            # Quorum check
            if not check_quorum(stage1_results, "Stage 1", MIN_STAGE1_QUORUM):
                health_monitor.log_healing_action("stage1_quorum_failure", {
                    "successful": len(stage1_results), "required": MIN_STAGE1_QUORUM,
                })
                raise QuorumError(
                    f"Stage 1 quorum not met: got {len(stage1_results)}, need {MIN_STAGE1_QUORUM}"
                )

            # Record Stage 1 token usage
            for r in stage1_results:
                cost_tracker.record("stage1", r["model"], r.get("usage"))
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Kill switch check between stages
            if kill_switch.is_session_killed(session_id):
                yield f"data: {json.dumps({'type': 'killed', 'message': 'Council session aborted by user.'})}\n\n"
                return

            # ── OPT-3: Incremental Stage 2 — stream each ranking as it arrives ──
            # Also fires evidence retrieval in parallel with Stage 2.
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            evidence_task = asyncio.create_task(run_evidence_skills(augmented_content, web_search_enabled=web_search_enabled))

            # Build Stage 2 prompt (same logic as stage2_collect_rankings but inline)
            _s2_models = user_council_models or COUNCIL_MODELS
            _s2_labels = [chr(65 + i) for i in range(len(stage1_results))]
            label_to_model = {
                f"Response {label}": result['model']
                for label, result in zip(_s2_labels, stage1_results)
            }
            _s2_context = build_conversation_context(conversation_history)
            _s2_context_note = f"\nNote: This is a follow-up question in an ongoing conversation.\n{_s2_context}\n" if _s2_context else ""
            _s2_responses_text = "\n\n".join([
                f"Response {label}:\n{result['response']}"
                for label, result in zip(_s2_labels, stage1_results)
            ])
            _s2_ranking_prompt = f"""You are a pharmaceutical domain expert evaluating different responses to the following question:
{_s2_context_note}
Question: {augmented_content}

Here are the responses from different models (anonymized):

{_s2_responses_text}

═══════════════════════════════════════════════════════════
PART 1 — RUBRIC EVALUATION (Verbalized Sampling)
═══════════════════════════════════════════════════════════
For EACH response, provide a score from 0 to 10 on each criterion below.
After each score, give a brief justification (1-2 sentences).

Criteria:
  • Relevancy (0-10): How directly and completely the response addresses the original question
  • Faithfulness (0-10): Factual accuracy, absence of hallucinations, grounded in evidence
  • Context Recall (0-10): Coverage of key concepts, dimensions, and nuances raised across all responses
  • Output Quality (0-10): Clarity, structure, depth, readability, and overall coherence
  • Consensus (0-10): Would other domain experts broadly agree with the claims made?

Format EXACTLY as follows for each response:

RUBRIC Response X:
  Relevancy: <score>/10 — <justification>
  Faithfulness: <score>/10 — <justification>
  Context Recall: <score>/10 — <justification>
  Output Quality: <score>/10 — <justification>
  Consensus: <score>/10 — <justification>

═══════════════════════════════════════════════════════════
PART 2 — CLAIM CLASSIFICATION (Pharma Safety)
═══════════════════════════════════════════════════════════
For EACH response, classify its major claims in pharmaceutical context:
  TP (True Positive)  = Correct, verifiable claim relevant to the question
  FP (False Positive) = Incorrect, misleading, or hallucinated claim
  FN (False Negative) = Important information the response FAILED to mention

Format EXACTLY as follows for each response:

CLAIMS Response X:
  TP: <count> — <brief summary of correct claims>
  FP: <count> — <brief summary of incorrect/hallucinated claims, or "None detected">
  FN: <count> — <brief summary of important omissions, or "None detected">

═══════════════════════════════════════════════════════════
PART 3 — FINAL RANKING
═══════════════════════════════════════════════════════════
Based on your rubric evaluation and claim analysis above, provide
your final ranking from best to worst.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")

Now provide your complete evaluation:"""
            _s2_messages = [{"role": "user", "content": _s2_ranking_prompt}]

            _s2_tasks = {
                asyncio.create_task(
                    query_model(m, _s2_messages, web_search_enabled=web_search_enabled, session_id=session_id)
                ): m
                for m in _s2_models
            }
            stage2_results = []
            _s2_pending = set(_s2_tasks.keys())
            _s2_total = len(_s2_models)

            while _s2_pending:
                done, _s2_pending = await asyncio.wait(_s2_pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    model_name = _s2_tasks[task]
                    try:
                        resp = task.result()
                        if resp is not None:
                            full_text = resp.get('content', '')
                            parsed = parse_ranking_from_text(full_text)
                            rubric = parse_rubric_scores(full_text)
                            claims = parse_claim_counts(full_text)
                            result_item = {
                                "model": model_name,
                                "ranking": full_text,
                                "parsed_ranking": parsed,
                                "rubric_scores": rubric,
                                "claim_counts": claims,
                                "usage": resp.get('usage'),
                            }
                            stage2_results.append(result_item)
                            cost_tracker.record("stage2", model_name, resp.get('usage'))
                            yield f"data: {json.dumps({'type': 'stage2_model_response', 'data': result_item, 'progress': {'completed': len(stage2_results), 'total': _s2_total}})}\n\n"
                    except Exception as e:
                        logger.error(f"[Stage2-Incremental] {model_name} failed: {e}")

            if len(stage2_results) < MIN_STAGE2_QUORUM:
                raise QuorumError(f"Stage 2 quorum not met: got {len(stage2_results)}, need {MIN_STAGE2_QUORUM}")

            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            # Compute grounding scores
            grounding_scores = compute_response_grounding_scores(
                stage2_results, label_to_model, aggregate_rankings
            )
            # Await evidence retrieval (should be done by now — ran during Stage 2)
            evidence_bundle = await evidence_task
            yield f"data: {json.dumps({'type': 'evidence_complete', 'data': evidence_bundle})}\n\n"
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings, 'grounding_scores': grounding_scores}})}\n\n"

            # ── Stage 2.5: Relevancy Gate ────────────────────────────
            relevancy_gate = compute_relevancy_gate(stage2_results)
            gated_labels = [lbl for lbl, g in relevancy_gate.items() if g.get("gated_out")]
            yield f"data: {json.dumps({'type': 'relevancy_gate', 'data': {'gate': relevancy_gate, 'gated_labels': gated_labels}})}\n\n"

            # Kill switch check between stages
            if kill_switch.is_session_killed(session_id):
                yield f"data: {json.dumps({'type': 'killed', 'message': 'Council session aborted by user.'})}\n\n"
                return

            # ── OPT-4: Post-Stage 2 ∥ Stage 3 Start ─────────────────
            # Stage 3 does NOT depend on post_stage2_agent output.
            # Fire Stage 3 + CA validation + post_stage2 ALL in parallel
            # so the chairman LLM call starts immediately.
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            evidence_text = format_citations_for_prompt(evidence_bundle)

            # Fire CA validation pass in parallel with Stage 3 (lightweight probes)
            ca_validation_task = asyncio.create_task(
                stage2_ca_validation_pass(
                    augmented_content,
                    stage1_results,
                    label_to_model,
                    user_council_models,
                    web_search_enabled,
                    session_id=session_id,
                )
            )

            # Fire Stage 3 as a task so it starts immediately
            stage3_task = asyncio.create_task(
                stage3_synthesize_final(
                    augmented_content, stage1_results, stage2_results,
                    user_chairman_model, conversation_history, web_search_enabled,
                    session_id=session_id,
                    evidence_context=evidence_text,
                    relevancy_gate=relevancy_gate,
                )
            )

            # Fire post-Stage 2 agent in parallel (doesn't block Stage 3)
            post_stage2_task = asyncio.create_task(
                post_stage2_agent(
                    augmented_content, grounding_scores, aggregate_rankings
                )
            )

            # Await post-Stage 2 (fast memory lookup, emits SSE while Stage 3 runs)
            stage2_gate = await post_stage2_task
            yield f"data: {json.dumps({'type': 'memory_gate', 'data': stage2_gate})}\n\n"

            # Kill switch check (cancel running tasks if killed)
            if kill_switch.is_session_killed(session_id):
                stage3_task.cancel()
                ca_validation_task.cancel()
                yield f"data: {json.dumps({'type': 'killed', 'message': 'Council session aborted by user.'})}\n\n"
                return

            # Await Stage 3 (already running in background)
            stage3_result = await stage3_task
            # Record Stage 3 token usage
            cost_tracker.record("stage3", stage3_result.get("model", "unknown"), stage3_result.get("usage"))

            # Await CA validation (should be done — ran during Stage 3)
            try:
                ca_validation_results = await ca_validation_task
                if ca_validation_results:
                    # Record CA validation token usage
                    for model_name, val_data in ca_validation_results.items():
                        if val_data.get("usage"):
                            cost_tracker.record("ca_validation", model_name, val_data["usage"])
                    # Enhance grounding scores with multi-round CA data
                    grounding_scores = enhance_ca_with_validation(
                        grounding_scores, ca_validation_results, label_to_model
                    )
                    yield f"data: {json.dumps({'type': 'ca_validation_complete', 'data': {'models_probed': len(ca_validation_results), 'grounding_scores': grounding_scores}})}\n\n"
                    logger.info(f"[CA Validation] Enhanced CA for {len(ca_validation_results)} models")

                    # Persist CA snapshots for cross-session tracking
                    try:
                        memory_mgr = get_memory_manager()
                        for resp in grounding_scores.get("per_response", []):
                            ca = resp.get("context_awareness")
                            if ca and ca.get("score") is not None:
                                memory_mgr.store_ca_snapshot(
                                    conversation_id=conversation_id,
                                    model=resp["model"],
                                    ca_data=ca,
                                )
                    except Exception as e:
                        logger.debug(f"[CA Tracking] Non-fatal persistence error: {e}")
            except Exception as e:
                logger.warning(f"[CA Validation] Non-fatal error: {e}")
                # Continue without enhanced CA — original grounding_scores remain

            # Extract infographic data from the chairman's response
            infographic_data = None
            raw_response = stage3_result.get("response", "")
            infographic_data = extract_infographic(raw_response)
            # Strip the raw infographic JSON block from the displayed response
            stage3_result["response"] = strip_infographic_block(raw_response)

            # ── Citation Supervisor: enrich references with clickable links ──
            stage3_result["response"] = enrich_stage3_citations(
                stage3_result["response"]
            )

            # ── Citation Validator: verify URLs are reachable, fix broken ones ──
            try:
                stage3_result["response"] = await validate_and_fix_citations(
                    stage3_result["response"]
                )
            except Exception as e:
                logger.warning(f"[Citation Validator] Non-fatal error: {e}")

            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Emit infographic data as a separate event
            if infographic_data:
                yield f"data: {json.dumps({'type': 'infographic_complete', 'data': infographic_data})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(user_id, conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message (including metadata for reload)
            storage.add_assistant_message(
                user_id,
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                metadata={
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate_rankings,
                    "grounding_scores": grounding_scores,
                    "evidence": evidence_bundle,
                    "infographic": infographic_data,
                    "memory_recall": memory_recall_data,
                    "memory_gate": stage2_gate,
                    "relevancy_gate": relevancy_gate,
                },
            )

            # Emit cost summary before completion
            cost_summary = cost_tracker.compute_summary()
            yield f"data: {json.dumps({'type': 'cost_summary', 'data': cost_summary})}\n\n"

            # ── OPT-5: Agent Team ∥ Post-Stage 3 Learning ─────────
            # Both are independent of each other — fire in parallel.
            overall_grounding = grounding_scores.get("overall_score", 0) / 100.0

            agent_team_task = asyncio.create_task(
                run_agent_team(
                    user_query=augmented_content,
                    stage1_results=stage1_results,
                    stage2_results=stage2_results,
                    stage3_result=stage3_result,
                    aggregate_rankings=aggregate_rankings,
                    grounding_scores=grounding_scores,
                    evidence_bundle=evidence_bundle,
                    cost_summary=cost_summary,
                    web_search_enabled=web_search_enabled,
                )
            )
            learning_task = asyncio.create_task(
                post_stage3_agent(
                    conversation_id=conversation_id,
                    user_query=augmented_content,
                    stage1_results=stage1_results,
                    aggregate_rankings=aggregate_rankings,
                    stage3_result=stage3_result,
                    grounding_score=overall_grounding,
                    cost_summary=cost_summary,
                )
            )

            # Await both (whichever finishes first proceeds; both are fast)
            agent_team_result = None
            learning_gate = None
            try:
                agent_team_result, learning_gate = await asyncio.gather(
                    agent_team_task, learning_task, return_exceptions=True
                )
            except Exception as e:
                logger.warning(f"[Parallel post-pipeline] gather error: {e}")

            # Emit agent team result
            if agent_team_result and not isinstance(agent_team_result, Exception):
                try:
                    yield f"data: {json.dumps({'type': 'agent_team_complete', 'data': agent_team_result})}\n\n"
                    storage.update_last_message_metadata(
                        user_id, conversation_id, {"agent_team": agent_team_result}
                    )
                except Exception:
                    logger.debug("Failed to persist agent_team metadata")
            elif isinstance(agent_team_result, Exception):
                logger.warning(f"[AgentTeam] Non-fatal error: {agent_team_result}")

            # Emit learning decision
            if learning_gate and not isinstance(learning_gate, Exception):
                yield f"data: {json.dumps({'type': 'memory_learning', 'data': learning_gate})}\n\n"
                # Persist memory_learning + cost_summary in conversation metadata
                try:
                    storage.update_last_message_metadata(
                        user_id, conversation_id,
                        {"memory_learning": learning_gate, "cost_summary": cost_summary},
                    )
                except Exception:
                    logger.debug("Failed to persist memory_learning metadata")
            elif isinstance(learning_gate, Exception):
                logger.warning(f"[PostStage3] Non-fatal error: {learning_gate}")
                # Still persist cost_summary even if learning failed
                try:
                    storage.update_last_message_metadata(
                        user_id, conversation_id, {"cost_summary": cost_summary},
                    )
                except Exception:
                    logger.debug("Failed to persist cost_summary metadata")

            # ── OPT-6: User Behaviour Learning + ECA Adaptation ───
            # Non-blocking: record user profile and run adaptation loop.
            try:
                upm = get_user_profile_memory()
                eca = get_eca()

                # Classify the query and record the interaction
                classification = upm.classify_query(augmented_content)
                upm.record_interaction(
                    user_id=user_id,
                    query=augmented_content,
                    grounding_score=overall_grounding,
                    relevancy_violations=gated_labels,
                    gated_labels=gated_labels,
                    classification=classification,
                )

                # Get updated user profile for ECA
                user_profile = upm.get_user_profile(user_id)

                # Run full ECA adaptation (Memory × Skills pairing)
                eca_result = eca.run_full_adaptation(
                    user_id=user_id,
                    user_profile=user_profile,
                    evidence_bundle=evidence_bundle,
                    grounding_scores=grounding_scores,
                    grounding_score_overall=overall_grounding,
                )

                # Emit user behaviour + ECA event
                yield f"data: {json.dumps({'type': 'user_behaviour_update', 'data': {'profile': user_profile, 'eca': eca_result, 'classification': classification}})}\n\n"

                # Persist ECA state in conversation metadata
                storage.update_last_message_metadata(
                    user_id, conversation_id,
                    {"user_profile": user_profile, "eca_adaptation": eca_result, "relevancy_gate": relevancy_gate},
                )
                logger.info(
                    f"[UserBehaviour+ECA] Complete for {user_id}: "
                    f"domain={classification['domain']}, ema_reward={eca_result.get('ema_reward', 0):.3f}"
                )
            except Exception as e:
                logger.warning(f"[UserBehaviour+ECA] Non-fatal error: {e}")

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except KillSwitchError as e:
            # User-triggered abort — graceful termination
            yield f"data: {json.dumps({'type': 'killed', 'message': str(e)})}\n\n"
        except QuorumError as e:
            # Self-healing exhausted — not enough models responded
            yield f"data: {json.dumps({'type': 'error', 'message': f'Self-healing exhausted: {e}', 'code': 'QUORUM_FAILURE'})}\n\n"
        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Always unregister the session from kill switch
            kill_switch.unregister_session(session_id)

    return StreamingResponse(
        with_keepalive(event_generator(), interval=10),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


if __name__ == "__main__":
    import uvicorn

    ssl_certfile = os.getenv("SSL_CERTFILE")
    ssl_keyfile = os.getenv("SSL_KEYFILE")

    uvicorn_kwargs = dict(host="0.0.0.0", port=8001)
    if ssl_certfile and ssl_keyfile:
        uvicorn_kwargs["ssl_certfile"] = ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = ssl_keyfile
        uvicorn_kwargs["ssl_version"] = 2  # TLS 1.3 (ssl.TLS_VERSION_TLSv1_3)
        print("\n🔒 TLS ENABLED — serving over HTTPS")
    else:
        print("\n⚠️  No SSL_CERTFILE/SSL_KEYFILE — serving over plain HTTP (dev mode)")

    uvicorn.run(app, **uvicorn_kwargs)
