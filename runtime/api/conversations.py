from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import tornado.web
import tornado.iostream

from .base import ApiHandler
from runtime import i18n
from runtime.capability_governance import ai_plugin_draft_workspace_guard_message
from runtime.agent_strategy.capability_router import (
    build_capability_catalog,
    format_capability_catalog_for_prompt,
)
from runtime.agent_strategy import classifiers as _clf
from runtime.agent_strategy import capability_preflight as _cap_preflight
from runtime.agent_strategy import confirmation_policy as _cp
from runtime.agent_strategy import conversation_task_context as _task_ctx
from runtime.agent_strategy import context_hygiene as _ctx_hygiene
from runtime.agent_strategy.document_contract_guard import document_contract_tool_guard_message
from runtime.agent_strategy.document_completion import min_text_output_check
from runtime.agent_strategy import prompts as _prp
from runtime.agent_strategy import plan_tracker as _pt
from runtime.agent_strategy import policy as _pol
from runtime.agent_strategy import task_contract as _tc
from runtime.agent_strategy.tool_execution_guard import (
    ToolExecutionGuardChecks,
    evaluate_tool_execution_guard,
)
from runtime.agent_strategy import tool_event_roles as _event_roles
from runtime.agent_strategy import tool_result_risks as _tool_risks
from runtime.model_providers import generate_chat_completion
from runtime.model_providers.client import stream_chat_completion
from runtime.assistant_modes import get_mode_config, normalize_mode
from runtime.context_manager import (
    compress_context,
    count_messages_tokens,
    get_context_limit,
    get_usable_limit,
)
from runtime.conversation_runner import ConversationRunExecutor
from runtime.conversation_interactions import (
    confirm_responses as _confirm_responses,
    pending_confirms as _pending_confirms,
    runtime_guidance as _runtime_guidance,
)
from runtime.prompt_context import build_system_prompt
from runtime.run_result_presenter import (
    synthesize_failure_answer,
    synthesize_final_answer,
    synthesize_partial_answer,
)
from runtime.task_runner import ToolContext
from runtime import tool_event_presentation as _tool_present


_active_stream_conversation_runs: dict[str, str] = {}
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


