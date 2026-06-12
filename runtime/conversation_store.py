from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .persistence import AtomicJsonDocumentStorage, DocumentStorage


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_conversation_mode(value: Any) -> str:
    mode = str(value or "terminal").strip() or "terminal"
    return "terminal" if mode in {"document", "coding", "paper"} else mode


@dataclass
class MessageRecord:
    id: str
    role: str
    content: str
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MessageRecord":
        return cls(
            id=str(value.get("id") or uuid4()),
            role=str(value.get("role", "")),
            content=str(value.get("content", "")),
            created_at=str(value.get("created_at") or utc_now()),
            metadata=value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
        )


@dataclass
class ConversationRecord:
    id: str
    workspace_id: str
    title: str
    mode: str = "terminal"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    messages: list[MessageRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self, include_messages: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "metadata": self.metadata,
        }
        if include_messages:
            data["messages"] = [message.to_public_dict() for message in self.messages]
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ConversationRecord":
        messages = value.get("messages") if isinstance(value.get("messages"), list) else []
        return cls(
            id=str(value.get("id") or uuid4()),
            workspace_id=str(value.get("workspace_id", "")),
            title=str(value.get("title") or "新对话"),
            mode=normalize_conversation_mode(value.get("mode")),
            created_at=str(value.get("created_at") or utc_now()),
            updated_at=str(value.get("updated_at") or utc_now()),
            messages=[MessageRecord.from_dict(item) for item in messages if isinstance(item, dict)],
            metadata=value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
        )


class ConversationStore:
    def __init__(
        self,
        store_path: Path | None = None,
        *,
        storage: DocumentStorage | None = None,
    ) -> None:
        self._storage = storage if storage is not None else AtomicJsonDocumentStorage(store_path)
        self.store_path = self._storage.path
        self._conversations: dict[str, ConversationRecord] = {}
        self._load()

    def list(self, workspace_id: str | None = None) -> list[ConversationRecord]:
        conversations = list(self._conversations.values())
        if workspace_id:
            conversations = [item for item in conversations if item.workspace_id == workspace_id]
        return sorted(conversations, key=lambda item: item.updated_at, reverse=True)

    def get(self, conversation_id: str) -> ConversationRecord | None:
        return self._conversations.get(conversation_id)

    def create(self, workspace_id: str, title: str | None = None, mode: str | None = None) -> ConversationRecord:
        record = ConversationRecord(
            id=str(uuid4()),
            workspace_id=workspace_id,
            title=title or "新对话",
            mode=normalize_conversation_mode(mode),
        )
        self._conversations[record.id] = record
        self._save()
        return record

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> MessageRecord:
        conversation = self._require(conversation_id)
        message = MessageRecord(id=str(uuid4()), role=role, content=content, metadata=metadata or {})
        conversation.messages.append(message)
        conversation.updated_at = utc_now()
        if conversation.title == "新对话" and role == "user" and content.strip():
            conversation.title = content.strip()[:24]
        self._save()
        return message

    def update_mode(self, conversation_id: str, mode: str) -> ConversationRecord:
        conversation = self._require(conversation_id)
        conversation.mode = normalize_conversation_mode(mode)
        conversation.updated_at = utc_now()
        self._save()
        return conversation

    def _require(self, conversation_id: str) -> ConversationRecord:
        conversation = self.get(conversation_id)
        if not conversation:
            raise KeyError(f"unknown conversation: {conversation_id}")
        return conversation

    def delete(self, conversation_id: str) -> bool:
        """Delete a conversation. Returns True if it existed."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            self._save()
            return True
        return False

    def _load(self) -> None:
        value = self._storage.load()
        conversations = value.get("conversations") if isinstance(value, dict) else []
        if not isinstance(conversations, list):
            return
        for item in conversations:
            if isinstance(item, dict):
                record = ConversationRecord.from_dict(item)
                self._conversations[record.id] = record

    def _save(self) -> None:
        payload = {
            "conversations": [
                item.to_public_dict(include_messages=True)
                for item in self._conversations.values()
            ]
        }
        self._storage.save(payload)
