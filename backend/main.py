"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio
import base64
from datetime import datetime

from . import storage
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings
from .config import OPENROUTER_API_KEY, AVAILABLE_MODELS, DEFAULT_COUNCIL_MODELS, DEFAULT_CHAIRMAN_MODEL
from .openrouter import query_model
from .resilience import (
    kill_switch,
    circuit_breaker,
    health_monitor,
    KillSwitchError,
    QuorumError,
)
from .grounding import compute_response_grounding_scores, get_rubric_criteria
from .skills import run_evidence_skills, format_citations_for_prompt
from .token_tracking import SessionCostTracker
from .memory import get_memory_manager
from .orchestrator import (
    pre_stage1_agent,
    post_stage2_agent,
    post_stage3_agent,
    user_gate_agent,
)


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

app = FastAPI(title="LLM Council API")

# Enable CORS for local development (allow multiple Vite ports)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174", 
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:3000",
    ],
    allow_credentials=True,
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


@app.get("/api/models")
async def get_available_models():
    """Get list of available models with their metadata."""
    return {
        "models": AVAILABLE_MODELS,
        "defaults": {
            "council_models": DEFAULT_COUNCIL_MODELS,
            "chairman_model": DEFAULT_CHAIRMAN_MODEL
        }
    }


@app.post("/api/enhance-prompt")
async def enhance_prompt(request: EnhancePromptRequest):
    """
    Enhance a user's prompt to be more specific, detailed, and effective.
    Uses a fast model (gemini-2.5-flash) to generate an improved version.
    """
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Prompt content is required")

    enhance_system = """You are an expert prompt engineer working for a pharmaceutical research council. Your job is to take a user's question and enhance it into a more detailed, specific, and scientifically rigorous prompt that will elicit better responses from LLMs.

Guidelines:
- Preserve the user's original intent completely
- Add relevant scientific dimensions (efficacy, safety, mechanisms, biomarkers, clinical data, preclinical models)
- Make the scope explicit (what comparisons, what endpoints, what contexts)
- Use precise scientific terminology appropriate to the domain
- Keep it as a single, well-structured question or request
- Do NOT answer the question — only improve it
- Return ONLY the improved prompt text, nothing else (no preamble, no explanation, no quotes)"""

    messages = [
        {"role": "system", "content": enhance_system},
        {"role": "user", "content": f"Enhance this prompt:\n\n{request.content}"}
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
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.get("/api/conversations/{conversation_id}/export")
async def export_conversation(conversation_id: str, format: str = "markdown"):
    """
    Export a conversation in the specified format.
    
    Args:
        conversation_id: The conversation ID
        format: Export format - 'markdown' or 'json' (default: markdown)
    
    Returns:
        The conversation in the requested format
    """
    conversation = storage.get_conversation(conversation_id)
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
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process with user preferences
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content,
        council_models=request.council_models,
        chairman_model=request.chairman_model
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
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
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    success = storage.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


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
    and recent self-healing actions taken.
    """
    return health_monitor.full_status()


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
# Memory Management API
# ────────────────────────────────────────────────────────────────────────

class MemoryDecisionRequest(BaseModel):
    decision: str  # "learn" | "unlearn"
    memory_type: str  # "semantic" | "episodic" | "procedural"
    memory_id: str
    reason: Optional[str] = ""


@app.get("/api/memory/stats")
async def get_memory_stats():
    """Get memory statistics across all three tiers."""
    mm = get_memory_manager()
    return mm.stats()


@app.get("/api/memory/{memory_type}")
async def list_memories(memory_type: str, include_unlearned: bool = False):
    """List all memories for a given type (semantic, episodic, procedural)."""
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
async def get_memory_entry(memory_type: str, memory_id: str):
    """Get a specific memory entry."""
    from .memory_store import get_memory_backend
    backend = get_memory_backend()
    doc = backend.get(memory_type, memory_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return doc


@app.post("/api/memory/decision")
async def apply_memory_decision(request: MemoryDecisionRequest):
    """Apply a learn/unlearn decision from the user."""
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
async def search_memories(memory_type: str, q: str, limit: int = 10):
    """Search memories by text query."""
    from .memory_store import get_memory_backend
    backend = get_memory_backend()
    return backend.search(memory_type, q, limit=limit)


@app.delete("/api/memory/{memory_type}/{memory_id}")
async def delete_memory_entry(memory_type: str, memory_id: str):
    """Permanently delete a memory entry (admin action)."""
    from .memory_store import get_memory_backend
    backend = get_memory_backend()
    if backend.delete(memory_type, memory_id):
        return {"status": "deleted", "memory_type": memory_type, "memory_id": memory_id}
    raise HTTPException(status_code=404, detail="Memory entry not found")


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    Supports file attachments (PDF, PPTX, XLSX, DOCX).
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
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
        try:
            # Emit session ID so the frontend can target the kill switch
            yield f"data: {json.dumps({'type': 'session_start', 'data': {'session_id': session_id}})}\n\n"

            # Check global halt before starting
            if kill_switch.is_halted:
                yield f"data: {json.dumps({'type': 'error', 'message': 'System is in emergency halt mode. Please try again later.', 'code': 'GLOBAL_HALT'})}\n\n"
                return
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
            storage.add_user_message(conversation_id, storage_content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # ── Pre-Stage 1 Orchestrator Agent: memory recall ──
            memory_gate = await pre_stage1_agent(augmented_content, conversation_id)
            if memory_gate.get("memory_context"):
                augmented_content = memory_gate["augmented_query"]
            yield f"data: {json.dumps({'type': 'memory_recall', 'data': {k: v for k, v in memory_gate.items() if k != 'memory_context' and k != 'augmented_query'}})}\n\n"

            # Stage 1: Collect responses (use augmented content with attachment info)
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(
                augmented_content, user_council_models, conversation_history,
                web_search_enabled, session_id=session_id,
            )
            # Record Stage 1 token usage
            for r in stage1_results:
                cost_tracker.record("stage1", r["model"], r.get("usage"))
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Kill switch check between stages
            if kill_switch.is_session_killed(session_id):
                yield f"data: {json.dumps({'type': 'killed', 'message': 'Council session aborted by user.'})}\n\n"
                return

            # Stage 2: Collect rankings
            # Also fire evidence retrieval in parallel with Stage 2
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            evidence_task = asyncio.create_task(run_evidence_skills(augmented_content))
            stage2_results, label_to_model = await stage2_collect_rankings(
                augmented_content, stage1_results, user_council_models,
                conversation_history, web_search_enabled, session_id=session_id,
            )
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            # Record Stage 2 token usage
            for r in stage2_results:
                cost_tracker.record("stage2", r["model"], r.get("usage"))
            # Compute grounding scores
            grounding_scores = compute_response_grounding_scores(
                stage2_results, label_to_model, aggregate_rankings
            )
            # Await evidence retrieval (should be done by now — ran during Stage 2)
            evidence_bundle = await evidence_task
            yield f"data: {json.dumps({'type': 'evidence_complete', 'data': evidence_bundle})}\n\n"
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings, 'grounding_scores': grounding_scores}})}\n\n"

            # ── Post-Stage 2 Orchestrator Agent: grounding evaluation ──
            stage2_gate = await post_stage2_agent(
                augmented_content, grounding_scores, aggregate_rankings
            )
            yield f"data: {json.dumps({'type': 'memory_gate', 'data': stage2_gate})}\n\n"

            # Kill switch check between stages
            if kill_switch.is_session_killed(session_id):
                yield f"data: {json.dumps({'type': 'killed', 'message': 'Council session aborted by user.'})}\n\n"
                return

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            evidence_text = format_citations_for_prompt(evidence_bundle)
            stage3_result = await stage3_synthesize_final(
                augmented_content, stage1_results, stage2_results,
                user_chairman_model, conversation_history, web_search_enabled,
                session_id=session_id,
                evidence_context=evidence_text,
            )
            # Record Stage 3 token usage
            cost_tracker.record("stage3", stage3_result.get("model", "unknown"), stage3_result.get("usage"))
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message (including metadata for reload)
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                metadata={
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate_rankings,
                    "grounding_scores": grounding_scores,
                    "evidence": evidence_bundle,
                },
            )

            # Emit cost summary before completion
            cost_summary = cost_tracker.compute_summary()
            yield f"data: {json.dumps({'type': 'cost_summary', 'data': cost_summary})}\n\n"

            # ── Post-Stage 3 Orchestrator Agent: learning decision ──
            # overall_score is 0–100 from grounding.py; orchestrator expects 0–1
            overall_grounding = grounding_scores.get("overall_score", 0) / 100.0
            learning_gate = await post_stage3_agent(
                conversation_id=conversation_id,
                user_query=augmented_content,
                stage1_results=stage1_results,
                aggregate_rankings=aggregate_rankings,
                stage3_result=stage3_result,
                grounding_score=overall_grounding,
                cost_summary=cost_summary,
            )
            yield f"data: {json.dumps({'type': 'memory_learning', 'data': learning_gate})}\n\n"

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
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
