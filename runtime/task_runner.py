from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from .capability_governance import ai_plugin_draft_workspace_guard_message
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
    temp_dir: Path | None = None
    attachment_store: Any | None = None
    attachment_ids: tuple[str, ...] = ()
    workspace_id: str = ""


class TaskRunner:
    DOCUMENT_WRITE_TOOLS = {
        "document.export_markdown",
        "document.export_docx",
        "document.export_draft_docx",
        "document.extract_pdf_to_docx",
        "document.translate_docx",
        "document.generate_docx_from_outline",
        "document.export_pdf",
        "document.generate_ppt",
        "document.merge_pdfs",
        "document.split_pdf",
        "document.create_bookmark_outline",
    }
    WEB_WRITE_TOOLS = {
        "web.collect_site_assets",
        "web.capture_page",
    }
    WRITE_TOOLS = {
        "code.apply_patch",
        "code.edit_file",
        "code.replace_text",
        "filesystem.apply_changes",
        "filesystem.transform_text",
        "filesystem.write_file",
        "filesystem.delete_file",
        "filesystem.finalize_text_file",
        *DOCUMENT_WRITE_TOOLS,
        *WEB_WRITE_TOOLS,
    }
    WRITE_EFFECTS = {"file_write", "file_delete", "local_state_change"}

    def __init__(
        self,
        registry: ToolRegistry,
        store: TaskStore,
        path_guard: PathGuard,
        backup_store: Any | None = None,
        settings: Any | None = None,
        attachment_store: Any | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.path_guard = path_guard
        self.backup_store = backup_store
        self.settings = settings
        self.attachment_store = attachment_store

    async def submit(
        self,
        tool_id: str,
        input_data: dict[str, Any],
        wait: bool = False,
        confirmed: bool = False,
        workspace_path: str | None = None,
        workspace_id: str | None = None,
        artifact_scope_id: str | None = None,
        attachment_ids: tuple[str, ...] | list[str] | None = None,
    ) -> TaskRecord:
        tool_id = self.registry.resolve_id(tool_id)
        input_data = self.registry.normalize_input_data(tool_id, input_data)
        tool = self.registry.get(tool_id)
        if self.settings and not self.settings.is_tool_enabled(tool_id):
            raise PermissionError(f"plugin is disabled for tool: {tool_id}")
        guard_message = ai_plugin_draft_workspace_guard_message(
            tool_id=tool_id,
            input_data=input_data,
            workspace_path=workspace_path,
            data_dir=getattr(self.settings, "data_dir", None),
        )
        if guard_message:
            raise PermissionError(guard_message)
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
        coro = self._run(
            task.id,
            workspace_path=workspace_path,
            workspace_id=workspace_id,
            artifact_scope_id=artifact_scope_id,
            attachment_ids=tuple(str(item) for item in (attachment_ids or ()) if str(item)),
        )
        if wait:
            await coro
        else:
            asyncio.create_task(coro)
        return self.store.get(task.id) or task

    async def _run(
        self,
        task_id: str,
        workspace_path: str | None = None,
        workspace_id: str | None = None,
        artifact_scope_id: str | None = None,
        attachment_ids: tuple[str, ...] = (),
    ) -> None:
        task = self.store.get(task_id)
        if not task:
            return

        self.store.update(task_id, status="running")
        self.store.append_log(task_id, "info", f"running tool: {task.tool}")

        backup_session = None
        backup_meta = None
        backup_warnings: list[dict[str, str]] = []
        try:
            tool = self.registry.get(task.tool)
            access_scope = self.settings.get_access_scope() if self.settings else "project_only"
            full_access = access_scope == "full_local"
            if workspace_path:
                path_guard = self.path_guard.scoped(workspace_path, allow_all=full_access)
            else:
                path_guard = self.path_guard.with_full_access() if full_access else self.path_guard
            backup_settings = self.settings.get_backup_settings() if self.settings else {"enabled": False, "keep_rounds": 5}
            tool_effects = set(tool.spec.effects or [])
            if (
                self.backup_store
                and self._should_capture_backup(task.tool, tool_effects)
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

            def backup_file(path: str | Path) -> None:
                if not backup_session:
                    return
                try:
                    backup_session.backup_file(path)
                except Exception as exc:
                    warning = {"path": str(path), "error": str(exc)}
                    backup_warnings.append(warning)
                    log(
                        "warning",
                        "backup failed; continuing without restore point for this path",
                        warning,
                    )

            backup_handler = backup_file if backup_session else None
            temp_dir = self._task_temp_dir(artifact_scope_id or task_id)
            temp_dir.mkdir(parents=True, exist_ok=True)
            context = ToolContext(
                path_guard=path_guard,
                task_id=task_id,
                log=log,
                backup_file=backup_handler,
                settings=self.settings,
                temp_dir=temp_dir,
                attachment_store=self.attachment_store,
                attachment_ids=attachment_ids,
                workspace_id=str(workspace_id or ""),
            )
            output = await tool.handler(task.input, context)
            failure_reason = self._output_failure_reason(task.tool, output)
            partial_reason = "" if failure_reason else self._output_partial_reason(task.tool, output)
            if backup_warnings and isinstance(output, dict):
                output["_backup_warnings"] = list(backup_warnings)
            if backup_session:
                backup_meta = backup_session.finish(
                    "failure" if failure_reason else ("partial" if partial_reason else "success"),
                    int(backup_settings.get("keep_rounds") or 5),
                )
                if backup_meta and isinstance(output, dict):
                    output["_backup"] = backup_meta
            if failure_reason:
                self.store.update(task_id, status="failure", output=output, error=failure_reason)
                self.store.append_log(task_id, "error", failure_reason)
            elif partial_reason:
                self.store.update(task_id, status="partial", output=output, error=partial_reason)
                self.store.append_log(task_id, "warning", partial_reason)
            else:
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

    @staticmethod
    def _output_failure_reason(tool_id: str, output: Any) -> str:
        if not isinstance(output, dict):
            return ""
        if output.get("error") is True:
            return _compact_failure_message(output, "tool reported an error")
        if tool_id == "shell.run_command":
            if output.get("timed_out") is True:
                timeout = output.get("timeout")
                fallback = f"command timed out after {timeout}s" if timeout else "command timed out"
                return _compact_failure_message(output, fallback)
            try:
                exit_code = int(output.get("exit_code", 0) or 0)
            except (TypeError, ValueError):
                exit_code = 0
            if exit_code != 0:
                return _compact_failure_message(
                    output,
                    f"command exited with code {exit_code}",
                )
        return ""

    @classmethod
    def _should_capture_backup(cls, tool_id: str, tool_effects: set[str]) -> bool:
        return tool_id in cls.WRITE_TOOLS or bool(tool_effects & cls.WRITE_EFFECTS)

    def _task_temp_dir(self, scope_id: str) -> Path:
        data_dir = getattr(self.settings, "data_dir", None)
        if data_dir:
            root = Path(data_dir) / "task-artifacts"
        elif self.store.storage_path:
            root = self.store.storage_path.parent / "task-artifacts"
        else:
            root = Path(tempfile.gettempdir()) / "yuntaocode-task-artifacts"
        safe_scope = "".join(
            char for char in str(scope_id or "")
            if char.isalnum() or char in {"-", "_"}
        )[:128]
        if not safe_scope:
            raise ValueError("artifact scope id is required")
        return root / safe_scope

    @staticmethod
    def _output_partial_reason(tool_id: str, output: Any) -> str:
        if not isinstance(output, dict):
            return ""
        status = str(output.get("status") or "").strip().lower()
        if status in {"partial", "partial_resumable"} or output.get("partial_resumable") is True:
            reason = str(output.get("stopped_reason") or "").strip()
            if status == "partial_resumable" or output.get("partial_resumable") is True:
                return reason or "tool partially completed and can be resumed"
            return reason or "tool partially completed"
        return ""


def _compact_failure_message(output: dict[str, Any], fallback: str) -> str:
    stderr = str(output.get("stderr") or "").strip()
    stdout = str(output.get("stdout") or "").strip()
    message = str(output.get("message") or output.get("content") or "").strip()
    detail = stderr or stdout or message
    if not detail:
        return fallback
    return f"{fallback}: {detail[:500]}"
