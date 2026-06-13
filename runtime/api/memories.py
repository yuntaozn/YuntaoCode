"""Memory CRUD API handlers."""

from __future__ import annotations

import uuid

import tornado.web

from .base import ApiHandler
from ..memory_store import MemoryItem


def _parse_tags(raw: object) -> list[str]:
    if isinstance(raw, str):
        parts = raw.replace("，", ",").replace("；", ",").replace(";", ",").split(",")
        return [part.strip() for part in parts if part.strip()][:6]
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()][:6]
    return []


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_workspace_scope(value: object) -> bool:
    return str(value or "").strip().lower() in {"workspace", "project"}


def _validate_workspace_id(handler: ApiHandler, workspace_id: str) -> None:
    if workspace_id and not handler.runtime.workspaces.get(workspace_id):
        raise tornado.web.HTTPError(404, reason=f"workspace not found: {workspace_id}")


def _validate_memory_scope(handler: ApiHandler, scope: object, workspace_id: str) -> None:
    if _is_workspace_scope(scope) and not workspace_id:
        raise tornado.web.HTTPError(400, reason="workspace_id is required for workspace memory")
    _validate_workspace_id(handler, workspace_id)


class MemoriesHandler(ApiHandler):
    """GET /memories - list memories; POST /memories - create a new memory."""

    def get(self) -> None:
        store = self.runtime.settings.memory_store
        workspace_id = self.get_argument("workspace_id", "").strip()
        applicable_only = _truthy(self.get_argument("applicable", "0"))
        items = store.list_applicable(workspace_id) if applicable_only else store.list()
        mem_settings = self.runtime.settings.get_memory_settings()
        self.finish_json({
            "success": True,
            "data": {
                "items": [memory.to_dict() for memory in items],
                "total": len(items),
                "enabled": mem_settings.get("enabled", True),
                "max_active": mem_settings.get("max_active", 30),
                "auto_extract": mem_settings.get("auto_extract", True),
            },
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        text = str(payload.get("text") or "").strip()
        if not text:
            raise tornado.web.HTTPError(400, reason="text is required")

        scope = str(payload.get("scope") or "global")
        workspace_id = str(payload.get("workspace_id") or "").strip()
        _validate_memory_scope(self, scope, workspace_id)

        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            text=text,
            tags=_parse_tags(payload.get("tags")),
            enabled=bool(payload.get("enabled", True)),
            source=str(payload.get("source") or "manual"),
            scope=scope,
            workspace_id=workspace_id,
        )
        store = self.runtime.settings.memory_store
        saved = store.add(item)
        self.finish_json({"success": True, "data": saved.to_dict()})


class MemoryDetailHandler(ApiHandler):
    """PUT /memories/{id} - update; DELETE /memories/{id} - delete."""

    def put(self, memory_id: str) -> None:
        payload = self.parse_json_body()
        store = self.runtime.settings.memory_store
        current = store.get(memory_id)
        if not current:
            raise tornado.web.HTTPError(404, reason=f"memory not found: {memory_id}")
        if "scope" in payload or "workspace_id" in payload:
            target_scope = payload.get("scope", current.scope)
            target_workspace_id = str(payload.get("workspace_id", current.workspace_id) or "").strip()
            _validate_memory_scope(self, target_scope, target_workspace_id)
        updated = store.update(memory_id, payload)
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
        workspace_id = self.get_argument("workspace_id", "").strip()

        prompt, used_ids = build_memory_prompt_from_store(
            store,
            enabled=mem_settings.get("enabled", True),
            max_active=mem_settings.get("max_active", 30),
            user_message=user_message,
            workspace_id=workspace_id,
        )
        self.finish_json({
            "success": True,
            "data": {
                "prompt": prompt,
                "used_memory_ids": used_ids,
                "char_count": len(prompt),
            },
        })
