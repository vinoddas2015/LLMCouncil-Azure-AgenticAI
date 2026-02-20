"""Conversation storage — dual-mode: local files or S3.

Cloud users  → S3  (key: conversations/{user_id}/{conversation_id}.json)
Local dev    → files (path: data/conversations/local-user/{conversation_id}.json)

The active backend is chosen per-call based on user_id:
  user_id == "local-user"  → file backend
  anything else            → S3 backend
"""

import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from .config import DATA_DIR, S3_BUCKET_NAME, S3_CONVERSATIONS_PREFIX
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
# ║  S3 Backend                                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝

_s3_client = None


def _get_s3():
    """Lazy-initialised boto3 S3 client (created once per process)."""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3")
    return _s3_client


def _s3_key(user_id: str, conversation_id: str) -> str:
    return f"{S3_CONVERSATIONS_PREFIX}/{user_id}/{conversation_id}.json"


def _s3_user_prefix(user_id: str) -> str:
    return f"{S3_CONVERSATIONS_PREFIX}/{user_id}/"


def _s3_put(user_id: str, conversation_id: str, data: Dict[str, Any]):
    _get_s3().put_object(
        Bucket=S3_BUCKET_NAME,
        Key=_s3_key(user_id, conversation_id),
        Body=json.dumps(data, indent=2).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def _s3_get(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    try:
        resp = _get_s3().get_object(
            Bucket=S3_BUCKET_NAME,
            Key=_s3_key(user_id, conversation_id),
        )
        return json.loads(resp["Body"].read().decode("utf-8"))
    except _get_s3().exceptions.NoSuchKey:
        return None


def _s3_delete(user_id: str, conversation_id: str) -> bool:
    key = _s3_key(user_id, conversation_id)
    try:
        _get_s3().head_object(Bucket=S3_BUCKET_NAME, Key=key)
    except Exception:
        return False
    _get_s3().delete_object(Bucket=S3_BUCKET_NAME, Key=key)
    return True


def _s3_list(user_id: str) -> List[Dict[str, Any]]:
    """List all conversations for a user from S3 (metadata only)."""
    s3 = _get_s3()
    prefix = _s3_user_prefix(user_id)
    conversations = []
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".json"):
                continue
            try:
                resp = s3.get_object(Bucket=S3_BUCKET_NAME, Key=obj["Key"])
                data = json.loads(resp["Body"].read().decode("utf-8"))
                conversations.append({
                    "id": data["id"],
                    "created_at": data["created_at"],
                    "title": data.get("title", "New Conversation"),
                    "message_count": len(data["messages"]),
                })
            except Exception as e:
                logger.warning(f"Skipping corrupt S3 object {obj['Key']}: {e}")

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
        _s3_put(uid, conversation_id, data)


def _get(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    uid = _validate_user_id(user_id)
    if _is_local(uid):
        return _file_get(uid, conversation_id)
    return _s3_get(uid, conversation_id)


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
    return _s3_list(uid)


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
    return _s3_delete(uid, conversation_id)
