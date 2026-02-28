"""Conversation storage — triple-mode: local files, Azure Blob, or Azure Cosmos DB.

Cloud users  → Azure Cosmos DB (database: llm-council, container: conversations)
              Partition key: /user_id
Blob fallback→ Azure Blob Storage (for file attachments, legacy)
Local dev    → files (path: data/conversations/local-user/{conversation_id}.json)

The active backend is chosen per-call based on user_id:
  user_id == "local-user"  → file backend  (dev)
  COSMOS_ENDPOINT set      → Cosmos DB     (cloud primary)
  else Blob conn string    → Azure Blob    (cloud legacy fallback)
"""

import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from .config import (
    DATA_DIR,
    AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER, BLOB_CONVERSATIONS_PREFIX,
    AZURE_BLOB_CONVERSATIONS_CONTAINER, AZURE_BLOB_ATTACHMENTS_CONTAINER,
    AZURE_BLOB_MEMORY_CONTAINER, AZURE_BLOB_SKILLS_CONTAINER,
    COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE, COSMOS_CONVERSATIONS_CONTAINER,
)
from .security import encrypt_data, decrypt_data, is_encryption_enabled

logger = logging.getLogger(__name__)

LOCAL_USER_ID = "local-user"


def _is_local(user_id: str) -> bool:
    return user_id == LOCAL_USER_ID


def _use_cosmos() -> bool:
    """True when Cosmos DB is configured (preferred cloud backend)."""
    return bool(COSMOS_ENDPOINT and COSMOS_KEY)


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
# ║  Azure Cosmos DB Backend  (cloud primary)                           ║
# ╚══════════════════════════════════════════════════════════════════════╝

_cosmos_client = None
_cosmos_container = None


def _get_cosmos_container():
    """Lazy-initialised Cosmos DB container client (one per process)."""
    global _cosmos_client, _cosmos_container
    if _cosmos_container is None:
        from azure.cosmos import CosmosClient, PartitionKey
        _cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
        db = _cosmos_client.create_database_if_not_exists(id=COSMOS_DATABASE)
        _cosmos_container = db.create_container_if_not_exists(
            id=COSMOS_CONVERSATIONS_CONTAINER,
            partition_key=PartitionKey(path="/user_id"),
            offer_throughput=400,
        )
    return _cosmos_container


def _cosmos_put(user_id: str, conversation_id: str, data: Dict[str, Any]):
    """Upsert a conversation document into Cosmos DB."""
    container = _get_cosmos_container()
    doc = dict(data)
    doc["id"] = conversation_id
    doc["user_id"] = user_id
    container.upsert_item(doc)


def _cosmos_get(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """Read a single conversation from Cosmos DB."""
    try:
        container = _get_cosmos_container()
        item = container.read_item(item=conversation_id, partition_key=user_id)
        # Strip Cosmos system properties before returning
        for key in ("_rid", "_self", "_etag", "_attachments", "_ts"):
            item.pop(key, None)
        return item
    except Exception:
        return None


def _cosmos_delete(user_id: str, conversation_id: str) -> bool:
    """Delete a conversation from Cosmos DB."""
    try:
        container = _get_cosmos_container()
        container.delete_item(item=conversation_id, partition_key=user_id)
        return True
    except Exception:
        return False


def _cosmos_list(user_id: str) -> List[Dict[str, Any]]:
    """List all conversations for a user (metadata only) from Cosmos DB."""
    container = _get_cosmos_container()
    query = (
        "SELECT c.id, c.created_at, c.title, c.context_tags, "
        "ARRAY_LENGTH(c.messages) AS message_count "
        "FROM c WHERE c.user_id = @uid AND ARRAY_LENGTH(c.messages) > 0"
    )
    params = [{"name": "@uid", "value": user_id}]
    items = list(container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=False,
    ))
    # Sort newest first
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    for item in items:
        item.setdefault("title", "New Conversation")
        item.setdefault("message_count", 0)
    return items


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


# ── Attachment Blob Helpers (SAS upload / download) ───────────────────

