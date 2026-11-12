from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import tornado.web
import tornado.iostream

from .base import ApiHandler
from runtime import i18n
from runtime.capability_governance import ai_plugin_draft_workspace_guard_message
from runtime.agent_strategy.capability_router import (
    build_capability_catalog,
    order_tool_specs_for_model_prompt,
)
from runtime.agent_strategy import classifiers as _clf
from runtime.agent_strategy import capability_preflight as _cap_preflight
from runtime.agent_strategy import confirmation_policy as _cp
from runtime.agent_strategy import conversation_task_context as _task_ctx
from runtime.agent_strategy import context_hygiene as _ctx_hygiene
from runtime.agent_strategy import prompts as _prp
from runtime.agent_strategy import task_contract as _tc
from runtime.agent_strategy.tool_execution_guard import (
    ToolExecutionGuardChecks,
    evaluate_tool_execution_guard,
)
from runtime.agent_strategy import tool_result_risks as _tool_risks
from runtime.model_providers import generate_chat_completion
from runtime.model_calls import run_model_call
from runtime.terminal_profile import get_terminal_config
from runtime.context_manager import (
    compress_context,
    count_messages_tokens,
    estimate_messages_tokens_fast,
    get_context_limit,
    get_usable_limit,
    tokenizer_ready,
)
from runtime.conversation_runner import ConversationRunExecutor
from runtime.conversation_interactions import (
    active_run_tasks as _active_run_tasks,
    active_stream_conversation_runs as _active_stream_conversation_runs,
    confirm_responses as _confirm_responses,
    pending_confirms as _pending_confirms,
)
from runtime.prompt_context import build_system_prompt
from runtime.run_result_presenter import (
    answer_only_final_answer_error,
    build_execution_notice,
    build_max_rounds_after_write_message,
    run_status_from_result,
)
from runtime.shell_command_facts import shell_command_facts
from runtime.task_runner import ToolContext
from runtime.user_guidance import add_user_guidance, pop_user_guidance
from runtime import tool_event_presentation as _tool_present
from runtime import tool_call_protocol as _tool_proto
from runtime.tool_result_evidence import tool_output_evidence


_ACTIVE_CONVERSATION_RUN_STATUSES = {"running", "waiting_confirmation", "paused"}


def _active_persisted_run_id_for_conversation(runtime: Any, conversation_id: str) -> str:
    try:
        runs = runtime.runs.list(conversation_id=conversation_id)
    except Exception:
        return ""
    for run in runs:
        if str(getattr(run, "status", "") or "") in _ACTIVE_CONVERSATION_RUN_STATUSES:
            return str(getattr(run, "id", "") or "")
    return ""

_TOOL_TASK_FAST_POLL_SECONDS = 0.25
_TOOL_TASK_STEADY_POLL_SECONDS = 1.0
_TOOL_TASK_FAST_POLL_WINDOW_SECONDS = 3.0
_TOOL_TASK_HEARTBEAT_SECONDS = 10.0


def _tool_task_poll_interval(elapsed_seconds: float) -> float:
    if elapsed_seconds < _TOOL_TASK_FAST_POLL_WINDOW_SECONDS:
        return _TOOL_TASK_FAST_POLL_SECONDS
    return _TOOL_TASK_STEADY_POLL_SECONDS


def _message_content_with_attachment_catalog(
    content: str,
    metadata: dict[str, Any],
    *,
    historical: bool = False,
) -> str:
    attachments = metadata.get("attachments") if isinstance(metadata.get("attachments"), list) else []
    rows: list[str] = []
    for item in attachments:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append(
            "- attachment_id={id}; name={name}; media_type={media_type}; size={size}".format(
                id=str(item.get("id")),
                name=str(item.get("name") or "attachment"),
                media_type=str(item.get("media_type") or "application/octet-stream"),
                size=int(item.get("size") or 0),
            )
        )
    if not rows:
        return content
    if historical:
        catalog = (
            "\n\nHistorical message attachments from an earlier turn:\n"
            + "\n".join(rows)
            + "\nThese immutable attachments belong to earlier messages in this conversation; "
            "attachment storage is separate from project paths."
        )
    else:
        catalog = (
            "\n\nCurrent user-provided immutable conversation attachments:\n"
            + "\n".join(rows)
            + "\nAttachment storage is separate from project paths."
    )
    return f"{content}{catalog}"


def _latest_user_message_id(conversation: Any) -> str:
    for item in reversed(getattr(conversation, "messages", []) or []):
        if str(getattr(item, "role", "") or "") == "user":
            return str(getattr(item, "id", "") or "")
    return ""


