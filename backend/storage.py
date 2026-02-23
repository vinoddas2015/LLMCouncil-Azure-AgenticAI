"""Conversation storage — dual-mode: local files or Azure Blob Storage.

Cloud users  → Azure Blob Storage (container: conversations/{user_id}/{conversation_id}.json)
Local dev    → files (path: data/conversations/local-user/{conversation_id}.json)

The active backend is chosen per-call based on user_id:
  user_id == "local-user"  → file backend
  anything else            → Azure Blob Storage backend
"""

import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from .config import DATA_DIR, AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER, BLOB_CONVERSATIONS_PREFIX
from .security import encrypt_data, decrypt_data, is_encryption_enabled

logger = logging.getLogger(__name__)

LOCAL_USER_ID = "local-user"


def _is_local(user_id: str) -> bool:
    return user_id == LOCAL_USER_ID


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Validation                                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _validate_user_id(user_id: str) -> str:
    """Sanitise and validate user_id to prevent path-traversal attacks."""
    uid = user_id.strip()
    if not uid or "/" in uid or "\\" in uid or ".." in uid:
        raise ValueError(f"Invalid user_id: {user_id!r}")
    return uid


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Azure Blob Storage Backend                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝

_blob_service_client = None


def _get_blob_service():
    """Lazy-initialised Azure Blob Storage client (created once per process)."""
    global _blob_service_client
    if _blob_service_client is None:
        from azure.storage.blob import BlobServiceClient
        _blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    return _blob_service_client


def _get_container_client():
    """Get the container client for conversations."""
    return _get_blob_service().get_container_client(AZURE_STORAGE_CONTAINER)


def _blob_name(user_id: str, conversation_id: str) -> str:
    return f"{BLOB_CONVERSATIONS_PREFIX}/{user_id}/{conversation_id}.json"


def _blob_user_prefix(user_id: str) -> str:
    return f"{BLOB_CONVERSATIONS_PREFIX}/{user_id}/"


def _blob_put(user_id: str, conversation_id: str, data: Dict[str, Any]):
    container = _get_container_client()
    container.upload_blob(
        name=_blob_name(user_id, conversation_id),
        data=json.dumps(data, indent=2).encode("utf-8"),
        overwrite=True,
        content_settings={"content_type": "application/json"},
    )


