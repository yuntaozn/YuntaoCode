"""本地持久记忆存储。"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .persistence import AtomicJsonDocumentStorage, DocumentStorage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryItem:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    source: str = "manual"           # 来源可选值："manual" | "auto" | "conversation"
    scope: str = "global"            # 作用域可选值："global" | "workspace"
    workspace_id: str = ""
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    usage_count: int = 0
    last_used_at: str = ""
    conversation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryItem":
        scope = _normalize_scope(value.get("scope"), value.get("workspace_id"))
        workspace_id = str(value.get("workspace_id") or "") if scope == "workspace" else ""
        return cls(
            id=str(value.get("id") or f"mem_{uuid.uuid4().hex[:10]}"),
            text=str(value.get("text") or ""),
            tags=list(value.get("tags") or []),
            enabled=bool(value.get("enabled", True)),
            source=str(value.get("source") or "manual"),
            scope=scope,
            workspace_id=workspace_id,
            created_at=str(value.get("created_at") or _utc_now()),
            updated_at=str(value.get("updated_at") or _utc_now()),
            usage_count=int(value.get("usage_count") or 0),
            last_used_at=str(value.get("last_used_at") or ""),
            conversation_id=str(value.get("conversation_id") or ""),
        )


# 数量限制
MAX_STORED_MEMORIES = 500
MAX_MEMORY_TEXT_CHARS = 500
MAX_MEMORY_PROMPT_CHARS = 6000
DEFAULT_ACTIVE_MEMORIES = 30
MAX_ACTIVE_MEMORIES = 50


class MemoryStore:
    """以单个 JSON 文件和原子写入实现的持久记忆存储。"""

    def __init__(
        self,
        store_path: Path | None = None,
        *,
        storage: DocumentStorage | None = None,
    ) -> None:
        self._storage = storage if storage is not None else AtomicJsonDocumentStorage(store_path)
        self.store_path = self._storage.path
        self._memories: dict[str, MemoryItem] = {}
        self._load()

    def _load(self) -> None:
        data = self._storage.load()
        items = data.get("memories") if isinstance(data, dict) else []
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                mem = MemoryItem.from_dict(item)
                if mem.text:
                    self._memories[mem.id] = mem

    def _save(self) -> None:
        payload = {
            "version": 1,
            "memories": [m.to_dict() for m in self._memories.values()],
        }
        self._storage.save(payload)

    # ----- 增删改查 -----

    def list(self) -> list[MemoryItem]:
        return sorted(
            self._memories.values(),
            key=lambda m: m.updated_at,
            reverse=True,
        )

    def list_applicable(self, workspace_id: str | None = None) -> list[MemoryItem]:
        """返回全局记忆及当前工作区范围内的记忆。"""
        current_workspace_id = str(workspace_id or "").strip()
        items: list[MemoryItem] = []
        for item in self.list():
            if item.scope == "workspace":
                if current_workspace_id and item.workspace_id == current_workspace_id:
                    items.append(item)
                continue
            items.append(item)
        return items

    def get(self, memory_id: str) -> MemoryItem | None:
        return self._memories.get(memory_id)

    def add(self, item: MemoryItem) -> MemoryItem:
        if not item.text:
            raise ValueError("memory text must not be empty")
        item.text = item.text[:MAX_MEMORY_TEXT_CHARS]
        item.scope = _normalize_scope(item.scope, item.workspace_id)
        if item.scope != "workspace":
            item.workspace_id = ""
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
        if "scope" in patch or "workspace_id" in patch:
            scope = patch.get("scope", item.scope)
            workspace_id = str(patch.get("workspace_id", item.workspace_id) or "")
            item.scope = _normalize_scope(scope, workspace_id)
            item.workspace_id = workspace_id if item.scope == "workspace" else ""
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
            # 此处不保存；构建提示时统一批量保存。

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

    # ----- 淘汰策略 -----

    def _evict_if_needed(self) -> None:
        """当数量超过 MAX_STORED_MEMORIES 时淘汰低价值记忆。"""
        if len(self._memories) <= MAX_STORED_MEMORIES:
            return

        now = datetime.now(timezone.utc)

        def _eviction_score(item: MemoryItem) -> float:
            """分数越高越可能被淘汰；手动记忆永不自动淘汰。"""
            if item.source == "manual":
                return -1000.0
            score = 0.0
            # 未使用记忆
            if item.usage_count == 0:
                score += 5.0
            # 30 天内未使用
            if item.last_used_at:
                try:
                    last_used = datetime.fromisoformat(item.last_used_at)
                    days_ago = (now - last_used).total_seconds() / 86400
                    if days_ago > 30:
                        score += 3.0
                except (ValueError, TypeError):
                    score += 3.0
            else:
                score += 3.0  # 从未使用
            # 短文本
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
                continue  # 永不淘汰手动记忆
            del self._memories[mid]
            removed += 1
            if removed >= to_remove:
                break

    # ----- 从 settings.json 迁移 -----

    @classmethod
    def migrate_from_settings(cls, store_path: Path, settings_store: Any) -> "MemoryStore":
        """将旧记忆数据从 settings.json 迁移到 memories.json。"""
        store = cls(store_path)

        # 仅当 memories.json 为空且设置中存在旧数据时迁移
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
                    scope="global",
                )
                store._memories[item.id] = item

            # 保存迁移后的数据
            store._save()

            # 清除设置中的旧数据
            if isinstance(old_memories, dict):
                old_memories["items"] = []
                settings_store._settings["memories"] = old_memories
                settings_store._save()

        return store


def _normalize_scope(scope: Any, workspace_id: Any = "") -> str:
    value = str(scope or "").strip().lower()
    if value in {"workspace", "project"} and str(workspace_id or "").strip():
        return "workspace"
    return "global"
