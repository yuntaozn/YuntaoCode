"""Memory CRUD API handlers."""

from __future__ import annotations

import uuid
from typing import Any

import tornado.web

from .base import ApiHandler
from ..memory_store import MemoryItem


class MemoriesHandler(ApiHandler):
    """GET /memories - list all memories; POST /memories - create a new memory."""

    def get(self) -> None:
        store = self.runtime.settings.memory_store
        items = store.list()
        self.finish_json({
            "success": True,
            "data": {
                "items": [m.to_dict() for m in items],
                "total": len(items),
                "enabled": self.runtime.settings.get_memory_settings().get("enabled", True),
                "max_active": self.runtime.settings.get_memory_settings().get("max_active", 30),
                "auto_extract": self.runtime.settings.get_memory_settings().get("auto_extract", True),
            },
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        text = str(payload.get("text") or "").strip()
        if not text:
            raise tornado.web.HTTPError(400, reason="text is required")

        tags_raw = payload.get("tags")
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        else:
            tags = []

        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            text=text,
            tags=tags[:6],
            enabled=bool(payload.get("enabled", True)),
            source=str(payload.get("source") or "manual"),
        )
        store = self.runtime.settings.memory_store
        saved = store.add(item)
        self.finish_json({"success": True, "data": saved.to_dict()})


class MemoryDetailHandler(ApiHandler):
    """PUT /memories/{id} - update; DELETE /memories/{id} - delete."""

    def put(self, memory_id: str) -> None:
        payload = self.parse_json_body()
        store = self.runtime.settings.memory_store
        updated = store.update(memory_id, payload)
        if not updated:
            raise tornado.web.HTTPError(404, reason=f"memory not found: {memory_id}")
        self.finish_json({"success": True, "data": updated.to_dict()})

    def delete(self, memory_id: str) -> None:
        store = self.runtime.settings.memory_store
        deleted = store.delete(memory_id)
        if not deleted:
            raise tornado.web.HTTPError(404, reason=f"memory not found: {memory_id}")
        self.finish_json({"success": True, "data": {"id": memory_id}})


class MemoryPromptHandler(ApiHandler):
    """GET /memories/prompt - preview the memory prompt that would be injected."""

    def get(self) -> None:
        from ..memory_service import build_memory_prompt_from_store

        store = self.runtime.settings.memory_store
        mem_settings = self.runtime.settings.get_memory_settings()
        user_message = self.get_argument("message", "")

        prompt, used_ids = build_memory_prompt_from_store(
            store,
            enabled=mem_settings.get("enabled", True),
            max_active=mem_settings.get("max_active", 30),
            user_message=user_message,
        )
        self.finish_json({
            "success": True,
            "data": {
                "prompt": prompt,
                "used_memory_ids": used_ids,
                "char_count": len(prompt),
            },
        })