def _blob_get(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    try:
        container = _get_container_client()
        blob = container.get_blob_client(_blob_name(user_id, conversation_id))
        data = blob.download_blob().readall().decode("utf-8")
        return json.loads(data)
    except Exception:
        return None


def _blob_delete(user_id: str, conversation_id: str) -> bool:
    try:
        container = _get_container_client()
        blob = container.get_blob_client(_blob_name(user_id, conversation_id))
        blob.delete_blob()
        return True
    except Exception:
        return False


def _blob_list(user_id: str) -> List[Dict[str, Any]]:
    """List all conversations for a user from Azure Blob Storage (metadata only)."""
    container = _get_container_client()
    prefix = _blob_user_prefix(user_id)
    conversations = []

    for blob in container.list_blobs(name_starts_with=prefix):
        if not blob.name.endswith(".json"):
            continue
        try:
            blob_client = container.get_blob_client(blob.name)
            raw = blob_client.download_blob().readall().decode("utf-8")
            data = json.loads(raw)
            conversations.append({
                "id": data["id"],
                "created_at": data["created_at"],
                "title": data.get("title", "New Conversation"),
                "message_count": len(data["messages"]),
            })
        except Exception as e:
            logger.warning(f"Skipping corrupt blob {blob.name}: {e}")

    conversations.sort(key=lambda x: x["created_at"], reverse=True)
    return conversations


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Local File Backend                                                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _user_dir(user_id: str) -> str:
    return os.path.join(DATA_DIR, _validate_user_id(user_id))


def _ensure_data_dir(user_id: str):
    Path(_user_dir(user_id)).mkdir(parents=True, exist_ok=True)


def _file_path(user_id: str, conversation_id: str) -> str:
    return os.path.join(_user_dir(user_id), f"{conversation_id}.json")


def _file_put(user_id: str, conversation_id: str, data: Dict[str, Any]):
    _ensure_data_dir(user_id)
    raw = json.dumps(data, indent=2)
    with open(_file_path(user_id, conversation_id), "w") as f:
        f.write(encrypt_data(raw))


def _file_get(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    path = _file_path(user_id, conversation_id)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        raw = f.read()
    return json.loads(decrypt_data(raw))


def _file_delete(user_id: str, conversation_id: str) -> bool:
    path = _file_path(user_id, conversation_id)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def _file_list(user_id: str) -> List[Dict[str, Any]]:
    _ensure_data_dir(user_id)
    user_path = _user_dir(user_id)
    conversations = []
    for filename in os.listdir(user_path):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(user_path, filename)
        with open(path, "r") as f:
            raw = f.read()
            data = json.loads(decrypt_data(raw))
            conversations.append({
                "id": data["id"],
                "created_at": data["created_at"],
                "title": data.get("title", "New Conversation"),
                "message_count": len(data["messages"]),
            })
    conversations.sort(key=lambda x: x["created_at"], reverse=True)
    return conversations


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Public API (same signatures as before — called from main.py)       ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _put(user_id: str, conversation_id: str, data: Dict[str, Any]):
    uid = _validate_user_id(user_id)
    if _is_local(uid):
        _file_put(uid, conversation_id, data)
    else:
        _blob_put(uid, conversation_id, data)


def _get(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    uid = _validate_user_id(user_id)
    if _is_local(uid):
        return _file_get(uid, conversation_id)
    return _blob_get(uid, conversation_id)


def create_conversation(user_id: str, conversation_id: str) -> Dict[str, Any]:
    """Create a new conversation."""
    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat(),
        "title": "New Conversation",
        "messages": [],
    }
    _put(user_id, conversation_id, conversation)
    return conversation


def get_conversation(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """Load a conversation from storage."""
    return _get(user_id, conversation_id)


def save_conversation(user_id: str, conversation: Dict[str, Any]):
    """Save a conversation to storage."""
    _put(user_id, conversation["id"], conversation)


def list_conversations(user_id: str) -> List[Dict[str, Any]]:
    """List all conversations for a user (metadata only)."""
    uid = _validate_user_id(user_id)
    if _is_local(uid):
        return _file_list(uid)
    return _blob_list(uid)


def add_user_message(user_id: str, conversation_id: str, content: str):
    """Add a user message to a conversation."""
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["messages"].append({"role": "user", "content": content})
    save_conversation(user_id, conversation)


def add_assistant_message(
    user_id: str,
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    metadata: Dict[str, Any] = None,
):
    """Add an assistant message with all 3 stages to a conversation."""
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    msg: Dict[str, Any] = {
        "role": "assistant",
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
    }
    if metadata:
        msg["metadata"] = metadata
    conversation["messages"].append(msg)
    save_conversation(user_id, conversation)


def update_last_message_metadata(
    user_id: str,
    conversation_id: str,
    extra_metadata: Dict[str, Any],
):
    """Merge *extra_metadata* into the last assistant message's metadata."""
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        return
    for msg in reversed(conversation.get("messages", [])):
        if msg.get("role") == "assistant":
            if msg.get("metadata") is None:
                msg["metadata"] = {}
            msg["metadata"].update(extra_metadata)
            break
    save_conversation(user_id, conversation)


def update_conversation_title(user_id: str, conversation_id: str, title: str):
    """Update the title of a conversation."""
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["title"] = title
    save_conversation(user_id, conversation)


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    """Delete a conversation from storage."""
    uid = _validate_user_id(user_id)
    if _is_local(uid):
        return _file_delete(uid, conversation_id)
    return _blob_delete(uid, conversation_id)