class ConversationsHandler(ApiHandler):
    def get(self) -> None:
        workspace_id = self.get_argument("workspace_id", None)
        conversations = self.runtime.conversations.list(workspace_id)
        self.finish_json({
            "success": True,
            "data": [item.to_public_dict() for item in conversations],
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        workspace_id = payload.get("workspace_id")
        if not workspace_id:
            raise tornado.web.HTTPError(400, reason="workspace_id is required")
        if not self.runtime.workspaces.get(workspace_id):
            raise tornado.web.HTTPError(404, reason="workspace not found")
        conversation = self.runtime.conversations.create(
            workspace_id, payload.get("title"), mode="terminal",
        )
        self.finish_json({
            "success": True,
            "data": conversation.to_public_dict(include_messages=True),
        })


class ConversationDetailHandler(ApiHandler):
    def get(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        data = conversation.to_public_dict(include_messages=True)

        # 计算当前上下文 token 用量，供前端显示。
        model = self.runtime.settings.get_default_model()
        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if workspace:
            mode_config = get_terminal_config(self.get_lang())
            system_prompt = build_system_prompt(
                settings=self.runtime.settings,
                mode_config=mode_config,
                workspace_path=workspace.path,
                workspace_id=workspace.id,
                user_memory="",
            )
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt}
            ]
            latest_user_message_id = _latest_user_message_id(conversation)
            for item in conversation.messages:
                metadata = getattr(item, "metadata", {}) or {}
                if metadata.get("guidance") and metadata.get("during_run"):
                    continue
                role = "assistant" if item.role == "assistant" else "user"
                messages.append({
                    "role": role,
                    "content": _message_content_with_attachment_catalog(
                        item.content,
                        metadata,
                        historical=not (
                            role == "user"
                            and str(getattr(item, "id", "") or "") == latest_user_message_id
                        ),
                    ),
                })
            if tokenizer_ready():
                data["context_tokens"] = count_messages_tokens(messages)
                data["context_tokens_estimated"] = False
            else:
                data["context_tokens"] = estimate_messages_tokens_fast(messages)
                data["context_tokens_estimated"] = True
            data["context_limit"] = get_context_limit(model, self.runtime.settings)
        else:
            data["context_tokens"] = 0
            data["context_tokens_estimated"] = False
            data["context_limit"] = get_context_limit(model, self.runtime.settings)

        self.finish_json({"success": True, "data": data})

    def delete(self, conversation_id: str) -> None:
        deleted = self.runtime.conversations.delete(conversation_id)
        if not deleted:
            raise tornado.web.HTTPError(404, reason="conversation not found")
        self.runtime.attachments.delete_for_conversation(conversation_id)
        self.finish_json({"success": True})


class ConversationGuidanceHandler(ApiHandler):
    def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        content = str(payload.get("content") or "").strip()
        if not content:
            raise tornado.web.HTTPError(400, reason="content is required")

        pending_count = add_user_guidance(conversation_id, content)
        message = self.runtime.conversations.add_message(
            conversation_id,
            "user",
            content,
            {"guidance": True, "during_run": True},
        )
        self.finish_json({
            "success": True,
            "data": {
                "count": pending_count,
                "message": message.to_public_dict(),
            },
        })


class ConversationMessagesHandler(ApiHandler):
    async def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        content = (payload.get("content") or "").strip()
        if not content:
            raise tornado.web.HTTPError(400, reason="content is required")
        if payload.get("access_scope"):
            self.runtime.settings.update({"access_scope": payload.get("access_scope")})

        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")

        active_run_id = (
            _active_stream_conversation_runs.get(conversation_id)
            or _active_persisted_run_id_for_conversation(self.runtime, conversation_id)
        )
        if active_run_id:
            raise tornado.web.HTTPError(
                409,
                reason=f"conversation already has an active run: {active_run_id}",
            )

        user_message = self.runtime.conversations.add_message(conversation_id, "user", content)
        assistant_content, metadata = await self._build_reply(conversation, workspace.to_public_dict(), content, payload)
        assistant_message = self.runtime.conversations.add_message(
            conversation_id,
            "assistant",
            assistant_content,
            metadata,
        )

        self.finish_json({
            "success": True,
            "data": {
                "conversation": conversation.to_public_dict(include_messages=True),
                "messages": [
                    user_message.to_public_dict(),
                    assistant_message.to_public_dict(),
                ],
            },
        })

    async def _build_reply(
        self,
        conversation: Any,
        workspace: dict[str, Any],
        content: str,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        model = payload.get("model") or self.runtime.settings.get_default_model()
        messages = self._build_model_messages(conversation, workspace)
        try:
            return await generate_chat_completion(
                settings=self.runtime.settings,
                model=model,
                messages=messages,
                enable_thinking=bool(payload.get("enable_thinking", True)),
                reasoning_effort=str(payload.get("reasoning_effort") or "medium"),
            )
        except tornado.web.HTTPError as exc:
            if exc.status_code != 400:
                raise
            text = i18n.t("conv.workspace_hint", self.get_lang(), path=workspace["path"], reason=str(exc.reason))
            return text, {"mode": "local-placeholder", "reason": exc.reason}

    def _build_model_messages(
        self,
        conversation: Any,
        workspace: dict[str, Any],
        *,
        record_memory_usage: bool = True,
    ) -> list[dict[str, Any]]:
        mode_config = get_terminal_config(self.get_lang())
        # 提取最新用户消息，供记忆相关性评分。
        latest_user_message = ""
        for msg in reversed(getattr(conversation, "messages", [])):
            if getattr(msg, "role", "") == "user":
                latest_user_message = msg.content or ""
                break
        memory_context = self.runtime.settings.get_memory_context(
            user_message=latest_user_message,
            workspace_id=str(workspace.get("id") or ""),
            record_usage=record_memory_usage,
        )
        system_prompt = build_system_prompt(
            settings=self.runtime.settings,
            mode_config=mode_config,
            workspace_path=workspace["path"],
            workspace_id=str(workspace.get("id") or ""),
            user_message=latest_user_message,
            user_memory="",
        )
        messages = [{"role": "system", "content": system_prompt}]
        latest_user_message_id = _latest_user_message_id(conversation)
        for item in conversation.messages:
            metadata = getattr(item, "metadata", {}) or {}
            role = "assistant" if item.role == "assistant" else "user"
            messages.append({
                "role": role,
                "content": _message_content_with_attachment_catalog(
                    item.content,
                    metadata,
                    historical=not (
                        role == "user"
                        and str(getattr(item, "id", "") or "") == latest_user_message_id
                    ),
                ),
                "_yuntao_metadata": metadata,
            })
        messages, hygiene_report = _ctx_hygiene.sanitize_model_context(messages)
        self._last_context_hygiene_report = hygiene_report
        self._last_memory_context = memory_context
        return messages

    def _capability_tool_specs(self, mode_config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        allowed_tools: set[str] | None = None
        if mode_config and "tools" in mode_config:
            allowed_tools = set(mode_config["tools"])
        specs: list[dict[str, Any]] = []
        for spec in self.runtime.registry.list_specs():
            tool_id = str(spec.get("id") or "")
            if allowed_tools is not None and tool_id not in allowed_tools:
                continue
            if not self.runtime.settings.is_tool_enabled(tool_id):
                continue
            item = dict(spec)
            item["available"] = bool(self.runtime.is_tool_available(spec))
            metadata_provider = getattr(self.runtime, "tool_runtime_metadata", None)
            if callable(metadata_provider):
                item.update(metadata_provider(spec))
            specs.append(item)
        return specs

    def _build_capability_snapshot(self, mode_config: dict[str, Any] | None = None) -> dict[str, Any]:
        specs = self._capability_tool_specs(mode_config)
        state_changing_tool_ids = {
            str(spec.get("id") or "")
            for spec in specs
            if (
                _clf.is_state_changing_tool(str(spec.get("id") or ""))
                or bool(
                    set(spec.get("effects") or [])
                    & {"file_write", "file_delete", "local_state_change", "external_state_change"}
                )
            )
        }
        capability_issues: list[dict[str, Any]] = []
        mcp_services = getattr(self.runtime, "mcp_services", None)
        if mcp_services is not None and hasattr(mcp_services, "capability_issues"):
            try:
                capability_issues = list(mcp_services.capability_issues())
            except Exception:
                capability_issues = []
        cli_providers = getattr(self.runtime, "cli_providers", None)
        if cli_providers is not None and hasattr(cli_providers, "capability_issues"):
            try:
                capability_issues.extend(list(cli_providers.capability_issues()))
            except Exception:
                pass
        return _cap_preflight.build_capability_snapshot(
            specs,
            state_changing_tool_ids=state_changing_tool_ids,
            capability_issues=capability_issues,
        )

    def _preflight_task_capabilities(
        self,
        task_contract: dict[str, Any],
        capability_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return _cap_preflight.preflight_task_capabilities(task_contract, capability_snapshot)


class ConversationMessagesStreamHandler(ConversationMessagesHandler):
    def flush(self, include_footers: bool = False) -> asyncio.Task[None]:
        return asyncio.create_task(self._safe_flush(include_footers=include_footers))

    async def _safe_flush(self, include_footers: bool = False) -> None:
        if getattr(self, "_client_stream_closed", False):
            return
        try:
            await super().flush(include_footers=include_footers)
        except tornado.iostream.StreamClosedError:
            self._client_stream_closed = True

    async def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        content = (payload.get("content") or "").strip()
        image_data = payload.get("image_data") or ""
        raw_attachment_ids = payload.get("attachment_ids") or []
        if not isinstance(raw_attachment_ids, list):
            raise tornado.web.HTTPError(400, reason="attachment_ids must be an array")
        attachment_ids = list(dict.fromkeys(str(item) for item in raw_attachment_ids if str(item)))
        if len(attachment_ids) > 8:
            raise tornado.web.HTTPError(400, reason="a message supports at most 8 attachments")
        if not content and not image_data and not attachment_ids:
            raise tornado.web.HTTPError(400, reason="content is required")

        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")
        try:
            attachment_records = self.runtime.attachments.validate_for_message(
                attachment_ids,
                workspace_id=conversation.workspace_id,
                conversation_id=conversation_id,
            )
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc

        active_run_id = (
            _active_stream_conversation_runs.get(conversation_id)
            or _active_persisted_run_id_for_conversation(self.runtime, conversation_id)
        )
        if active_run_id:
            raise tornado.web.HTTPError(
                409,
                reason=f"conversation already has an active run: {active_run_id}",
            )
        model = payload.get("model") or self.runtime.settings.get_default_model()
        requested_mode = "terminal"
        effective_mode = self._effective_mode(requested_mode, content, conversation)
        source_run_id = str(payload.get("source_run_id") or "").strip()
        parent_run_id = str(payload.get("parent_run_id") or source_run_id).strip()
        resume_from_checkpoint_id = str(payload.get("resume_from_checkpoint_id") or "").strip()
        prepared_run_id = str(payload.get("prepared_run_id") or "").strip()
        task_id = str(payload.get("task_id") or "").strip()
        if source_run_id:
            source_run = self.runtime.runs.get(source_run_id)
            if not source_run or source_run.conversation_id != conversation_id or source_run.workspace_id != conversation.workspace_id:
                raise tornado.web.HTTPError(409, reason="source run belongs to another conversation or workspace")
            if not task_id:
                task_id = source_run.task_id
        prepared_run = self.runtime.runs.get(prepared_run_id) if prepared_run_id else None
        if prepared_run_id and not prepared_run:
            raise tornado.web.HTTPError(404, reason="prepared run not found")
        if prepared_run and prepared_run.status != "created":
            raise tornado.web.HTTPError(409, reason=f"prepared run is not startable: {prepared_run.status}")
        if prepared_run and (
            prepared_run.conversation_id != conversation_id
            or prepared_run.workspace_id != conversation.workspace_id
        ):
            raise tornado.web.HTTPError(409, reason="prepared run belongs to another conversation or workspace")
        if prepared_run:
            task_id = prepared_run.task_id
        product_task = self.runtime.product_tasks.get(task_id) if task_id else None
        if task_id and not product_task:
            raise tornado.web.HTTPError(404, reason="task not found")
        if product_task and product_task.workspace_id != conversation.workspace_id:
            raise tornado.web.HTTPError(409, reason="task belongs to another workspace")
        if product_task and product_task.conversation_id != conversation_id:
            raise tornado.web.HTTPError(409, reason="task belongs to another conversation")
        if prepared_run and product_task and product_task.current_run_id != prepared_run.id:
            raise tornado.web.HTTPError(409, reason="prepared run has been superseded by another attempt")
        if product_task and product_task.state in {"completed", "cancelled"}:
            raise tornado.web.HTTPError(409, reason="terminal tasks require an explicit replay to create a new task")
        if not prepared_run and product_task and product_task.current_run_id and product_task.state in {
            "running", "planning", "waiting_confirmation", "verifying", "resuming",
        }:
            raise tornado.web.HTTPError(409, reason="task already has an active run")

        # 引用和状态校验全部通过后才持久化消息；预约使用请求独有标识。
        reservation = f"pending:{uuid4()}"
        _active_stream_conversation_runs[conversation_id] = reservation
        run = None
        task = None
        try:
            if payload.get("access_scope"):
                self.runtime.settings.update({"access_scope": payload.get("access_scope")})
            self.set_header("Content-Type", "application/x-ndjson; charset=utf-8")
            msg_metadata: dict[str, Any] = {}
            if image_data:
                msg_metadata["has_image"] = True
            if attachment_records:
                msg_metadata["attachments"] = [record.to_public_dict() for record in attachment_records]
                msg_metadata["has_image"] = any(record.is_image for record in attachment_records)
            user_message = self.runtime.conversations.add_message(
                conversation_id,
                "user",
                content or ("[Attachment]" if attachment_records else self.t("conv.image_placeholder")),
                msg_metadata,
            )
            self.runtime.attachments.bind_message(attachment_ids, user_message.id)
            self.write_event({"event": "user", "message": user_message.to_public_dict()})
            await self.flush()

            if not product_task:
                product_task = self.runtime.product_tasks.create(
                    goal=content or ("Process attachments" if attachment_records else "Process image"),
                    conversation_id=conversation_id,
                    workspace_id=conversation.workspace_id,
                    kind="conversation_task",
                    metadata={"source": "conversation"},
                )
            if prepared_run:
                run = prepared_run
                source_run_id = run.source_run_id
                resume_from_checkpoint_id = run.resume_from_checkpoint_id
                payload["source_run_id"] = source_run_id
                payload["resume_from_checkpoint_id"] = resume_from_checkpoint_id
                self.runtime.run_events.emit(run.id, {
                    "event": "status",
                    "status": "resumed",
                    "message": "prepared replay run started",
                })
            else:
                attempt = max(1, int(product_task.run_count or 0) + 1)
                run = self.runtime.runs.create(
                    conversation_id=conversation_id,
                    workspace_id=conversation.workspace_id,
                    mode=effective_mode,
                    user_content=content or ("[attachment]" if attachment_records else "[image]"),
                    task_id=product_task.id,
                    parent_run_id=parent_run_id,
                    source_run_id=source_run_id,
                    attempt=attempt,
                    resume_from_checkpoint_id=resume_from_checkpoint_id,
                )
                self.runtime.product_tasks.attach_run(product_task.id, run.id)
            self._active_run_id = run.id
            self._active_conversation_id = conversation_id
            _active_stream_conversation_runs[conversation_id] = run.id
            self.write_event({"event": "run", "run": run.to_public_dict(include_events=True)})
            await self.flush()
            executor = ConversationRunExecutor(
                self,
                run_id=run.id,
                conversation_id=conversation_id,
            )
            event_queue = self.runtime.run_events.subscribe(run.id)

            async def execute_run() -> None:
                try:
                    await executor.execute(
                        conversation_id=conversation_id,
                        conversation=conversation,
                        workspace=workspace,
                        payload=payload,
                        content=content,
                        image_data=image_data,
                        attachments=attachment_records,
                        model=model,
                        requested_mode=requested_mode,
                        effective_mode=effective_mode,
                        run=run,
                    )
                except Exception as exc:
                    self.runtime.run_events.emit(run.id, {
                        "event": "error",
                        "error": str(exc) or exc.__class__.__name__,
                    })
                finally:
                    current = self.runtime.runs.get(run.id)
                    if current and current.stage != "done":
                        # 覆盖 Provider 提前返回和未经过 Finalizer 的异常退出。
                        self.runtime.run_events.emit(run.id, {
                            "event": "done",
                            "run_status": current.status if current.status in {"failure", "stopped", "cancelled"} else "failure",
                        })

            task = asyncio.create_task(execute_run())
            _active_run_tasks[run.id] = task

            def release_execution(completed: asyncio.Task[None]) -> None:
                # HTTP 连接关闭不代表执行结束；控制句柄和会话占用随后台执行释放。
                if _active_run_tasks.get(run.id) is completed:
                    _active_run_tasks.pop(run.id, None)
                if _active_stream_conversation_runs.get(conversation_id) == run.id:
                    _active_stream_conversation_runs.pop(conversation_id, None)

            task.add_done_callback(release_execution)
            try:
                while True:
                    if getattr(self, "_client_stream_closed", False):
                        return
                    if task.done() and event_queue.empty():
                        break
                    try:
                        event_data = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        self.write_json_line({
                            "event": "heartbeat",
                            "run_id": run.id,
                            "message": self.t("conv.model_processing"),
                            "phase": "run_stream",
                            "connection_alive": True,
                        })
                        await self.flush()
                        continue
                    payload_for_client = dict(event_data)
                    payload_for_client.pop("time", None)
                    self.write_json_line(payload_for_client)
                    await self.flush()
                    if payload_for_client.get("event") == "done":
                        break
                    if (
                        payload_for_client.get("event") == "error"
                        and payload_for_client.get("terminal", True) is not False
                    ):
                        break
            finally:
                self.runtime.run_events.unsubscribe(run.id, event_queue)
        finally:
            if task is None:
                try:
                    if run is not None:
                        self.runtime.run_events.emit(run.id, {
                            "event": "error", "error": "run setup interrupted before execution",
                        })
                        self.runtime.run_events.emit(run.id, {"event": "done", "run_status": "failure"})
                finally:
                    owned_ids = {reservation} | ({run.id} if run is not None else set())
                    if _active_stream_conversation_runs.get(conversation_id) in owned_ids:
                        _active_stream_conversation_runs.pop(conversation_id, None)


    def _normalize_confirmation_policy(self, payload: dict[str, Any]) -> str:
        return _cp.normalize_confirmation_policy(
            payload.get("confirmation_policy"),
            self.runtime.settings.get_confirmation_policy(),
        )

    def _build_task_contract(
        self,
        *,
        task_intent: str,
        mode: str | None,
        planning_policy: str,
        confirmation_policy: str,
        workspace_path: str,
        expected_document_coverage: bool = False,
        expected_min_output_chars: int = 0,
        source: str = "policy",
    ) -> dict[str, Any]:
        return _tc.default_task_contract(
            task_intent=task_intent,
            mode=mode,
            planning_policy=planning_policy,
            confirmation_policy=confirmation_policy,
            workspace_path=workspace_path,
            access_scope=self.runtime.settings.get_access_scope(),
            expected_document_coverage=expected_document_coverage,
            expected_min_output_chars=expected_min_output_chars,
            source=source,
        )


    async def _run_auxiliary_model_call(
        self,
        *,
        purpose: str,
        model: str,
        messages: list[dict[str, Any]],
        enable_thinking: bool,
        reasoning_effort: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> tuple[str, dict[str, Any]]:
        observable = bool(getattr(self, "_active_run_id", ""))
        return await run_model_call(
            purpose=purpose,
            settings=self.runtime.settings,
            model=model,
            messages=messages,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            tools=tools,
            tool_choice=tool_choice,
            generate=generate_chat_completion,
            emit=self.write_event if observable else None,
            flush=self.flush if observable else None,
        )


    def _explorer_tool_ids(self, mode: str | None) -> set[str]:
        return _clf.explorer_tool_ids(mode)


    def _normalize_tool_id(self, value: Any) -> str:
        return _clf.canonical_tool_id(value)


    def _build_model_tools(
        self,
        mode_config: dict[str, Any] | None = None,
        *,
        allowed_tool_ids: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        allowed_tools: set[str] | None = None
        if mode_config and "tools" in mode_config:
            allowed_tools = set(mode_config["tools"])
        tools: list[dict[str, Any]] = []
        name_map: dict[str, str] = {}
        for spec in order_tool_specs_for_model_prompt(self._capability_tool_specs(mode_config)):
            if allowed_tools is not None and spec["id"] not in allowed_tools:
                continue
            if allowed_tool_ids is not None and spec["id"] not in allowed_tool_ids:
                continue
            if not self.runtime.settings.is_tool_enabled(spec["id"]):
                continue
            if not bool(spec.get("available")):
                continue
            model_name = self._model_tool_name(spec["id"])
            name_map[model_name] = spec["id"]
            name_map[spec["id"]] = spec["id"]
            tools.append({
                "type": "function",
                "function": {
                    "name": model_name,
                    "description": self._model_tool_description(spec),
                    "parameters": spec["input_schema"],
                },
            })
        return tools, name_map

    def _model_tool_name(self, tool_id: str) -> str:
        return tool_id.replace(".", "__")

    def _model_tool_description(self, spec: dict[str, Any]) -> str:
        description = str(spec.get("description") or "")
        if str(spec.get("source_type") or "") != "mcp":
            return description
        health = str(spec.get("tool_health") or "available")
        if health == "available":
            return description
        last_error = str(spec.get("tool_last_error") or "").strip()
        note = f"Runtime health: {health}."
        if last_error:
            note += f" Last error: {last_error[:240]}."
        note += " This is a readiness fact; the model decides whether and how to use this capability."
        return f"{description}\n\n{note}" if description else note

    def _messages_for_model_round(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        return _clf.messages_for_model_round(messages, tools)

    def _complete_tool_calls(self, calls: list[dict[str, Any]], round_index: int) -> list[dict[str, Any]]:
        return _clf.complete_tool_calls(calls, round_index)

    def _extract_native_tool_calls(self, text: str, round_index: int) -> list[dict[str, Any]]:
        return _clf.extract_native_tool_calls(text, round_index)

    def _tool_call_details(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        function = tool_call.get("function") or {}
        model_tool_name = function.get("name") or ""
        tool_id = self._normalize_tool_id(
            tool_name_map.get(model_tool_name) or model_tool_name,
        )
        arguments_text = function.get("arguments") or "{}"
        try:
            arguments = json.loads(arguments_text)
            if not isinstance(arguments, dict):
                arguments = {}
        except json.JSONDecodeError:
            arguments = {}
        if "path" not in arguments:
            for alias in ("file_path", "filepath", "dir_path", "folder_path"):
                if alias in arguments:
                    arguments["path"] = arguments[alias]
                    break
        return tool_id, arguments

    def _tool_signature(self, tool_id: str, arguments: dict[str, Any]) -> str:
        return _clf.tool_signature(tool_id, arguments)

    def _document_write_tool_ids(self) -> set[str]:
        return set(_clf.DOCUMENT_WRITE_TOOL_IDS)

    def _write_tool_ids(self) -> set[str]:
        return set(_clf.WRITE_TOOL_IDS)

    def _read_only_tool_ids(self, mode: str | None) -> set[str]:
        ids = self._explorer_tool_ids(mode)
        ids |= {"git.status", "git.diff", "git.log"}
        return ids

    def _deliverable_verification_tool_ids(self) -> set[str]:
        return set(_clf.DELIVERABLE_VERIFICATION_TOOL_IDS)

    def _verification_tool_ids(self, mode: str | None) -> set[str]:
        _ = mode
        return _clf.verification_tool_ids(None)

    def _execution_pressure_tool_ids(self, mode: str | None) -> set[str]:
        return (
            self._write_tool_ids()
            | self._explorer_tool_ids(mode)
            | {"git.status", "git.diff"}
        )

    def _is_write_tool(self, tool_id: str) -> bool:
        return _clf.is_write_tool(tool_id)

    def _is_state_changing_tool(self, tool_id: str) -> bool:
        if _clf.is_state_changing_tool(tool_id):
            return True
        try:
            spec = self.runtime.registry.get(tool_id).spec
        except KeyError:
            return False
        return "external_state_change" in set(spec.effects or [])

    def _is_verification_tool(self, tool_id: str, mode: str | None) -> bool:
        return tool_id in self._verification_tool_ids(mode)

    def _filter_tools_by_ids(
        self,
        tools: list[dict[str, Any]],
        tool_name_map: dict[str, str],
        allowed_ids: set[str],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            model_name = str(function.get("name") or "")
            tool_id = self._normalize_tool_id(tool_name_map.get(model_name) or model_name)
            if tool_id in allowed_ids:
                result.append(tool)
        return result

    def _is_recon_tool(self, tool_id: str) -> bool:
        return _clf.is_recon_tool(tool_id)

    def _skipped_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_id: str,
        arguments: dict[str, Any],
        *,
        reason: str,
        message: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        function = tool_call.get("function") or {}
        model_tool_name = (function.get("name") or self._model_tool_name(tool_id))
        raw_arguments_text = str(function.get("arguments") or "")
        observation = _tool_proto.build_tool_attempt_observation(
            tool_id=tool_id,
            arguments=arguments,
            reason=reason,
            message=message,
            raw_tool_name=str(model_tool_name or ""),
            raw_arguments_text=raw_arguments_text,
            missing_fields=self._tool_attempt_missing_fields(tool_id, arguments, reason),
        )
        output = _tool_proto.tool_attempt_output(observation)
        event = {
            "status": "failure",
            "tool": tool_id,
            "name": self._tool_display_name(tool_id),
            "input": arguments,
            "task_id": "",
            "error": message,
            "output": output,
            "tool_attempt_observation": observation,
        }
        try:
            event.update(self.runtime.registry.get(tool_id).spec.to_event_contract())
        except KeyError:
            pass
        tool_payload = {
            "tool": tool_id,
            "input": arguments,
            "status": "failure",
            "output": output,
            "error": message,
        }
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": model_tool_name,
            "content": self._compact_tool_payload(tool_payload),
        }, event

    def _tool_attempt_missing_fields(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        reason: str,
    ) -> list[str]:
        if reason != "invalid_tool_input":
            return []
        try:
            return list(self.runtime.registry.missing_required_input_fields(tool_id, arguments))
        except Exception:
            return []


    def _has_unresolved_tool_call_markup(self, content: str) -> bool:
        return _clf.has_unresolved_tool_call_markup(content)

    def _strip_native_tool_call_blocks(self, content: str) -> str:
        return _clf.strip_native_tool_call_blocks(content)


    def _answer_only_final_answer_error(
        self,
        content: str,
        tool_events: list[dict[str, Any]],
        task_contract: dict[str, Any] | None = None,
    ) -> str:
        return answer_only_final_answer_error(content, tool_events, task_contract)


    def _run_status_from_result(self, run_result: dict[str, Any]) -> str:
        return run_status_from_result(run_result)


    def _tool_event_failed(self, event: dict[str, Any]) -> bool:
        if str(event.get("status") or "") == "failure":
            return True
        if str(event.get("status") or "") == "partial":
            return False
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        if output.get("error") is True:
            return True
        if str(event.get("tool") or "") == "shell.run_command":
            if output.get("timed_out") is True:
                return True
            try:
                return int(output.get("exit_code", 0) or 0) != 0
            except (TypeError, ValueError):
                return False
        return False

    def _tool_event_failure_message(self, event: dict[str, Any]) -> str:
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        if output.get("timed_out") is True:
            event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
            timeout = output.get("timeout") or event_input.get("timeout")
            message = f"command timed out after {timeout}s" if timeout else "command timed out"
            detail = str(output.get("stderr") or output.get("stdout") or "").strip()
            return f"{message}: {detail}" if detail else message
        error = str(event.get("error") or "").strip()
        if error:
            return error
        stderr = str(output.get("stderr") or "").strip()
        stdout = str(output.get("stdout") or "").strip()
        if stderr:
            return stderr
        if stdout:
            return stdout
        if output.get("exit_code") is not None:
            return f"exit_code={output.get('exit_code')}"
        return "工具执行失败"

    def _tool_event_display_path(self, workspace_path: str, event: dict[str, Any]) -> str:
        event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        path = (
            output.get("path")
            or output.get("output_path")
            or event_input.get("output_path")
            or event_input.get("path")
            or ""
        )
        if not path:
            return ""
        return self._relative_workspace_path(workspace_path, str(path))


    def _runtime_confirmation_decision(self, tool_id: str) -> _cp.ConfirmationDecision:
        try:
            tool = self.runtime.registry.get(tool_id)
        except KeyError:
            return _cp.decide_tool_confirmation(
                getattr(self, "_active_confirmation_policy", "auto"),
                tool_id,
                declared_confirmation=True,
            )
        return _cp.decide_tool_confirmation(
            getattr(self, "_active_confirmation_policy", "auto"),
            tool_id,
            declared_confirmation=bool(tool.spec.requires_confirmation),
        )


    def _ai_plugin_draft_workspace_guard(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        workspace_path: str | None,
    ) -> str:
        return ai_plugin_draft_workspace_guard_message(
            tool_id=tool_id,
            input_data=arguments,
            workspace_path=workspace_path,
            data_dir=getattr(getattr(self.runtime, "settings", None), "data_dir", None),
        )

    def _tool_execution_guard_decision(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        workspace_path: str | None,
    ):
        return evaluate_tool_execution_guard(
            tool_id,
            arguments,
            workspace_path,
            ToolExecutionGuardChecks(
                is_tool_enabled=self.runtime.settings.is_tool_enabled,
                is_tool_available=lambda current_tool_id: self.runtime.is_tool_available(
                    self.runtime.registry.get_public_spec(current_tool_id)
                ),
                missing_required_input_fields=self.runtime.registry.missing_required_input_fields,
                ai_plugin_draft_workspace_message=self._ai_plugin_draft_workspace_guard,
            ),
        )

    def _runtime_confirmation_message(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        decision: _cp.ConfirmationDecision | None = None,
    ) -> str:
        target = self._runtime_confirmation_target(arguments)
        operation = self._runtime_confirmation_operation(tool_id, arguments, target)
        lines = ["即将执行需要确认的本地操作。"]
        contract = getattr(self, "_active_task_contract", None)
        if isinstance(contract, dict):
            goal = str(contract.get("goal") or "").strip()
            if goal:
                lines.append(f"任务目标：{goal}")
        lines.append(f"操作：{operation}")
        lines.append(f"工具：{self._tool_display_name(tool_id)}（{tool_id}）")
        if decision is not None:
            lines.append(f"确认策略：{decision.policy}")
            lines.append(f"风险类型：{decision.risk}")
        if target:
            lines.append(f"目标：{target}")
        if tool_id == "shell.run_command":
            command = str(arguments.get("command") or "").strip()
            args = arguments.get("args")
            argv = [str(item) for item in args] if isinstance(args, (list, tuple)) else []
            facts = shell_command_facts(command, argv)
            if command:
                lines.append(f"命令：{command}")
            if argv:
                lines.append(f"参数：{' '.join(argv)[:500]}")
            if arguments.get("cwd"):
                lines.append(f"工作目录：{arguments['cwd']}")
            lines.append(f"最长运行：{arguments.get('timeout', facts.default_timeout)} 秒")
        if tool_id == "filesystem.write_file" and isinstance(arguments.get("content"), str):
            lines.append(f"内容大小：{len(arguments['content'])} 字符")
        lines.append("确认后会在本地工作区执行；5 分钟内未响应将自动取消。")
        return "\n".join(lines)

    def _runtime_confirmation_target(self, arguments: dict[str, Any]) -> str:
        patch = arguments.get("patch")
        if isinstance(patch, str):
            paths: list[str] = []
            for line in patch.splitlines():
                for prefix in ("*** Add File: ", "*** Update File: "):
                    if line.startswith(prefix):
                        path = line[len(prefix):].strip()
                        if path and path not in paths:
                            paths.append(path)
            if paths:
                return ", ".join(paths[:4])
        return str(
            arguments.get("path")
            or arguments.get("output_path")
            or arguments.get("output_dir")
            or ""
        ).strip()

    def _runtime_confirmation_operation(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        target: str,
    ) -> str:
        if tool_id == "code.apply_patch":
            return "应用代码补丁"
        if tool_id == "shell.run_command":
            return shell_command_facts(
                arguments.get("command"),
                arguments.get("args"),
            ).operation_label
        if tool_id == "filesystem.delete_file":
            return "Delete file"
        if tool_id.startswith("mcp_"):
            if target:
                return "更新外部应用状态"
            return "执行外部 MCP 操作"
        if target:
            exists = False
            is_dir = False
            try:
                path = Path(target)
                exists = path.exists()
                is_dir = path.is_dir()
            except (OSError, ValueError):
                exists = False
                is_dir = False
            if is_dir or arguments.get("output_dir"):
                return "更新目录内容" if exists else "创建/使用输出目录"
            if tool_id in self._document_write_tool_ids():
                return "更新文档" if exists else "生成文档"
            return "覆盖/更新文件" if exists else "创建文件"
        if tool_id in self._document_write_tool_ids():
            return "生成或更新文档"
        return "写入文件"

    async def _confirm_runtime_tool_call(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        decision: _cp.ConfirmationDecision,
    ) -> bool:
        conversation_id = str(getattr(self, "_active_conversation_id", "") or "")
        if not conversation_id:
            return True

        confirm_event = asyncio.Event()
        _pending_confirms[conversation_id] = confirm_event
        _confirm_responses.pop(conversation_id, None)
        self.write_event({
            "event": "confirm",
            "message": self._runtime_confirmation_message(tool_id, arguments, decision),
            "tool": tool_id,
            "input": arguments,
            "confirmation_decision": decision.to_dict(),
        })
        await self.flush()
        try:
            await asyncio.wait_for(confirm_event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            pass
        finally:
            _pending_confirms.pop(conversation_id, None)
        confirmed = _confirm_responses.pop(conversation_id, "cancel") == "continue"
        run_id = str(getattr(self, "_active_run_id", "") or "")
        current = self.runtime.runs.get(run_id) if run_id else None
        if current and current.status == "waiting_confirmation":
            self.write_event({
                "event": "status", "status": "resumed",
                "message": "操作确认等待已结束，继续处理当前任务。",
            })
            await self.flush()
        return confirmed

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
        workspace_path: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        function = tool_call.get("function") or {}
        model_tool_name = function.get("name") or ""
        tool_id = tool_name_map.get(model_tool_name) or model_tool_name.replace("__", ".")
        arguments_text = function.get("arguments") or "{}"
        arguments, argument_error = _clf.parse_tool_arguments_strict(arguments_text)
        if argument_error:
            return self._skipped_tool_call(
                tool_call,
                tool_id,
                arguments,
                reason=argument_error,
                message=(
                    "Tool arguments were incomplete, malformed, or not a JSON object. "
                    "The runtime did not execute this call."
                ),
            )

        try:
            tool_id = self.runtime.registry.resolve_id(tool_id)
            tool_spec = self.runtime.registry.get(tool_id).spec
            arguments = self.runtime.registry.normalize_input_data(tool_id, arguments)
        except KeyError:
            return self._skipped_tool_call(
                tool_call,
                tool_id,
                arguments,
                reason="unknown_tool",
                message=f"未知工具：{tool_id}。本次调用未执行。",
            )

        guard_decision = self._tool_execution_guard_decision(tool_id, arguments, workspace_path)
        if guard_decision:
            return self._skipped_tool_call(
                tool_call,
                tool_id,
                arguments,
                reason=guard_decision.reason,
                message=guard_decision.message,
            )

        confirmation_decision = self._runtime_confirmation_decision(tool_id)
        if confirmation_decision.requires_confirmation:
            confirmed = await self._confirm_runtime_tool_call(tool_id, arguments, confirmation_decision)
            if not confirmed:
                return self._skipped_tool_call(
                    tool_call,
                    tool_id,
                    arguments,
                    reason="user_cancelled_tool",
                    message=f"用户取消了写入工具调用：{tool_id}",
                )
            await self._wait_if_paused()

        task = await self.runtime.runner.submit(
            tool_id,
            arguments,
            wait=False,
            confirmed=True,
            workspace_path=workspace_path,
            workspace_id=getattr(self, "_active_workspace_id", ""),
            artifact_scope_id=getattr(self, "_active_run_id", "") or None,
            attachment_ids=getattr(self, "_active_attachment_ids", ()),
        )
        event: dict[str, Any] = {
            "status": "running",
            "tool": tool_id,
            "name": self._tool_display_name(tool_id),
            "input": arguments,
            "task_id": task.id,
            "progress": self._tool_progress_snapshot(tool_id, task),
            "confirmation_decision": confirmation_decision.to_dict(),
            **tool_spec.to_event_contract(),
        }
        self.write_event({"event": "tool", **event})
        await self.flush()

        started_at = asyncio.get_running_loop().time()
        last_log_count = len(task.logs)
        last_progress_at = started_at
        last_heartbeat_at = started_at
        try:
            while task.status in {"queued", "running"}:
                elapsed_before_poll = asyncio.get_running_loop().time() - started_at
                await asyncio.sleep(_tool_task_poll_interval(elapsed_before_poll))
                current = self.runtime.tool_tasks.get(task.id) or task
                new_logs = current.logs[last_log_count:]
                emitted_progress = False
                if new_logs:
                    last_log_count = len(current.logs)
                    last_progress_at = asyncio.get_running_loop().time()
                    for log_event in new_logs[-3:]:
                        self.write_event({
                            "event": "tool_log",
                            "tool": tool_id,
                            "name": self._tool_display_name(tool_id),
                            "task_id": task.id,
                            "level": log_event.get("level"),
                            "message": log_event.get("message"),
                            "data": log_event.get("data") or {},
                            "progress": self._tool_progress_snapshot(tool_id, current),
                        })
                    emitted_progress = True
                task = current
                if task.status not in {"queued", "running"}:
                    if emitted_progress:
                        await self.flush()
                    break
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat_at >= _TOOL_TASK_HEARTBEAT_SECONDS:
                    last_heartbeat_at = now
                    elapsed = int(now - started_at)
                    stale_seconds = int(now - last_progress_at)
                    progress = self._tool_progress_snapshot(tool_id, task)
                    self.write_event({
                        "event": "heartbeat",
                        "message": self._tool_progress_message(tool_id, task, elapsed, stale_seconds, progress),
                        "idle_seconds": elapsed,
                        "tool": tool_id,
                        "name": self._tool_display_name(tool_id),
                        "task_id": task.id,
                        "task_status": task.status,
                        "stale_seconds": stale_seconds,
                        "progress": progress,
                    })
                    emitted_progress = True
                if emitted_progress:
                    await self.flush()
        except asyncio.CancelledError:
            self.runtime.runner.cancel(task.id)
            raise
        task = self.runtime.tool_tasks.get(task.id) or task
        output_preview = self._tool_output_preview(tool_id, task.output)
        task_error = task.error
        if task.status == "failure":
            task_error = self._tool_event_failure_message({
                "tool": tool_id,
                "status": task.status,
                "input": arguments,
                "output": task.output,
                "error": task.error,
            })
        event = {
            "status": task.status,
            "tool": tool_id,
            "name": self._tool_display_name(tool_id),
            "input": arguments,
            "task_id": task.id,
            "error": task_error,
            "output": tool_output_evidence(task.output),
            "output_preview": output_preview,
            "output_source": {"kind": "tool_task_output", "task_id": task.id},
            "progress": self._tool_progress_snapshot(tool_id, task),
            **tool_spec.to_event_contract(),
        }
        tool_payload = _tool_risks.attach_tool_result_risks({
            "tool": tool_id,
            "task_id": task.id,
            "input": arguments,
            "status": task.status,
            "output": event["output"],
            "error": task_error,
        })
        if tool_payload.get("runtime_risks"):
            event["runtime_risks"] = tool_payload["runtime_risks"]
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": model_tool_name,
            "content": self._compact_tool_payload(tool_payload),
        }, event

    def _tool_progress_snapshot(self, tool_id: str, task: Any) -> dict[str, Any]:
        return _tool_present.tool_progress_snapshot(tool_id, task)

    def _tool_progress_message(
        self,
        tool_id: str,
        task: Any,
        elapsed_seconds: int,
        stale_seconds: int,
        progress: dict[str, Any],
    ) -> str:
        return _tool_present.tool_progress_message(
            tool_id,
            task,
            elapsed_seconds,
            stale_seconds,
            progress,
            display_name=self._tool_display_name(tool_id),
        )

    def _tool_display_name(self, tool_id: str) -> str:
        try:
            return self.runtime.registry.get(tool_id).spec.name
        except KeyError:
            return tool_id

    def _tool_output_preview(self, tool_id: str, output: Any) -> dict[str, Any] | None:
        return _tool_present.tool_output_preview(tool_id, output)

    async def _capture_git_status(
        self,
        workspace_path: str,
        mode_config: dict[str, Any],
    ) -> dict[str, Any] | None:
        if mode_config.get("tools") and "git.status" not in set(mode_config.get("tools") or []):
            return None
        try:
            tool = self.runtime.registry.get("git.status")
            context = ToolContext(
                path_guard=self.runtime.runner.path_guard,
                task_id="internal.git.status",
                log=lambda *_args, **_kwargs: None,
            )
            output = await tool.handler({"path": workspace_path}, context)
        except Exception:
            return None
        return output if isinstance(output, dict) else None

    async def _build_change_summary(
        self,
        workspace_path: str,
        mode_config: dict[str, Any],
        baseline: dict[str, Any] | None,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        final_status = await self._capture_git_status(workspace_path, mode_config)
        touched_paths = self._collect_touched_paths(workspace_path, tool_events)
        if not final_status:
            if not touched_paths:
                return None
            return {
                "source": "tool-events",
                "clean": None,
                "files": [{"status": "touched", "path": path} for path in touched_paths[:80]],
                "file_count": len(touched_paths),
                "total_dirty_count": None,
                "truncated": len(touched_paths) > 80,
            }

        final_files = final_status.get("files") or []
        baseline_files = baseline.get("files") if baseline else []
        baseline_map = {
            self._normalize_display_path(item.get("path")): str(item.get("status") or "")
            for item in baseline_files or []
            if isinstance(item, dict) and item.get("path")
        }
        touched_set = set(touched_paths)
        changed_files: list[dict[str, str]] = []
        for item in final_files:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            path = self._normalize_display_path(item.get("path"))
            status = str(item.get("status") or "")
            if baseline is None or baseline_map.get(path) != status or path in touched_set:
                changed_files.append({"status": status, "path": path})

        known_paths = {item["path"] for item in changed_files}
        for path in touched_paths:
            if path not in known_paths:
                changed_files.append({"status": "clean", "path": path})
                known_paths.add(path)

        if not changed_files:
            return None

        return {
            "source": "git-status",
            "branch": final_status.get("branch") or "",
            "clean": bool(final_status.get("clean")),
            "files": changed_files[:80],
            "file_count": len(changed_files),
            "total_dirty_count": int(final_status.get("file_count") or 0),
            "truncated": len(changed_files) > 80,
        }

    def _collect_touched_paths(self, workspace_path: str, tool_events: list[dict[str, Any]]) -> list[str]:
        paths: list[str] = []
        for event in tool_events:
            if event.get("status") != "success":
                continue
            tool_id = event.get("tool")
            if not self._is_write_tool(str(tool_id or "")):
                continue
            output = event.get("output") if isinstance(event.get("output"), dict) else {}
            input_data = event.get("input") if isinstance(event.get("input"), dict) else {}
            candidates: list[Any] = []
            if tool_id == "code.apply_patch":
                candidates.extend(output.get("paths") or [])
            elif tool_id == "code.replace_text":
                root = output.get("root") or input_data.get("path") or workspace_path
                for item in output.get("changed_files") or []:
                    if isinstance(item, dict) and item.get("path"):
                        candidates.append(str(Path(str(root)) / str(item["path"])))
                if not candidates:
                    candidates.append(root)
            else:
                candidates.append(
                    output.get("path")
                    or output.get("output_path")
                    or input_data.get("output_path")
                    or input_data.get("path")
                )
            for candidate in candidates:
                rel = self._relative_workspace_path(workspace_path, candidate)
                if rel and rel not in paths:
                    paths.append(rel)
        return paths

    def _relative_workspace_path(self, workspace_path: str, path_value: Any) -> str:
        if not path_value:
            return ""
        text = str(path_value)
        try:
            path = Path(text)
            if path.is_absolute():
                return self._normalize_display_path(path.relative_to(Path(workspace_path)))
        except ValueError:
            return self._normalize_display_path(text)
        except OSError:
            return self._normalize_display_path(text)
        return self._normalize_display_path(text)

    def _normalize_display_path(self, path_value: Any) -> str:
        return str(path_value or "").replace("\\", "/")

    def _is_user_guidance_message(self, message: Any) -> bool:
        return _task_ctx.is_user_guidance_message(message)

    def _discard_parts(self, target: list[str], parts: list[str]) -> None:
        if not parts:
            return
        del target[-len(parts):]

    def _read_file_range_record(
        self,
        arguments: dict[str, Any],
        tool_event: dict[str, Any],
    ) -> dict[str, Any]:
        output = tool_event.get("output") if isinstance(tool_event.get("output"), dict) else {}
        path = str(output.get("path") or arguments.get("path") or "")
        start_line = output.get("start_line") or arguments.get("start_line") or 1
        end_line = output.get("end_line") or arguments.get("end_line")
        total_lines = output.get("total_lines")
        next_start_line = output.get("next_start_line")
        next_end_line = output.get("next_end_line")
        return {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": total_lines,
            "truncated": bool(output.get("truncated")),
            "next_start_line": next_start_line,
            "next_end_line": next_end_line,
        }

    def _has_recent_task_context(self, conversation: Any | None, current_content: str) -> bool:
        return _task_ctx.has_recent_task_context(conversation, current_content)

    def _task_lineage_candidates(
        self,
        conversation: Any | None,
        current_content: str,
    ) -> list[dict[str, Any]]:
        return _task_ctx.task_lineage_candidates(conversation, current_content)

    def _task_lineage_availability(
        self,
        candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    ) -> dict[str, Any]:
        return _task_ctx.task_lineage_availability(candidates)

    def _referenced_task_candidate_contract(
        self,
        candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
        candidate_id: Any,
    ) -> dict[str, Any] | None:
        return _task_ctx.referenced_task_candidate_contract(candidates, candidate_id)


    def _effective_mode(
        self,
        requested_mode: str | None,
        content: str,
        conversation: Any | None = None,
    ) -> str:
        _ = (requested_mode, content, conversation)
        return "terminal"


    def _is_recoverable_write_failure(self, tool_id: str, event: dict[str, Any]) -> bool:
        return _clf.is_recoverable_write_failure(tool_id, event)


    def _pop_user_guidance(self, conversation_id: str) -> tuple[str, str]:
        batch = pop_user_guidance(conversation_id)
        if not batch.items:
            return "", ""
        return batch.prompt, batch.text


    def _max_rounds_message(self, max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
        return _prp.max_rounds_message(max_rounds, tool_events)

    def _max_rounds_after_write_message(self, max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
        return build_max_rounds_after_write_message(
            max_rounds,
            tool_events,
            is_write_tool=self._is_write_tool,
        )

    def _build_execution_notice(
        self,
        mode: str | None,
        assistant_content: str,
        tool_events: list[dict[str, Any]],
        *,
        requires_code_write: bool = False,
        contract_failed: bool = False,
        max_rounds_exceeded: bool = False,
        run_result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return build_execution_notice(
            mode,
            assistant_content,
            tool_events,
            requires_code_write=requires_code_write,
            contract_failed=contract_failed,
            max_rounds_exceeded=max_rounds_exceeded,
            run_result=run_result,
            is_write_tool=self._is_write_tool,
            is_invalid_verification_method_event=_clf.is_invalid_verification_method_event,
            assistant_claims_code_changed=self._assistant_claims_code_changed,
        )

    def _assistant_claims_code_changed(self, content: str) -> bool:
        text = content.lower()
        claim_terms = (
            "已修改",
            "已经修改",
            "修改完成",
            "已修复",
            "修复完成",
            "已经修复",
            "已成功",
            "成功修改",
            "成功修复",
            "已新增",
            "已写入",
            "已经添加",
            "已经改",
            "改为",
            "改成",
        )
        code_terms = (
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".vue",
            ".html",
            ".css",
            ".json",
            "代码",
            "文件",
            "端口",
            "配置",
            "函数",
            "组件",
        )
        return any(term in text for term in claim_terms) and any(term in text for term in code_terms)

    def _compact_tool_payload(self, payload: dict[str, Any], limit: int = 40000) -> str:
        return _tool_present.compact_tool_payload(payload, limit=limit)

    def _summarize_tool_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _tool_present.summarize_tool_payload(payload)

    def write_event(self, payload: dict[str, Any]) -> None:
        self._record_run_event(payload)
        self.write_json_line(payload)

    def _record_run_event(self, payload: dict[str, Any]) -> None:
        run_id = getattr(self, "_active_run_id", "")
        if not run_id or not hasattr(self.runtime, "run_events"):
            return
        self.runtime.run_events.emit(run_id, payload)

    def write_json_line(self, payload: dict[str, Any]) -> None:
        if getattr(self, "_client_stream_closed", False):
            return
        try:
            self.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except (tornado.iostream.StreamClosedError, RuntimeError):
            self._client_stream_closed = True


class ConversationCompressHandler(ConversationMessagesHandler):
    """处理 POST /conversations/{id}/compress，手动触发上下文压缩。"""
    async def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")

        model = self.runtime.settings.get_default_model()
        messages = self._build_model_messages(
            conversation,
            workspace.to_public_dict(),
            record_memory_usage=False,
        )
        before_tokens = count_messages_tokens(messages)

        compressed, summary_meta = await compress_context(
            messages,
            model,
            self.runtime.settings,
            conversation=conversation,
            force=True,
        )

        if summary_meta:
            conv_meta = conversation.metadata or {}
            conv_meta.update(summary_meta)
            conversation.metadata = conv_meta
            self.runtime.conversations._save()

        after_tokens = count_messages_tokens(compressed)

        self.finish_json({
            "success": True,
            "data": {
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "compressed": bool(summary_meta),
                "context_limit": get_context_limit(model, self.runtime.settings),
                "summary_token_count": (summary_meta or {}).get("summary_token_count", 0),
            },
        })


class ConversationConfirmHandler(ApiHandler):
    """POST /conversations/{id}/confirm — 用户确认继续或取消任务"""

    def post(self, conversation_id: str) -> None:
        payload = self.parse_json_body()
        action = payload.get("action", "continue")  # 可选值："continue" 或 "cancel"
        _confirm_responses[conversation_id] = action
        event = _pending_confirms.get(conversation_id)
        if event:
            event.set()
            self.finish_json({"success": True, "action": action})
        else:
            self.finish_json({"success": False, "error": "无待确认任务"})