def _parse_storage_conn_field(field: str) -> str:
    """Extract a named field from the Azure Storage connection string.

    Azure AccountKey values contain '=' characters (base64), so a simple
    ``split("=")`` would break.  Instead we locate the field prefix and
    find the next ';' delimiter.
    """
    prefix = f"{field}="
    start = AZURE_STORAGE_CONNECTION_STRING.find(prefix)
    if start == -1:
        return ""
    start += len(prefix)
    end = AZURE_STORAGE_CONNECTION_STRING.find(";", start)
    return AZURE_STORAGE_CONNECTION_STRING[start:end] if end != -1 else AZURE_STORAGE_CONNECTION_STRING[start:]


def is_blob_configured() -> bool:
    """Return True when Azure Blob Storage credentials are available."""
    return bool(AZURE_STORAGE_CONNECTION_STRING)


def generate_attachment_upload_url(user_id: str, filename: str, content_type: str) -> tuple:
    """Generate a SAS URL for direct browser upload to the *attachments* container.

    Returns ``(upload_url, blob_name)`` where *upload_url* is a fully-qualified
    Azure Blob SAS URL valid for 30 minutes with write-only permissions.
    """
    import uuid
    from datetime import datetime, timedelta, timezone
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions

    account_name = _parse_storage_conn_field("AccountName")
    account_key = _parse_storage_conn_field("AccountKey")
    container = AZURE_BLOB_ATTACHMENTS_CONTAINER

    # Unique blob name: {user_id}/{uuid}_{filename}
    safe_name = filename.replace("/", "_").replace("\\", "_")
    blob_name = f"{_validate_user_id(user_id)}/{uuid.uuid4().hex[:12]}_{safe_name}"

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(write=True, create=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
        content_type=content_type,
    )

    upload_url = f"https://{account_name}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"
    return upload_url, blob_name


def download_attachment_blob(blob_name: str) -> bytes:
    """Download an attachment from the *attachments* container and return raw bytes."""
    container_client = _get_blob_service().get_container_client(AZURE_BLOB_ATTACHMENTS_CONTAINER)
    blob_client = container_client.get_blob_client(blob_name)
    return blob_client.download_blob().readall()


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
    elif _use_cosmos():
        _cosmos_put(uid, conversation_id, data)
    else:
        _blob_put(uid, conversation_id, data)


def _get(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    uid = _validate_user_id(user_id)
    if _is_local(uid):
        return _file_get(uid, conversation_id)
    if _use_cosmos():
        return _cosmos_get(uid, conversation_id)
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
    if _use_cosmos():
        return _cosmos_list(uid)
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


def update_conversation_context(
    user_id: str,
    conversation_id: str,
    context_tags: Dict[str, Any],
):
    """Save domain/topic classification metadata on a conversation.

    This enables memory and skill retrieval to index conversations
    by domain (pharma, chemistry, regulatory, etc.), question type,
    and complexity — improving cross-session learning.
    """
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        return
    conversation["context_tags"] = context_tags
    save_conversation(user_id, conversation)


def save_pipeline_checkpoint(
    user_id: str,
    conversation_id: str,
    checkpoint_data: Dict[str, Any],
):
    """Save partial pipeline results for resume-on-disconnect.

    Called after each major stage completes so that a network drop
    doesn't lose work.  The checkpoint is cleared on successful
    completion by ``clear_pipeline_checkpoint``.
    """
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["_pipeline_checkpoint"] = checkpoint_data
    save_conversation(user_id, conversation)


def load_pipeline_checkpoint(
    user_id: str,
    conversation_id: str,
) -> Optional[Dict[str, Any]]:
    """Load pipeline checkpoint, or *None* if no checkpoint exists."""
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        return None
    return conversation.get("_pipeline_checkpoint")


def clear_pipeline_checkpoint(user_id: str, conversation_id: str):
    """Remove the pipeline checkpoint after successful completion."""
    conversation = get_conversation(user_id, conversation_id)
    if conversation is None:
        return
    if "_pipeline_checkpoint" in conversation:
        del conversation["_pipeline_checkpoint"]
        save_conversation(user_id, conversation)


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    """Delete a conversation from storage."""
    uid = _validate_user_id(user_id)
    if _is_local(uid):
        return _file_delete(uid, conversation_id)
    if _use_cosmos():
        return _cosmos_delete(uid, conversation_id)
    return _blob_delete(uid, conversation_id)