def _message_content_with_attachment_catalog(content: str, metadata: dict[str, Any]) -> str:
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
    catalog = (
        "\n\nUser-provided immutable conversation attachments:\n"
        + "\n".join(rows)
        + "\nUse attachment.extract_text for text, PDF, or Word attachments. "
        "Do not treat attachment storage as a project path."
    )
    return f"{content}{catalog}"


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
        mode = normalize_mode(payload.get("mode") or self.runtime.settings.get_assistant_mode())
        conversation = self.runtime.conversations.create(
            workspace_id, payload.get("title"), mode=mode,
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

        # Calculate current context token usage so the frontend can display it
        model = self.runtime.settings.get_default_model()
        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if workspace:
            mode_config = get_mode_config(getattr(conversation, "mode", None), self.get_lang())
            system_prompt = build_system_prompt(
                settings=self.runtime.settings,
                mode_config=mode_config,
                workspace_path=workspace.path,
                workspace_id=workspace.id,
            )
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt}
            ]
            for item in conversation.messages:
                metadata = getattr(item, "metadata", {}) or {}
                if metadata.get("guidance") and metadata.get("during_run"):
                    continue
                role = "assistant" if item.role == "assistant" else "user"
                messages.append({
                    "role": role,
                    "content": _message_content_with_attachment_catalog(item.content, metadata),
                })
            data["context_tokens"] = count_messages_tokens(messages)
            data["context_limit"] = get_context_limit(model, self.runtime.settings)
        else:
            data["context_tokens"] = 0
            data["context_limit"] = get_context_limit(model, self.runtime.settings)

        self.finish_json({"success": True, "data": data})

    def patch(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        mode = normalize_mode(payload.get("mode"))

        conversation = self.runtime.conversations.update_mode(conversation_id, mode)
        self.runtime.settings.update({"assistant_mode": mode})
        self.finish_json({
            "success": True,
            "data": conversation.to_public_dict(include_messages=True),
        })

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

        items = _runtime_guidance.setdefault(conversation_id, [])
        items.append(content)
        if len(items) > 10:
            del items[:-10]
        message = self.runtime.conversations.add_message(
            conversation_id,
            "user",
            content,
            {"guidance": True, "during_run": True},
        )
        self.finish_json({
            "success": True,
            "data": {
                "count": len(items),
                "message": message.to_public_dict(),
            },
        })


class ConversationMessagesHandler(ApiHandler):
    def _payload_mode(self, payload: dict[str, Any]) -> str | None:
        mode = str(payload.get("mode") or "").strip()
        return normalize_mode(mode) if mode else None

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

        payload_mode = self._payload_mode(payload)
        if payload_mode:
            self.runtime.settings.update({"assistant_mode": payload_mode})
            if payload_mode != conversation.mode:
                conversation = self.runtime.conversations.update_mode(conversation_id, payload_mode)

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
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        mode_config = get_mode_config(mode if mode is not None else getattr(conversation, "mode", None), self.get_lang())
        # Extract the latest user message for memory relevance scoring
        latest_user_message = ""
        for msg in reversed(getattr(conversation, "messages", [])):
            if getattr(msg, "role", "") == "user":
                latest_user_message = msg.content or ""
                break
        system_prompt = build_system_prompt(
            settings=self.runtime.settings,
            mode_config=mode_config,
            workspace_path=workspace["path"],
            workspace_id=str(workspace.get("id") or ""),
            user_message=latest_user_message,
            capability_context=self._capability_context_prompt(mode_config),
        )
        messages = [{"role": "system", "content": system_prompt}]
        for item in conversation.messages:
            metadata = getattr(item, "metadata", {}) or {}
            if metadata.get("guidance") and metadata.get("during_run"):
                continue
            role = "assistant" if item.role == "assistant" else "user"
            messages.append({
                "role": role,
                "content": _message_content_with_attachment_catalog(item.content, metadata),
            })
        messages, hygiene_report = _ctx_hygiene.sanitize_model_context(messages)
        self._last_context_hygiene_report = hygiene_report
        return messages

    def _capability_context_prompt(self, mode_config: dict[str, Any] | None = None) -> str:
        if not hasattr(self.runtime, "registry"):
            return ""
        specs = [
            spec
            for spec in self._capability_tool_specs(mode_config)
            if bool(spec.get("available"))
        ]
        return format_capability_catalog_for_prompt(build_capability_catalog(specs))

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
                or "external_state_change" in set(spec.get("effects") or [])
            )
        }
        capability_issues: list[dict[str, Any]] = []
        mcp_services = getattr(self.runtime, "mcp_services", None)
        if mcp_services is not None and hasattr(mcp_services, "capability_issues"):
            try:
                capability_issues = list(mcp_services.capability_issues())
            except Exception:
                capability_issues = []
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

    async def _auto_start_mcp_services_for_preflight(self, preflight: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(preflight, dict):
            return []
        target_capability_ids = [
            str(item).strip()
            for item in preflight.get("target_capability_ids") or []
            if str(item).strip().startswith("mcp.")
        ]
        if not target_capability_ids:
            return []
        advisories = preflight.get("advisories") if isinstance(preflight.get("advisories"), list) else []
        startable_targets = {
            str(item.get("capability_id") or "").strip()
            for item in advisories
            if isinstance(item, dict)
            and str(item.get("capability_id") or "").strip() in set(target_capability_ids)
            and str(item.get("recommended_action") or "").strip() == "start"
        }
        if not startable_targets:
            return []
        mcp_services = getattr(self.runtime, "mcp_services", None)
        if mcp_services is None or not hasattr(mcp_services, "start_capability_services"):
            return []
        try:
            return await mcp_services.start_capability_services(sorted(startable_targets))
        except Exception as exc:
            return [{
                "service_id": "",
                "capability_id": ",".join(sorted(startable_targets)),
                "status": "failed",
                "message": str(exc),
            }]

    def _capability_fallback_guard(self, tool_id: str) -> str:
        preflight = getattr(self, "_active_capability_preflight", None)
        if _cap_preflight.tool_allowed_by_preflight(preflight, tool_id):
            return ""
        targets = ", ".join(preflight.get("target_capability_ids") or []) if isinstance(preflight, dict) else ""
        if targets:
            return (
                f"Tool {tool_id} is outside the target capability boundary ({targets}). "
                "This boundary is enforced by the active task policy."
            )
        return (
            f"Tool {tool_id} is outside the current capability preflight boundary. "
            "Use an available target capability or explain why another safe strategy is necessary."
        )

    def _capability_preflight_failure_message(self, preflight: dict[str, Any]) -> str:
        messages = _cap_preflight.preflight_blocker_messages(preflight)
        lines = [
            "未完成：当前任务被运行时策略阻止，模型和工具尚未继续执行。",
        ]
        if messages:
            lines.append("")
            lines.append("阻断原因：")
            lines.extend(f"- {message}" for message in messages[:6])
        lines.extend([
            "",
            "这类阻断只应由明确的安全或权限策略触发；普通能力缺失会作为提示交给模型自主处理。",
        ])
        return "\n".join(lines)

    def _capability_boundary_prompt(self, preflight: dict[str, Any]) -> str:
        if not isinstance(preflight, dict):
            return ""
        advisory_messages = _cap_preflight.preflight_advisory_messages(preflight)
        preferred = preflight.get("preferred_tool_ids")
        allowed = preflight.get("allowed_tool_ids")
        enforce_allowed = isinstance(allowed, list) and bool(preflight.get("enforce_allowed_tools"))
        if not advisory_messages and not isinstance(preferred, list) and not enforce_allowed:
            return ""
        targets = ", ".join(preflight.get("target_capability_ids") or [])
        lines = [
            "Capability preflight advisory: use these runtime facts when choosing the task strategy.",
            (
                "Call only exact tool IDs that are visible in the current tool list. "
                "Do not invent generic discovery or management tools such as mcp.list_tools "
                "unless that exact tool ID is listed."
            ),
        ]
        if targets:
            lines.append(f"Target capability: {targets}.")
        if advisory_messages:
            lines.append("Current capability notes:")
            lines.extend(f"- {message}" for message in advisory_messages[:6])
        if isinstance(preferred, list) and preferred:
            lines.append("Preferred tools when they fit the goal: " + ", ".join(str(item) for item in preferred[:12]) + ".")
        if str(preflight.get("requires_external_state_capability") or "").lower() == "true":
            lines.append(
                "For external application or MCP state changes, prefer a small roundtrip check before a large script, "
                "and split complex actions into smaller verifiable tool calls when the provider has recent failures."
            )
        if enforce_allowed and isinstance(allowed, list):
            lines.append("This run has an enforced tool boundary: use only the tools still visible for state-changing work.")
        else:
            lines.append(
                "This is not a hard blocker. You may choose another safe strategy, ask the user, or explain the missing capability. "
                "Do not claim an external application state changed unless tool evidence confirms it."
            )
        return "\n".join(lines)

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
        if payload.get("access_scope"):
            self.runtime.settings.update({"access_scope": payload.get("access_scope")})

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
        _active_stream_conversation_runs[conversation_id] = "pending"

        payload_mode = self._payload_mode(payload)
        if payload_mode:
            self.runtime.settings.update({"assistant_mode": payload_mode})
            if payload_mode != conversation.mode:
                conversation = self.runtime.conversations.update_mode(conversation_id, payload_mode)

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

        model = payload.get("model") or self.runtime.settings.get_default_model()
        requested_mode = getattr(conversation, "mode", None)
        effective_mode = self._effective_mode(requested_mode, content, conversation)
        source_run_id = str(payload.get("source_run_id") or "").strip()
        parent_run_id = str(payload.get("parent_run_id") or source_run_id).strip()
        resume_from_checkpoint_id = str(payload.get("resume_from_checkpoint_id") or "").strip()
        prepared_run_id = str(payload.get("prepared_run_id") or "").strip()
        task_id = str(payload.get("task_id") or "").strip()
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

        task = asyncio.create_task(execute_run())
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
            if _active_stream_conversation_runs.get(conversation_id) in {run.id, "pending"}:
                _active_stream_conversation_runs.pop(conversation_id, None)

    def _normalize_planning_policy(self, payload: dict[str, Any]) -> str:
        policy = str(payload.get("planning_policy") or "").strip().lower()
        if policy in {"off", "auto", "always"}:
            return policy
        if any(key in payload for key in ("plan_mode", "plan_execution")):
            return self._normalize_plan_mode(payload)
        legacy = str(payload.get("execution_mode") or "").strip().lower()
        if legacy in {"conservative", "auto", "aggressive"}:
            return {
                "conservative": "off",
                "auto": "auto",
                "aggressive": "always",
            }[legacy]
        return self.runtime.settings.get_planning_policy()

    def _normalize_confirmation_policy(self, payload: dict[str, Any]) -> str:
        return _cp.normalize_confirmation_policy(
            payload.get("confirmation_policy"),
            self.runtime.settings.get_confirmation_policy(),
        )

    def _normalize_execution_mode(self, payload: dict[str, Any]) -> str:
        """Return the deprecated compatibility alias for planning_policy."""
        return {
            "off": "conservative",
            "auto": "auto",
            "always": "aggressive",
        }[self._normalize_planning_policy(payload)]

    def _plan_mode_for_execution_mode(self, execution_mode: str, payload: dict[str, Any]) -> str:
        """Compatibility helper for older callers."""
        return self._normalize_planning_policy({**payload, "execution_mode": execution_mode})

    def _normalize_plan_mode(self, payload: dict[str, Any]) -> str:
        mode = str(payload.get("plan_mode") or "").strip().lower()
        if mode in {"auto", "always", "off"}:
            return mode
        if payload.get("plan_execution") is True:
            return "always"
        if payload.get("plan_execution") is False and "plan_execution" in payload:
            return "off"
        return "auto"

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

    def _should_use_model_task_contract(
        self,
        content: str,
        fallback_intent: str,
        hard_no_write_lock: bool,
        conversation: Any | None = None,
    ) -> bool:
        text = str(content or "").strip()
        return _tc.should_use_model_task_contract(
            text,
            fallback_intent,
            hard_no_write_lock,
            has_recent_task_context=self._has_recent_task_context(conversation, text),
        )

    async def _decide_task_contract(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        workspace_path: str,
        user_content: str,
        fallback_contract: dict[str, Any],
        hard_no_write_lock: bool,
        expected_document_coverage: bool,
        expected_min_output_chars: int,
        previous_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            lang = self.get_lang()
        except Exception:
            lang = ""
        mode_config = get_mode_config(fallback_contract.get("assistant_mode"), lang)
        prompt = _tc.task_contract_prompt(
            workspace_path,
            fallback_contract,
            capability_context=self._capability_context_prompt(mode_config),
            previous_contract=previous_contract,
        )
        try:
            decision_messages: list[dict[str, Any]] = [
                {"role": "system", "content": prompt},
                *_tc.task_contract_context_messages(messages, user_content),
            ]
            answer, _metadata = await generate_chat_completion(
                settings=self.runtime.settings,
                model=model,
                messages=decision_messages,
                enable_thinking=False,
                reasoning_effort="low",
                tools=None,
            )
            parsed = _tc.extract_task_contract_json(answer)
            contract = _tc.merge_model_task_contract(
                parsed,
                fallback_contract,
                hard_no_write_lock=hard_no_write_lock,
                expected_document_coverage=expected_document_coverage,
                expected_min_output_chars=expected_min_output_chars,
            )
            return _tc.apply_task_continuity(
                contract,
                previous_contract=previous_contract,
                current_user_content=user_content,
            )
        except Exception as exc:
            contract = _tc.merge_model_task_contract(
                None,
                fallback_contract,
                hard_no_write_lock=hard_no_write_lock,
                expected_document_coverage=expected_document_coverage,
                expected_min_output_chars=expected_min_output_chars,
            )
            contract["source"] = "policy_fallback"
            contract["model_contract_error"] = str(exc)[:500]
            return _tc.apply_task_continuity(
                contract,
                previous_contract=previous_contract,
                current_user_content=user_content,
            )

    def _task_contract_prompt(self, contract: dict[str, Any]) -> str:
        conditions = ", ".join(contract.get("success_conditions") or [])
        goal = str(contract.get("goal") or "").strip() or "(not declared)"
        deliverables = json.dumps(contract.get("deliverables") or [], ensure_ascii=False)
        lang = self.get_lang()
        prompt = (
            i18n.t("contract.title", lang)
            + i18n.t("contract.workspace", lang, workspace_path=str(contract.get("workspace_path")))
            + i18n.t("contract.access", lang, access_scope=str(contract.get("access_scope")))
            + i18n.t("contract.planning_policy", lang, planning_policy=str(contract.get("planning_policy")))
            + i18n.t("contract.confirmation_policy", lang, confirmation_policy=str(contract.get("confirmation_policy")))
            + i18n.t("contract.intent", lang, intent=str(contract.get("intent")))
            + i18n.t("contract.goal", lang, goal=goal)
            + i18n.t("contract.deliverables", lang, deliverables=deliverables)
            + f"任务路由：{contract.get('routing_strategy')}（模型理解任务，系统校验能力契约与执行结果）\n"
            + i18n.t("contract.must_write", lang, requires_write=str(bool(contract.get("requires_write"))))
            + i18n.t(
                "contract.must_change_state",
                lang,
                requires_state_change=str(bool(contract.get("requires_state_change"))),
            )
            + i18n.t("contract.must_verify", lang, requires_verification=str(bool(contract.get("requires_verification"))))
            + i18n.t("contract.success", lang, conditions=conditions)
            + i18n.t("contract.write_rule", lang)
            + i18n.t("contract.verify_rule", lang)
            + i18n.t("contract.summary_rule", lang)
        )
        if contract.get("expected_document_coverage"):
            prompt += (
                "\n文档覆盖要求：本轮是全文/整文档输出任务。生成文件后必须验证输出规模，"
                "不能只验证文件存在；如果输出明显少于源文档，请明确说明未完整完成。\n"
            )
        try:
            min_chars = int(contract.get("expected_min_output_chars") or 0)
        except (TypeError, ValueError):
            min_chars = 0
        if min_chars > 0:
            prompt += (
                f"\nDocument size target: the user requested at least about {min_chars} characters. "
                "After exporting, compare the tool-reported content_chars/text_chars with this target. "
                "If the output is shorter, say it is not fully complete.\n"
            )
        return prompt

    def _task_contract_failures(
        self,
        contract: dict[str, Any],
        tool_events: list[dict[str, Any]],
        mode: str | None,
    ) -> list[str]:
        failures: list[str] = []
        workspace_path = str(contract.get("workspace_path") or "")
        deliverables = _event_roles.successful_deliverable_events(
            tool_events,
            task_contract=contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        verifications = _event_roles.sufficient_deliverable_verification_events(
            tool_events,
            task_contract=contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        if (
            (contract.get("requires_write") or contract.get("requires_state_change"))
            and not deliverables
        ):
            failures.append("missing_target_deliverable_success")
        if (
            contract.get("requires_verification")
            and deliverables
            and not verifications
        ):
            failures.append("missing_target_deliverable_verification")
        min_output_check = min_text_output_check(
            tool_events,
            expected_min_output_chars=contract.get("expected_min_output_chars") or 0,
            task_contract=contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        if min_output_check.get("required") and not min_output_check.get("ok"):
            failures.append(str(min_output_check.get("reason") or "document_output_too_short"))
        return failures

    async def _decide_plan_execution(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        workspace_path: str,
        mode: str | None,
        user_content: str,
    ) -> dict[str, Any]:
        lang = self.get_lang()
        prompt = i18n.t("plan_judge.prompt", lang, mode=mode or "document", workspace_path=workspace_path)
        try:
            decision_messages: list[dict[str, Any]] = []
            if messages and messages[0].get("role") == "system":
                decision_messages.append(messages[0])
            decision_messages.append({"role": "user", "content": user_content})
            decision_messages.append({"role": "system", "content": prompt})
            answer, _metadata = await generate_chat_completion(
                settings=self.runtime.settings,
                model=model,
                messages=decision_messages,
                enable_thinking=False,
                reasoning_effort="low",
                tools=None,
            )
            parsed = self._extract_plan_json(answer)
            if parsed and "use_plan" in parsed:
                return {
                    "mode": "auto",
                    "enabled": bool(parsed.get("use_plan")),
                    "reason": str(parsed.get("reason") or "")[:160],
                    "confidence": parsed.get("confidence"),
                    "source": "model",
                }
        except Exception:
            pass

        enabled = self._heuristic_plan_execution(user_content, mode)
        return {
            "mode": "auto",
            "enabled": enabled,
            "reason": self.t("plan_judge.reason_auto") if enabled else self.t("plan_judge.reason_direct"),
            "source": "heuristic",
        }

    def _heuristic_plan_execution(self, content: str, mode: str | None) -> bool:
        return _pol.heuristic_plan_execution(content, mode)

    async def _generate_execution_plan(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        workspace_path: str,
        mode: str | None,
        enable_thinking: bool,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        plan_messages = [*messages, {
            "role": "system",
            "content": self._planning_prompt(workspace_path, mode),
        }]
        plan_parts: list[str] = []
        async for event in stream_chat_completion(
            settings=self.runtime.settings,
            model=model,
            messages=plan_messages,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            tools=None,
        ):
            if event.get("error"):
                raise tornado.web.HTTPError(502, reason=event["error"])
            if event.get("message"):
                plan_parts.append(event["message"])
            if event.get("reasoning"):
                self.write_event({"event": "reasoning", "reasoning": event["reasoning"]})
                await self.flush()
            if event.get("heartbeat"):
                self.write_event({
                    "event": "heartbeat",
                    "message": event.get("message") or "模型仍在处理，请稍候",
                    "idle_seconds": event.get("idle_seconds"),
                    "phase": event.get("phase") or "model_stream",
                    "connection_alive": event.get("connection_alive", True),
                })
                await self.flush()
        raw_plan = "".join(plan_parts).strip()
        return self._normalize_execution_plan(raw_plan, mode)

    def _planning_prompt(self, workspace_path: str, mode: str | None) -> str:
        lang = self.get_lang()
        if mode == "coding":
            focus = i18n.t("planner.focus_coding", lang)
        elif mode == "paper":
            focus = i18n.t("planner.focus_paper", lang)
        else:
            focus = i18n.t("planner.focus_general", lang)
        return (
            i18n.t("planner.intro", lang, workspace_path=workspace_path)
            + focus + "\n"
            + i18n.t("planner.json_format", lang)
        )

    def _normalize_execution_plan(self, raw_plan: str, mode: str | None) -> dict[str, Any]:
        return _pt.normalize_execution_plan(raw_plan, mode)

    def _extract_plan_json(self, raw_plan: str) -> dict[str, Any] | None:
        return _pt.extract_plan_json(raw_plan)

    def _fallback_execution_plan(self, mode: str | None) -> dict[str, Any]:
        return _pt.fallback_execution_plan(mode)

    def _format_execution_plan_for_context(self, plan: dict[str, Any]) -> str:
        return _prp.format_execution_plan_for_context(plan)

    def _execute_plan_prompt(self, plan: dict[str, Any], mode: str | None) -> str:
        return _prp.execute_plan_prompt(plan, mode)

    def _execution_stage_sequence(
        self,
        mode: str | None,
        code_change_intent: bool,
        task_intent: str = "",
    ) -> list[str]:
        return _clf.execution_stage_sequence(mode, code_change_intent, task_intent)

    def _stage_round_limit(self, stage: str, mode: str | None, code_change_intent: bool) -> int:
        return _clf.stage_round_limit(stage, mode, code_change_intent)

    def _stage_tools(
        self,
        stage: str,
        tools: list[dict[str, Any]],
        tool_name_map: dict[str, str],
        mode: str | None,
        code_change_intent: bool,
    ) -> list[dict[str, Any]] | None:
        # 阶段不再收窄工具集。Planner / Explorer / Editor / Verifier
        # 只是角色提示和 UI 状态，真实安全边界由执行层决定。
        return tools

    def _explorer_tool_ids(self, mode: str | None) -> set[str]:
        return _clf.explorer_tool_ids(mode)

    def _stage_status_message(self, stage: str) -> str:
        return _prp.stage_status_message(stage)

    def _stage_prompt(
        self,
        stage: str,
        workspace_path: str,
        mode: str | None,
        code_change_intent: bool,
    ) -> str:
        return _prp.stage_prompt(stage, workspace_path, mode, code_change_intent)

    def _mark_next_plan_step_running(
        self,
        execution_plan: dict[str, Any] | None,
        tool_call: dict[str, Any],
    ) -> int | None:
        return _pt.mark_next_plan_step_running(execution_plan, tool_call)

    def _normalize_tool_id(self, value: Any) -> str:
        return _pt.normalize_tool_id(value)

    def _tool_matches_plan_step(self, tool_id: str, step: dict[str, Any]) -> bool:
        return _pt.tool_matches_plan_step(tool_id, step)

    def _finish_plan_step(
        self,
        execution_plan: dict[str, Any],
        step_index: int,
        tool_event: dict[str, Any],
    ) -> None:
        _pt.finish_plan_step(execution_plan, step_index, tool_event)

    def _complete_remaining_plan_steps(
        self,
        execution_plan: dict[str, Any],
        *,
        failed: bool,
        had_tool_events: bool = True,
    ) -> None:
        _pt.complete_remaining_plan_steps(execution_plan, failed=failed, had_tool_events=had_tool_events)

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
        for spec in self._capability_tool_specs(mode_config):
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
        note += " Prefer a small roundtrip test, restart the service, or choose another safe strategy before relying on this tool."
        return f"{description}\n\n{note}" if description else note

    def _messages_for_model_round(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        return _clf.messages_for_model_round(messages, tools)

    def _merge_tool_call_chunks(self, calls: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
        _clf.merge_tool_call_chunks(calls, chunks)

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
        ids = set(self._deliverable_verification_tool_ids())
        if mode in {"document", "paper"}:
            ids |= {
                "filesystem.scan_folder",
                "filesystem.read_file",
                "filesystem.read_text_preview",
                "document.extract_docx_outline",
                "document.extract_pdf_text_preview",
            }
        return ids

    def _post_deliverable_tool_ids(self) -> set[str]:
        return self._write_tool_ids() | self._deliverable_verification_tool_ids() | self._deliverable_read_tool_ids()

    def _execution_pressure_tool_ids(self, mode: str | None) -> set[str]:
        return (
            self._write_tool_ids()
            | self._explorer_tool_ids(mode)
            | {"git.status", "git.diff"}
        )

    def _editor_repair_tool_ids(self, mode: str | None, *, force_full_file_rewrite: bool = False) -> set[str]:
        if force_full_file_rewrite:
            return {
                "filesystem.read_file",
                "filesystem.read_text_preview",
                "filesystem.write_file",
            }
        return self._write_tool_ids() | self._explorer_tool_ids(mode)

    def _deliverable_read_tool_ids(self) -> set[str]:
        """允许在目标产物出现后读取必要证据或参考。"""
        return {"filesystem.read_file", "filesystem.read_text_preview", "filesystem.scan_folder"}

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

    def _is_deliverable_verification_tool(self, tool_id: str) -> bool:
        return tool_id in self._deliverable_verification_tool_ids()

    def _is_verification_tool(self, tool_id: str, mode: str | None) -> bool:
        return tool_id in self._verification_tool_ids(mode)

    def _is_post_deliverable_tool(self, tool_id: str) -> bool:
        return tool_id in self._post_deliverable_tool_ids()

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
        model_tool_name = ((tool_call.get("function") or {}).get("name") or self._model_tool_name(tool_id))
        event = {
            "status": "failure",
            "tool": tool_id,
            "name": self._tool_display_name(tool_id),
            "input": arguments,
            "task_id": "",
            "error": message,
            "output": {"type": "guard", "reason": reason, "message": message},
        }
        tool_payload = {
            "tool": tool_id,
            "input": arguments,
            "status": "failure",
            "output": {"reason": reason, "message": message},
            "error": message,
        }
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": model_tool_name,
            "content": self._compact_tool_payload(tool_payload),
        }, event

    def _progress_key(self, tool_events: list[dict[str, Any]], mode: str | None) -> str:
        return _clf.progress_key(tool_events, mode)

    def _round_has_only_non_progress(self, round_events: list[dict[str, Any]]) -> bool:
        return _clf.round_has_only_non_progress(round_events)

    def _consecutive_repeated_failure_count(self, tool_events: list[dict[str, Any]]) -> int:
        return _clf.consecutive_repeated_failure_count(tool_events)

    def _repeated_failure_action(
        self,
        tool_events: list[dict[str, Any]],
        *,
        strategy_change_intervened: bool,
    ) -> str:
        return _clf.repeated_failure_action(
            tool_events,
            strategy_change_intervened=strategy_change_intervened,
        )

    def _looks_like_dangling_action(self, content: str) -> bool:
        return _clf.looks_like_dangling_action(content)

    def _has_unresolved_tool_call_markup(self, content: str) -> bool:
        return _clf.has_unresolved_tool_call_markup(content)

    def _strip_native_tool_call_blocks(self, content: str) -> str:
        return _clf.strip_native_tool_call_blocks(content)

    def _dangling_action_prompt(
        self,
        workspace_path: str,
        unfinished_text: str,
        tool_events: list[dict[str, Any]],
        mode: str | None,
        *,
        allow_state_change: bool = True,
    ) -> str:
        return _prp.dangling_action_prompt(
            workspace_path,
            unfinished_text,
            tool_events,
            mode,
            allow_state_change=allow_state_change,
        )

    def _malformed_tool_call_prompt(self, workspace_path: str, unfinished_text: str) -> str:
        return _prp.malformed_tool_call_prompt(workspace_path, unfinished_text)

    def _answer_only_final_answer_error(
        self,
        content: str,
        tool_events: list[dict[str, Any]],
        task_contract: dict[str, Any] | None = None,
    ) -> str:
        if tool_events or not isinstance(task_contract, dict):
            return ""
        if str(task_contract.get("intent") or "") != "answer_only":
            return ""
        text = (content or "").strip()
        if not text or text == "模型没有返回内容。":
            return "model did not return a final answer"
        if _clf.strip_native_tool_call_blocks(text) != text:
            return "model returned unresolved tool call markup instead of a final answer"
        if self._looks_like_dangling_action(text):
            return "model stopped at a pending action instead of answering"
        return ""

    def _needs_synthesized_final_answer(
        self,
        content: str,
        tool_events: list[dict[str, Any]],
        task_contract: dict[str, Any] | None = None,
    ) -> bool:
        text = (content or "").strip()
        if not tool_events:
            return bool(self._answer_only_final_answer_error(content, tool_events, task_contract))
        if not text or text == "模型没有返回内容。":
            return True
        if _clf.strip_native_tool_call_blocks(text) != text:
            return True
        return self._looks_like_dangling_action(text)

    def _run_status_from_result(self, run_result: dict[str, Any]) -> str:
        status = str(run_result.get("status") or "")
        if status == "stopped":
            return "stopped"
        if status == "failure":
            return "failure"
        if status == "partial":
            return "partial"
        return "success"

    def _synthesize_failure_answer(
        self,
        workspace_path: str,
        tool_events: list[dict[str, Any]],
        run_result: dict[str, Any],
    ) -> str:
        return synthesize_failure_answer(
            workspace_path,
            tool_events,
            run_result,
            tool_event_failed=self._tool_event_failed,
            tool_event_failure_message=self._tool_event_failure_message,
            tool_event_display_path=self._tool_event_display_path,
        )

    def _synthesize_partial_answer(
        self,
        workspace_path: str,
        tool_events: list[dict[str, Any]],
        run_result: dict[str, Any],
    ) -> str:
        return synthesize_partial_answer(
            workspace_path,
            tool_events,
            run_result,
        )

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

    def _synthesize_final_answer(
        self,
        workspace_path: str,
        tool_events: list[dict[str, Any]],
        change_summary: dict[str, Any] | None,
        mode: str | None,
        task_contract: dict[str, Any] | None = None,
    ) -> str:
        return synthesize_final_answer(
            workspace_path,
            tool_events,
            change_summary,
            mode,
            task_contract,
            is_write_tool=self._is_write_tool,
            is_verification_tool=self._is_verification_tool,
            relative_workspace_path=self._relative_workspace_path,
            tool_event_failed=self._tool_event_failed,
            tool_event_failure_message=self._tool_event_failure_message,
        )

    def _progress_observer_prompt(
        self,
        workspace_path: str,
        current_stage: str,
        tool_events: list[dict[str, Any]],
        code_change_intent: bool,
        reason: str,
    ) -> str:
        return _prp.progress_observer_prompt(workspace_path, current_stage, tool_events, code_change_intent, reason)

    def _repeated_failure_strategy_prompt(
        self,
        workspace_path: str,
        current_stage: str,
        tool_events: list[dict[str, Any]],
    ) -> str:
        return _prp.repeated_failure_strategy_prompt(workspace_path, current_stage, tool_events)

    def _recon_budget_prompt(self, budget: int, workspace_path: str) -> str:
        return _prp.recon_budget_prompt(budget, workspace_path)

    def _write_only_stage_prompt(self, workspace_path: str) -> str:
        return _prp.write_only_stage_prompt(workspace_path)

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

    def _document_contract_tool_guard(self, tool_id: str, arguments: dict[str, Any]) -> str:
        contract = getattr(self, "_active_task_contract", None)
        return document_contract_tool_guard_message(
            tool_id,
            arguments,
            contract if isinstance(contract, dict) else None,
        )

    def _verification_runtime_tool_guard(self, tool_id: str, arguments: dict[str, Any]) -> str:
        if tool_id != "shell.run_command":
            return ""
        if not _clf.is_long_running_service_command(arguments):
            return ""
        contract = getattr(self, "_active_task_contract", None)
        if not isinstance(contract, dict) or not contract.get("requires_verification"):
            return ""
        tool_events = getattr(self, "_active_tool_events", [])
        current_stage = str(getattr(self, "_active_current_stage", "") or "")
        post_deliverable_mode = bool(
            getattr(self, "_active_post_deliverable_mode", False)
        )
        verification_context = (
            _clf.has_successful_write(tool_events if isinstance(tool_events, list) else [])
            or current_stage == "verifier"
            or post_deliverable_mode
        )
        if not verification_context:
            return ""
        command = _clf.shell_command_text(arguments)
        return (
            "检测到模型把长驻服务启动命令当作普通验证命令："
            f"{command}。这类命令通常不会自行退出，不能作为本轮目标产物完成后的自动验证。"
            "请改用可退出的语法检查、构建、测试、读取生成文件、git diff/status，"
            "或在最终总结中明确说明需要用户手动打开浏览器验证。"
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
                capability_fallback_message=self._capability_fallback_guard,
                ai_plugin_draft_workspace_message=self._ai_plugin_draft_workspace_guard,
                document_contract_message=self._document_contract_tool_guard,
                verification_runtime_message=self._verification_runtime_tool_guard,
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
        return _confirm_responses.pop(conversation_id, "cancel") == "continue"

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
        except KeyError:
            return self._skipped_tool_call(
                tool_call,
                tool_id,
                arguments,
                reason="unknown_tool",
                message=f"未知工具：{tool_id}。请改用当前工具列表中的规范工具 ID。",
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
            "confirmation_decision": confirmation_decision.to_dict(),
            "declared_effects": list(tool_spec.effects or []),
            "declared_roles": list(tool_spec.roles or []),
            "declared_verification_strength": tool_spec.verification_strength,
        }
        self.write_event({"event": "tool", **event})
        await self.flush()

        started_at = asyncio.get_running_loop().time()
        last_log_count = len(task.logs)
        last_progress_at = started_at
        last_heartbeat_at = started_at
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
            "output": output_preview,
            "declared_effects": list(tool_spec.effects or []),
            "declared_roles": list(tool_spec.roles or []),
            "declared_verification_strength": tool_spec.verification_strength,
        }
        tool_payload = _tool_risks.attach_tool_result_risks({
            "tool": tool_id,
            "input": arguments,
            "status": task.status,
            "output": task.output,
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

    def _is_runtime_guidance_message(self, message: Any) -> bool:
        return _task_ctx.is_runtime_guidance_message(message)

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

    def _read_range_summary_prompt(
        self,
        workspace_path: str,
        ranges: list[dict[str, Any]],
    ) -> str:
        lines = ["已读取文件片段（按行号范围记录）："]
        next_calls: list[str] = []
        for item in ranges:
            rel = self._relative_workspace_path(workspace_path, item.get("path")) or str(item.get("path") or "")
            start_line = item.get("start_line") or 1
            end_line = item.get("end_line") or "?"
            total = item.get("total_lines") or "?"
            lines.append(f"- {rel}: {start_line}-{end_line} / {total}")
            if item.get("truncated") and item.get("next_start_line"):
                next_calls.append(
                    f"- 如确实需要继续阅读 {rel}，请调用 filesystem.read_file "
                    f"并传入 start_line={item.get('next_start_line')}, end_line={item.get('next_end_line')}"
                )
        lines.append("不要重复读取完全相同的文件行号范围。")
        if next_calls:
            lines.append("长文件尚有后续内容；只有当当前任务确实依赖后续代码时，才继续读取下一段：")
            lines.extend(next_calls[:4])
        lines.append("如果现有片段已足以定位修改点，请直接调用写入工具；不要因为文件很长就停止执行。")
        return "\n".join(lines)

    def _previous_write_context(self, conversation: Any | None, current_content: str) -> bool:
        return _task_ctx.previous_write_context(conversation, current_content)

    def _has_recent_task_context(self, conversation: Any | None, current_content: str) -> bool:
        return _task_ctx.has_recent_task_context(conversation, current_content)

    def _previous_task_contract_context(
        self,
        conversation: Any | None,
        current_content: str,
    ) -> dict[str, Any] | None:
        return _task_ctx.previous_task_contract_context(conversation, current_content)

    def _previous_document_export_context(self, conversation: Any | None, current_content: str) -> bool:
        return _task_ctx.previous_document_export_context(conversation, current_content)

    def _previous_full_document_output_context(self, conversation: Any | None, current_content: str) -> bool:
        return _task_ctx.previous_full_document_output_context(conversation, current_content)

    def _expects_full_document_output(self, content: str, conversation: Any | None = None) -> bool:
        return _task_ctx.expects_full_document_output(content, conversation)

    def _expected_min_output_chars(self, content: str, conversation: Any | None = None) -> int:
        return _task_ctx.expected_min_output_chars(content, conversation)
    def _plan_has_pending_write_step(self, execution_plan: Any) -> bool:
        return _clf.plan_has_pending_write_step(execution_plan)

    def _classify_task_intent(
        self,
        content: str,
        mode: str | None,
        conversation: Any | None = None,
    ) -> str:
        return _task_ctx.classify_task_intent(content, mode, conversation)
    def _has_no_write_instruction(self, content: str) -> bool:
        return _clf.has_no_write_instruction(content)

    def _looks_like_read_only_request(self, content: str) -> bool:
        return _clf.looks_like_read_only_request(content)

    def _looks_like_document_export_request(self, content: str) -> bool:
        return _clf.looks_like_document_export_request(content)

    def _looks_like_full_document_output_request(self, content: str) -> bool:
        return _clf.looks_like_full_document_output_request(content)

    def _has_explicit_write_instruction(self, content: str) -> bool:
        return _clf.has_explicit_write_instruction(content)

    def _effective_mode(
        self,
        requested_mode: str | None,
        content: str,
        conversation: Any | None = None,
    ) -> str:
        return _task_ctx.effective_mode(requested_mode, content, conversation)

    def _looks_like_paper_task(self, content: str) -> bool:
        return _clf.looks_like_paper_task(content)

    def _looks_like_follow_up_execution(self, content: str) -> bool:
        return _clf.looks_like_follow_up_execution(content)

    def _looks_like_code_change_request(self, content: str) -> bool:
        return _clf.looks_like_code_change_request(content)

    def _looks_like_simple_code_change(self, content: str) -> bool:
        return _clf.looks_like_simple_code_change(content)

    def _code_change_intent(
        self,
        content: str,
        mode: str | None,
        conversation: Any | None = None,
    ) -> bool:
        return _task_ctx.code_change_intent(content, mode, conversation)

    def _has_successful_write(self, tool_events: list[dict[str, Any]]) -> bool:
        return _clf.has_successful_write(tool_events)

    def _has_successful_verification(self, tool_events: list[dict[str, Any]], mode: str | None) -> bool:
        return _clf.has_successful_verification(tool_events, mode)

    def _has_successful_target_deliverable(
        self,
        task_contract: dict[str, Any] | None,
        tool_events: list[dict[str, Any]],
        workspace_path: str,
        mode: str | None,
    ) -> bool:
        if not isinstance(task_contract, dict):
            return self._has_successful_write(tool_events)
        return bool(_event_roles.successful_deliverable_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        ))

    def _has_successful_target_verification(
        self,
        task_contract: dict[str, Any] | None,
        tool_events: list[dict[str, Any]],
        workspace_path: str,
        mode: str | None,
    ) -> bool:
        if not isinstance(task_contract, dict):
            return self._has_successful_verification(tool_events, mode)
        min_output_check = min_text_output_check(
            tool_events,
            expected_min_output_chars=task_contract.get("expected_min_output_chars") or 0,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        if min_output_check.get("required") and not min_output_check.get("ok"):
            return False
        return bool(_event_roles.sufficient_deliverable_verification_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        ))

    def _is_recoverable_write_failure(self, tool_id: str, event: dict[str, Any]) -> bool:
        return _clf.is_recoverable_write_failure(tool_id, event)

    def _write_repair_prompt(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        event: dict[str, Any],
        workspace_path: str,
        force_full_file_rewrite: bool = False,
    ) -> str:
        return _prp.write_repair_prompt(tool_id, arguments, event, workspace_path, force_full_file_rewrite)

    async def _auto_read_failed_target(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        workspace_path: str,
    ) -> str:
        """edit_file 失败后，自动读取目标文件的相关片段，返回文件内容片段供模型使用。"""
        from pathlib import Path
        target = arguments.get("path") or arguments.get("output_path") or ""
        if not target:
            return ""
        try:
            access_scope = self.runtime.settings.get_access_scope()
            guard = self.runtime.runner.path_guard.scoped(
                workspace_path,
                allow_all=access_scope == "full_local",
            )
            target_path = guard.resolve(target)
            if not target_path.exists() or not target_path.is_file():
                return ""
            text = target_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        
        # 尝试定位失败的 old_text 周边内容
        old_text = ""
        edits = arguments.get("edits")
        if isinstance(edits, list) and edits:
            old_text = (edits[0].get("old_text") or edits[0].get("old_string") or "")
        elif isinstance(arguments.get("old_text"), str):
            old_text = arguments["old_text"]
        elif isinstance(arguments.get("old_string"), str):
            old_text = arguments["old_string"]
        
        lines = text.splitlines()
        total_lines = len(lines)
        
        if old_text:
            # 模糊定位：找 old_text 首行在文件中的大致位置
            first_line = old_text.strip().splitlines()[0].strip() if old_text.strip() else ""
            center_line = 0
            if first_line:
                for i, line in enumerate(lines):
                    if first_line in line:
                        center_line = i
                        break
            # 取前后 30 行上下文，返回纯文本（不带行号），避免模型把行号写进 old_text
            start = max(0, center_line - 30)
            end = min(total_lines, center_line + 30)
            snippet = "\n".join(lines[start:end])
            return f"文件：{target_path.name}（第 {start+1}-{end} 行，共 {total_lines} 行，以下为不含行号的原始文本）\n{snippet}"
        
        # 没有 old_text，返回文件前 60 行纯文本
        end = min(total_lines, 60)
        snippet = "\n".join(lines[:end])
        suffix = f"\n... (剩余 {total_lines - end} 行省略)" if total_lines > end else ""
        return f"文件：{target_path.name}（共 {total_lines} 行，以下为不含行号的原始文本）\n{snippet}{suffix}"

    def _interrupt_execution_plan(self, execution_plan: dict[str, Any]) -> None:
        _pt.interrupt_execution_plan(execution_plan)

    def _runtime_intervention_prompt(
        self,
        workspace_path: str,
        current_stage: str,
        tool_events: list[dict[str, Any]],
        execution_plan: dict[str, Any] | None,
    ) -> str:
        return _prp.runtime_intervention_prompt(workspace_path, current_stage, tool_events, execution_plan)

    def _pop_runtime_guidance(self, conversation_id: str) -> tuple[str, str]:
        guidance_items = _runtime_guidance.pop(conversation_id, [])
        if not guidance_items:
            return "", ""
        guidance_text = "\n".join(f"- {item}" for item in guidance_items[-5:])
        return (
            "【运行中插话 / 干预】用户追加了新的信息或纠偏要求。"
            "请暂停沿用旧思路，重新审视当前任务后再继续：\n"
            f"{guidance_text}",
            guidance_text,
        )

    def _verifier_retry_prompt(self, mode: str | None, workspace_path: str) -> str:
        return _prp.verifier_retry_prompt(mode, workspace_path)

    def _tool_contract_correction_prompt(self, workspace_path: str, write_only: bool = False) -> str:
        return _prp.tool_contract_correction_prompt(workspace_path, write_only)

    def _read_only_task_prompt(self, workspace_path: str) -> str:
        return _prp.read_only_task_prompt(workspace_path)

    def _analysis_first_task_prompt(self, workspace_path: str) -> str:
        return _prp.analysis_first_task_prompt(workspace_path)

    def _post_deliverable_prompt(self, workspace_path: str) -> str:
        return _prp.post_deliverable_prompt(workspace_path)

    def _final_answer_prompt(self, workspace_path: str) -> str:
        return _prp.final_answer_prompt(workspace_path)

    def _user_requests_code_change(self, content: str, mode: str | None) -> bool:
        return _clf.user_requests_code_change(content, mode)

    def _max_rounds_message(self, max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
        return _prp.max_rounds_message(max_rounds, tool_events)

    def _max_rounds_after_write_message(self, max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
        paths: list[str] = []
        for event in tool_events:
            if not self._is_write_tool(str(event.get("tool") or "")) or event.get("status") != "success":
                continue
            event_input = event.get("input")
            if isinstance(event_input, dict):
                path = event_input.get("path")
                if path:
                    paths.append(str(path))
        unique_paths = list(dict.fromkeys(paths))
        lines = [
            f"本轮已有写入工具成功执行，但后续工具调用达到上限（{max_rounds} 轮），系统已停止继续执行。",
            "本轮变更是否完整请以上方工具记录和变更清单为准。",
        ]
        if unique_paths:
            lines.append("")
            lines.append("已成功写入的文件：")
            lines.extend(f"- {path}" for path in unique_paths[-8:])
        lines.append("")
        lines.append("建议：如结果不完整，请基于这些已写入文件继续下一轮，系统会避免重复搜索并优先收束。")
        return "\n".join(lines)

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
        if mode not in {"coding", "terminal"}:
            return None

        write_successes = [
            event for event in tool_events
            if self._is_write_tool(str(event.get("tool") or "")) and event.get("status") == "success"
        ]
        write_failures = [
            event for event in tool_events
            if self._is_write_tool(str(event.get("tool") or "")) and event.get("status") == "failure"
        ]
        invalid_verification_failures = [
            event for event in tool_events
            if _clf.is_invalid_verification_method_event(event)
        ]
        claims_change = self._assistant_claims_code_changed(assistant_content)
        if write_successes and invalid_verification_failures:
            failed_tools = [
                {
                    "tool": event.get("tool") or "",
                    "name": event.get("name") or event.get("tool") or "",
                    "path": ((event.get("input") or {}).get("path") if isinstance(event.get("input"), dict) else "") or "",
                    "error": event.get("error") or "",
                    "task_id": event.get("task_id") or "",
                }
                for event in invalid_verification_failures
            ]
            return {
                "reason": "invalid_verification_method",
                "message": "注意：本轮文件已写入，但模型尝试使用长驻服务命令作为验证方式。系统未把该命令视为有效自动验证，仍需运行可退出的检查命令或由用户手动打开页面确认。",
                "failed_tools": failed_tools[:8],
                "tool_event_count": len(tool_events),
            }
        if write_successes and write_failures:
            failed_tools = [
                {
                    "tool": event.get("tool") or "",
                    "name": event.get("name") or event.get("tool") or "",
                    "path": ((event.get("input") or {}).get("path") if isinstance(event.get("input"), dict) else "") or "",
                    "error": event.get("error") or "",
                    "task_id": event.get("task_id") or "",
                }
                for event in write_failures
            ]
            return {
                "reason": "partial_write_tool_failed",
                "message": "注意：本轮已有写入工具成功执行，但也存在写入工具失败。请以变更清单和工具调用记录为准，失败项可能仍需继续处理。",
                "failed_tools": failed_tools[:8],
                "tool_event_count": len(tool_events),
            }

        result_risks = run_result.get("risks") if isinstance(run_result, dict) else []
        if isinstance(result_risks, list) and "optional_write_not_verified" in result_risks:
            written_paths = run_result.get("observed_written_paths") if isinstance(run_result, dict) else []
            if not isinstance(written_paths, list):
                written_paths = []
            return {
                "reason": "optional_write_not_verified",
                "message": "注意：模型本轮主动写入了本地文件，但系统没有观察到后续运行、预览或读取验证。请把本轮结果视为已修改、未验证，而不是已确认修复。",
                "written_paths": [str(path) for path in written_paths[:8]],
                "tool_event_count": len(tool_events),
            }

        if write_successes:
            return None

        if not claims_change and not write_failures and not requires_code_write:
            return None

        failed_tools = [
            {
                "tool": event.get("tool") or "",
                "name": event.get("name") or event.get("tool") or "",
                "path": ((event.get("input") or {}).get("path") if isinstance(event.get("input"), dict) else "") or "",
                "error": event.get("error") or "",
                "task_id": event.get("task_id") or "",
            }
            for event in write_failures
        ]
        if max_rounds_exceeded:
            message = "注意：本轮工具调用达到上限，系统已停止继续执行并保存了诊断信息。实际文件是否变更请以工具调用和变更清单为准。"
            reason = "max_tool_rounds"
        elif contract_failed:
            message = "注意：本轮模型没有成功调用本地写入工具，系统已判定代码变更未执行。"
            reason = "tool_contract_failed"
        elif write_failures:
            message = "注意：本轮代码写入工具执行失败，实际文件可能没有变更。请展开上方工具调用查看失败原因。"
            reason = "write_tool_failed"
        elif tool_events:
            message = "注意：本轮没有成功执行任何代码写入工具，因此不能确认实际文件已经变更。"
            reason = "no_successful_write_tool"
        else:
            message = "注意：本轮没有任何本地工具调用记录，因此实际代码没有被修改。"
            reason = "no_tool_calls"

        return {
            "reason": reason,
            "message": message,
            "failed_tools": failed_tools[:8],
            "tool_event_count": len(tool_events),
        }

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
    """POST /conversations/{id}/compress — manually trigger context compression."""

    async def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")

        model = self.runtime.settings.get_default_model()
        messages = self._build_model_messages(conversation, workspace.to_public_dict())
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
        action = payload.get("action", "continue")  # "continue" or "cancel"
        _confirm_responses[conversation_id] = action
        event = _pending_confirms.get(conversation_id)
        if event:
            event.set()
            self.finish_json({"success": True, "action": action})
        else:
            self.finish_json({"success": False, "error": "无待确认任务"})
