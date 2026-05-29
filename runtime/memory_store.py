"""Persistent memory store with atomic writes and eviction policy."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryItem:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    source: str = "manual"           # "manual" | "auto" | "conversation"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    usage_count: int = 0
    last_used_at: str = ""
    conversation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryItem":
        return cls(
            id=str(value.get("id") or f"mem_{uuid.uuid4().hex[:10]}"),
            text=str(value.get("text") or ""),
            tags=list(value.get("tags") or []),
            enabled=bool(value.get("enabled", True)),
            source=str(value.get("source") or "manual"),
            created_at=str(value.get("created_at") or _utc_now()),
            updated_at=str(value.get("updated_at") or _utc_now()),
            usage_count=int(value.get("usage_count") or 0),
            last_used_at=str(value.get("last_used_at") or ""),
            conversation_id=str(value.get("conversation_id") or ""),
        )


# Limits
MAX_STORED_MEMORIES = 500
MAX_MEMORY_TEXT_CHARS = 500
MAX_MEMORY_PROMPT_CHARS = 6000
DEFAULT_ACTIVE_MEMORIES = 30
MAX_ACTIVE_MEMORIES = 50


class MemoryStore:
    """Persistent memory store backed by a single JSON file with atomic writes."""

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self._memories: dict[str, MemoryItem] = {}
        self._load()

    def _load(self) -> None:
        if not self.store_path or not self.store_path.exists():
            return
        try:
            raw = self.store_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return
        items = data.get("memories") if isinstance(data, dict) else []
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                mem = MemoryItem.from_dict(item)
                if mem.text:
                    self._memories[mem.id] = mem

    def _save(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "memories": [m.to_dict() for m in self._memories.values()],
        }
        # Atomic write: write to temp file then rename
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.store_path)

    # ----- CRUD -----

    def list(self) -> list[MemoryItem]:
        return sorted(
            self._memories.values(),
            key=lambda m: m.updated_at,
            reverse=True,
        )

    def get(self, memory_id: str) -> MemoryItem | None:
        return self._memories.get(memory_id)

    def add(self, item: MemoryItem) -> MemoryItem:
        if not item.text:
            raise ValueError("memory text must not be empty")
        item.text = item.text[:MAX_MEMORY_TEXT_CHARS]
        item.updated_at = _utc_now()
        self._memories[item.id] = item
        self._evict_if_needed()
        self._save()
        return item

    def update(self, memory_id: str, patch: dict[str, Any]) -> MemoryItem | None:
        item = self._memories.get(memory_id)
        if not item:
            return None
        if "text" in patch:
            text = str(patch["text"] or "").strip()[:MAX_MEMORY_TEXT_CHARS]
            if text:
                item.text = text
        if "tags" in patch:
            tags = patch["tags"]
            if isinstance(tags, list):
                item.tags = [str(t).strip()[:24] for t in tags if str(t).strip()][:6]
        if "enabled" in patch:
            item.enabled = bool(patch["enabled"])
        item.updated_at = _utc_now()
        self._save()
        return item

    def delete(self, memory_id: str) -> bool:
        if memory_id in self._memories:
            del self._memories[memory_id]
            self._save()
            return True
        return False

    def record_usage(self, memory_id: str) -> None:
        item = self._memories.get(memory_id)
        if item:
            item.usage_count += 1
            item.last_used_at = _utc_now()
            # Don't save here; batch save happens at prompt build time

    def batch_record_usage(self, memory_ids: list[str]) -> None:
        now = _utc_now()
        for mid in memory_ids:
            item = self._memories.get(mid)
            if item:
                item.usage_count += 1
                item.last_used_at = now
        self._save()

    def count(self) -> int:
        return len(self._memories)

    # ----- Eviction -----

    def _evict_if_needed(self) -> None:
        """Evict low-value memories when count exceeds MAX_STORED_MEMORIES."""
        if len(self._memories) <= MAX_STORED_MEMORIES:
            return

        now = datetime.now(timezone.utc)

        def _eviction_score(item: MemoryItem) -> float:
            """Higher score = more likely to be evicted. Manual memories are never evicted."""
            if item.source == "manual":
                return -1000.0
            score = 0.0
            # Unused memories
            if item.usage_count == 0:
                score += 5.0
            # Not used in 30 days
            if item.last_used_at:
                try:
                    last_used = datetime.fromisoformat(item.last_used_at)
                    days_ago = (now - last_used).total_seconds() / 86400
                    if days_ago > 30:
                        score += 3.0
                except (ValueError, TypeError):
                    score += 3.0
            else:
                score += 3.0  # Never used
            # Short text
            if len(item.text) < 20:
                score += 1.0
            return score

        sorted_items = sorted(
            self._memories.items(),
            key=lambda kv: _eviction_score(kv[1]),
            reverse=True,
        )

        to_remove = len(self._memories) - MAX_STORED_MEMORIES
        removed = 0
        for mid, item in sorted_items:
            if _eviction_score(item) <= -1000.0:
                continue  # Never evict manual memories
            del self._memories[mid]
            removed += 1
            if removed >= to_remove:
                break

    # ----- Migration from settings.json -----

    @classmethod
    def migrate_from_settings(cls, store_path: Path, settings_store: Any) -> "MemoryStore":
        """Migrate old memory data from settings.json into memories.json."""
        store = cls(store_path)

        # Only migrate if memories.json is empty and settings has old data
        old_memories = settings_store._settings.get("memories", {})
        old_items = old_memories.get("items", []) if isinstance(old_memories, dict) else []

        if not store._memories and old_items:
            for raw in old_items:
                if not isinstance(raw, dict):
                    continue
                text = str(raw.get("text") or raw.get("content") or "").strip()
                if not text:
                    continue
                item = MemoryItem(
                    id=str(raw.get("id") or f"mem_{uuid.uuid4().hex[:10]}"),
                    text=text[:MAX_MEMORY_TEXT_CHARS],
                    tags=list(raw.get("tags") or []),
                    enabled=bool(raw.get("enabled", True)),
                    source="manual",
                )
                store._memories[item.id] = item

            # Save migrated data
            store._save()

            # Clear old data from settings
            if isinstance(old_memories, dict):
                old_memories["items"] = []
                settings_store._settings["memories"] = old_memories
                settings_store._save()

        return store
