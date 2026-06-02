from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .security import PathGuard
from .task_store import TaskRecord, TaskStore
from .tool_registry import ToolRegistry


@dataclass(frozen=True)
class ToolContext:
    path_guard: PathGuard
    task_id: str
    log: Any
    backup_file: Any | None = None
    settings: Any | None = None


class TaskRunner:
    DOCUMENT_WRITE_TOOLS = {
        "document.export_markdown",
        "document.export_docx",
        "document.extract_pdf_to_docx",
        "document.generate_docx_from_outline",
        "document.export_pdf",
        "document.generate_ppt",
        "document.merge_pdfs",
        "document.split_pdf",
        "document.create_bookmark_outline",
    }
    WRITE_TOOLS = {
        "code.edit_file",
        "code.replace_text",
        "filesystem.write_file",
        *DOCUMENT_WRITE_TOOLS,
    }

    def __init__(
        self,
        registry: ToolRegistry,
        store: TaskStore,
        path_guard: PathGuard,
        backup_store: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.path_guard = path_guard
        self.backup_store = backup_store
        self.settings = settings

    async def submit(
        self,
        tool_id: str,
        input_data: dict[str, Any],
        wait: bool = False,
        confirmed: bool = False,
        workspace_path: str | None = None,
    ) -> TaskRecord:
        tool_id = self.registry.resolve_id(tool_id)
        tool = self.registry.get(tool_id)
        if self.settings and not self.settings.is_tool_enabled(tool_id):
            raise PermissionError(f"plugin is disabled for tool: {tool_id}")
        if tool.spec.requires_confirmation and not confirmed:
            task = self.store.create(tool_id, input_data)
            self.store.update(
                task.id,
                status="waiting_confirmation",
                output={"reason": "tool requires confirmation"},
            )
            self.store.append_log(task.id, "warning", "tool requires confirmation")
            return self.store.get(task.id) or task
        task = self.store.create(tool_id, input_data)
        coro = self._run(task.id, workspace_path=workspace_path)
        if wait:
            await coro
        else:
            asyncio.create_task(coro)
        return self.store.get(task.id) or task

    async def _run(self, task_id: str, workspace_path: str | None = None) -> None:
        task = self.store.get(task_id)
        if not task:
            return

        self.store.update(task_id, status="running")
        self.store.append_log(task_id, "info", f"running tool: {task.tool}")

        backup_session = None
        backup_meta = None
        try:
            tool = self.registry.get(task.tool)
            access_scope = self.settings.get_access_scope() if self.settings else "project_only"
            full_access = access_scope == "full_local"
            if workspace_path:
                path_guard = self.path_guard.scoped(workspace_path, allow_all=full_access)
            else:
                path_guard = self.path_guard.with_full_access() if full_access else self.path_guard
            backup_settings = self.settings.get_backup_settings() if self.settings else {"enabled": False, "keep_rounds": 5}
            if (
                self.backup_store
                and task.tool in self.WRITE_TOOLS
                and backup_settings.get("enabled", True)
            ):
                backup_session = self.backup_store.begin(
                    task.id,
                    task.tool,
                    task.input,
                    path_guard=path_guard,
                )

            def log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
                self.store.append_log(task_id, level, message, data)

            backup_file = backup_session.backup_file if backup_session else None
            context = ToolContext(
                path_guard=path_guard,
                task_id=task_id,
                log=log,
                backup_file=backup_file,
                settings=self.settings,
            )
            output = await tool.handler(task.input, context)
            if backup_session:
                backup_meta = backup_session.finish("success", int(backup_settings.get("keep_rounds") or 5))
                if backup_meta and isinstance(output, dict):
                    output["_backup"] = backup_meta
            self.store.update(task_id, status="success", output=output)
            self.store.append_log(task_id, "info", "task completed")
        except Exception as exc:
            if backup_session:
                try:
                    backup_settings = self.settings.get_backup_settings() if self.settings else {"keep_rounds": 5}
                    backup_meta = backup_session.finish("failure", int(backup_settings.get("keep_rounds") or 5))
                    if backup_meta:
                        self.store.append_log(task_id, "warning", "backup captured before failed write", backup_meta)
                except Exception as backup_exc:
                    self.store.append_log(task_id, "error", f"backup failed: {backup_exc}")
            self.store.update(task_id, status="failure", error=str(exc))
            self.store.append_log(task_id, "error", str(exc))
