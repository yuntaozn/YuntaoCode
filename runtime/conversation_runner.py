from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import tornado.web

from runtime.terminal_profile import get_terminal_config
from runtime.context_manager import compress_context, count_messages_tokens
from runtime.conversation_interactions import (
    paused_runs as _paused_runs,
)
from runtime.user_guidance import has_pending_user_guidance
from runtime.tool_call_loop import ToolCallLoop
from runtime.tool_execution_batch import ToolExecutionBatch, ToolExecutionState
from runtime.agent_strategy.capability_router import (
    build_task_route_evidence,
)
from runtime.agent_strategy.project_context import build_active_focus_snapshot
from runtime.agent_strategy.policy import resolve_profile
from runtime.agent_strategy.prompts import missing_tool_call_payload_prompt
from runtime.agent_strategy.profiles import profile_to_public_dict
from runtime.agent_strategy.convergence import (
    ESCALATE_NO_PROGRESS,
    REPORT_REPETITION,
    build_execution_convergence_decision,
)
from runtime.context_pack import (
    build_context_pack,
    format_context_pack_for_prompt,
)
from runtime.run_finalizer import RunFinalizationRequest, RunFinalizer
from runtime.run_execution_state import RunExecutionState
from runtime.task_state_control import TASK_STATE_TOOL_ID, TASK_STATE_TOOL_NAME, TaskStateControl, task_state_tool
from runtime.tool_discovery import DISCOVERY_TOOL_ID, DISCOVERY_TOOL_NAME, ToolDiscovery
from runtime.agent_strategy.plan_tracker import create_model_plan, apply_model_plan_updates
from runtime.run_completion import (
    build_completion_decision,
)
from runtime.run_recovery import format_recovery_context
from runtime.visual_context import build_visual_context_messages, apply_visual_context_delivery
from runtime.workspace_snapshot import build_workspace_snapshot
from runtime import i18n


class ConversationRunExecutor:
    def __init__(self, helper: Any, *, run_id: str, conversation_id: str) -> None:
        self._helper = helper
        self.runtime = helper.runtime
        self._active_run_id = run_id
        self._active_conversation_id = conversation_id

    def __getattr__(self, name: str) -> Any:
        class_attr = getattr(self._helper.__class__, name, None)
        if callable(class_attr):
            return class_attr.__get__(self, self.__class__)
        return getattr(self._helper, name)

    def write_event(self, payload: dict[str, Any]) -> None:
        self.runtime.run_events.emit(self._active_run_id, payload)

    def _set_active_tool_events(self, tool_events: list[dict[str, Any]]) -> None:
        self._active_tool_events = tool_events

    async def flush(self, include_footers: bool = False) -> None:
        return None

    def write_json_line(self, payload: dict[str, Any]) -> None:
        return None

    async def _wait_if_paused(self) -> None:
        run = self.runtime.runs.get(self._active_run_id)
        if not run or run.status != "paused":
            return
        pause_event = _paused_runs.setdefault(self._active_run_id, asyncio.Event())
        pause_event.clear()
        self.write_event({
            "event": "status",
            "status": "paused",
            "message": "Run paused; waiting for resume.",
        })
        await self.flush()
        while True:
            current = self.runtime.runs.get(self._active_run_id)
            if not current or current.status != "paused":
                return
            await pause_event.wait()
            pause_event.clear()

    async def execute(
        self,
        *,
        conversation_id: str,
        conversation: Any,
        workspace: Any,
        payload: dict[str, Any],
        content: str,
        image_data: str,
        attachments: list[Any],
        model: str,
        requested_mode: str | None,
        effective_mode: str,
        run: Any,
    ) -> None:
        self._active_workspace_id = str(conversation.workspace_id or "")
        messages = self._build_model_messages(
            conversation,
            workspace.to_public_dict(),
        )
        memory_context = getattr(self, "_last_memory_context", {}) or {}
        resume_checkpoint_id = str(getattr(run, "resume_from_checkpoint_id", "") or "")
        if resume_checkpoint_id:
            checkpoint = self.runtime.product_tasks.get_checkpoint(resume_checkpoint_id)
            snapshot = None
            if checkpoint and checkpoint.get("context_snapshot_id"):
                snapshot = self.runtime.product_tasks.get_context_snapshot(
                    str(checkpoint["context_snapshot_id"])
                )
            recovery_context = format_recovery_context(checkpoint, snapshot)
            if recovery_context:
                messages.append({"role": "system", "content": recovery_context})
        conversation_attachments = self.runtime.attachments.list_for_conversation(conversation_id)
        self._active_attachment_ids = tuple(record.id for record in conversation_attachments)
        image_attachments = [record for record in attachments if record.is_image]
        # 当前轮次的图片转为多模态输入，其他附件仍保留在消息目录中，
        # 并通过受控工具读取。
        if (image_data or image_attachments) and messages:
            last_msg = messages[-1]
            if last_msg.get("role") == "user":
                parts: list[dict[str, Any]] = []
                text_content = last_msg.get("content") or content
                if text_content:
                    parts.append({"type": "text", "text": text_content})
                if image_data:
                    parts.append({"type": "image_url", "image_url": {"url": image_data}})
                for record in image_attachments:
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": self.runtime.attachments.data_url(record.id)},
                    })
                last_msg["content"] = parts

        context_hygiene_report = getattr(self, "_last_context_hygiene_report", {}) or {}
        if context_hygiene_report.get("changed"):
            self.write_event({
                "event": "context_hygiene",
                "report": context_hygiene_report,
            })
            await self.flush()

        # --- 上下文压缩 ---
        self.write_event({"event": "status", "status": "compressing", "message": "正在检查上下文长度"})
        await self.flush()
        messages, summary_meta = await compress_context(
            messages, model, self.runtime.settings, conversation=conversation,
        )
        if summary_meta:
            conv_meta = conversation.metadata or {}
            conv_meta.update(summary_meta)
            conversation.metadata = conv_meta
            self.runtime.conversations._save()
            self.write_event({"event": "status", "status": "compressed",
                             "message": f"上下文已压缩（摘要 {summary_meta.get('summary_token_count', 0)} tokens）"})
            await self.flush()

        context_tokens = count_messages_tokens(messages)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_events: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {
            "mode": "local-model",
            "model": model,
            "run_id": run.id,
            "requested_mode": requested_mode,
            "effective_mode": effective_mode,
        }
        self._active_mode = effective_mode
        metadata["context_hygiene"] = context_hygiene_report
        metadata["memory_context"] = {
            "schema_version": str(memory_context.get("schema_version") or ""),
            "used_memory_ids": list(memory_context.get("used_memory_ids") or []),
            "selected_count": int(memory_context.get("selected_count") or 0),
            "workspace_id": str(memory_context.get("workspace_id") or ""),
        }
        _lang = i18n.get_lang(self._helper.request) if hasattr(self._helper, "request") else ""
        mode_config = get_terminal_config(_lang)
        workspace_snapshot = build_workspace_snapshot(workspace.path)
        metadata["workspace_snapshot"] = workspace_snapshot
        self.write_event({
            "event": "workspace_snapshot",
            "snapshot": workspace_snapshot,
        })
        tool_name_map = {DISCOVERY_TOOL_ID: DISCOVERY_TOOL_ID, DISCOVERY_TOOL_NAME: DISCOVERY_TOOL_ID}

        def load_tool_catalog() -> tuple[list[dict[str, Any]], dict[str, str]]:
            available_tools, names = self._build_model_tools(mode_config)
            available_tools.append(task_state_tool())
            names.update({TASK_STATE_TOOL_ID: TASK_STATE_TOOL_ID, TASK_STATE_TOOL_NAME: TASK_STATE_TOOL_ID})
            tool_name_map.update(names)
            return available_tools, names

        tool_discovery = ToolDiscovery(load_tool_catalog, emit=self.write_event)
        max_rounds = mode_config["max_rounds"]
        enable_thinking = bool(payload.get("enable_thinking", True))
        reasoning_effort = str(payload.get("reasoning_effort") or "medium")
        confirmation_policy = self._normalize_confirmation_policy(payload)
        execution_plan: dict[str, Any] | None = None
        change_baseline = await self._capture_git_status(workspace.path, mode_config)
        # 保持初始审计状态中性；任务理解与计划由主执行模型持续负责。
        task_intent = "undetermined"
        task_contract = self._build_task_contract(
            task_intent=task_intent,
            mode=effective_mode,
            planning_policy="off",
            confirmation_policy=confirmation_policy,
            workspace_path=workspace.path,
        )
        # 初始状态只记录用户原话，主执行模型按需声明语义；没有独立前置裁决。
        task_contract["source"] = "main_execution_pending"
        task_contract["goal"] = content
        task_lineage_candidates = self._task_lineage_candidates(conversation, content)
        active_focus = build_active_focus_snapshot(
            task_contract,
            task_lineage_candidates,
            workspace_snapshot=workspace_snapshot,
        )
        metadata["active_focus"] = active_focus
        capability_snapshot = self._build_capability_snapshot(mode_config)
        task_intent = str(task_contract.get("intent") or task_intent)
        code_change_intent = bool(task_contract.get("requires_write"))
        state_change_intent = bool(task_contract.get("requires_state_change"))
        agent_profile = resolve_profile(
            task_intent,
            effective_mode,
            code_change_intent=code_change_intent,
            state_change_intent=state_change_intent,
            first_action=str(task_contract.get("first_action") or ""),
        )
        self._active_task_contract = task_contract
        self._active_confirmation_policy = confirmation_policy
        capability_preflight = self._preflight_task_capabilities(task_contract, capability_snapshot)
        self._active_capability_snapshot = capability_snapshot
        self._active_capability_preflight = capability_preflight
        metadata["capability_snapshot"] = capability_snapshot
        metadata["capability_preflight"] = capability_preflight
        task_route_evidence = build_task_route_evidence(
            task_contract,
            capability_snapshot,
            capability_preflight,
        )
        metadata["task_route_evidence"] = task_route_evidence
        planning_context_pack = build_context_pack(
            phase="planning",
            user_content=content,
            workspace_snapshot=workspace_snapshot,
            task_contract=None,
            active_focus=None,
            task_candidates=task_lineage_candidates,
            memory_context=memory_context,
            capability_snapshot=capability_snapshot,
            capability_preflight=capability_preflight,
            context_hygiene_report=context_hygiene_report,
            task_id=str(getattr(run, "task_id", "") or ""),
        )
        metadata["context_pack"] = planning_context_pack
        metadata.setdefault("context_packs", []).append(planning_context_pack)
        self.write_event({
            "event": "context_pack",
            "pack": planning_context_pack,
        })
        planning_context_prompt = format_context_pack_for_prompt(planning_context_pack)
        if planning_context_prompt:
            messages.append({
                "role": "system",
                "content": planning_context_prompt,
            })
        self.write_event({"event": "task_contract", "contract": task_contract})
        self.write_event({
            "event": "capability_snapshot",
            "snapshot": capability_snapshot,
            "preflight": capability_preflight,
        })
        self.write_event({
            "event": "task_route_evidence",
            "evidence": task_route_evidence,
        })
        await self.flush()
        metadata["task_intent"] = task_intent
        metadata["agent_profile"] = profile_to_public_dict(agent_profile)
        metadata["code_change_intent"] = code_change_intent
        metadata["state_change_intent"] = state_change_intent
        metadata["confirmation_policy"] = confirmation_policy
        metadata["task_contract"] = task_contract
        metadata["task_id"] = str(getattr(run, "task_id", "") or "")
        metadata["run_id"] = str(getattr(run, "id", "") or "")
        metadata["source_run_id"] = str(getattr(run, "source_run_id", "") or "")
        metadata["resume_from_checkpoint_id"] = str(
            getattr(run, "resume_from_checkpoint_id", "") or ""
        )
        run_state = RunExecutionState.create(max_rounds)
        tool_execution_state = ToolExecutionState()
        tool_call_loop = ToolCallLoop(
            emit=self.write_event,
            flush=self.flush,
            guidance_pending=lambda: has_pending_user_guidance(conversation_id),
        )
        async def record_task_declaration(
            contract: dict[str, Any], plan: list[str] | None, declaration: dict[str, Any],
        ) -> None:
            nonlocal task_contract, task_intent, code_change_intent, state_change_intent
            nonlocal active_focus, capability_preflight, execution_plan
            proposed_plan = execution_plan
            if plan is not None:
                proposed_plan = create_model_plan(str(contract.get("goal") or ""), plan)
            proposed_plan = apply_model_plan_updates(
                proposed_plan, declaration.get("step_updates", []),
                getattr(self, "_active_tool_events", []),
            )
            understanding_changed = contract != task_contract
            task_contract = contract
            task_intent = str(contract.get("intent") or "answer_only")
            code_change_intent = bool(contract.get("requires_write"))
            state_change_intent = bool(contract.get("requires_state_change"))
            active_focus = build_active_focus_snapshot(
                contract, task_lineage_candidates, workspace_snapshot=workspace_snapshot,
            )
            capability_preflight = self._preflight_task_capabilities(contract, capability_snapshot)
            self._active_task_contract = contract
            self._active_capability_preflight = capability_preflight
            metadata.update({
                "task_contract": contract,
                "task_intent": task_intent,
                "code_change_intent": code_change_intent,
                "state_change_intent": state_change_intent,
                "active_focus": active_focus,
                "capability_preflight": capability_preflight,
            })
            self.write_event({"event": "task_contract", "contract": contract})
            if plan is not None or declaration.get("step_updates"):
                execution_plan = proposed_plan
                metadata["execution_plan"] = execution_plan
                self.write_event({"event": "plan", "plan": execution_plan})
            completion = declaration.get("completion")
            if completion is not None or (understanding_changed and metadata.get("completion_decisions")):
                assessment = {
                    "schema_version": "completion_self_assessment.v1",
                    "kind": "completion_self_assessment", "source": "model_declared",
                    **completion,
                } if completion is not None else None
                decision = build_completion_decision(
                    review_count=0, run_result=None, tool_calls=None,
                    reason="task_state_declaration", self_assessment=assessment,
                )
                metadata.setdefault("completion_decisions", []).append(decision)
                self.write_event({"event": "completion_decision", "decision": decision})
            await self.flush()

        task_control = TaskStateControl(task_contract, record_task_declaration)

        async def handle_runtime_control(*args: Any) -> dict[str, Any] | None:
            message = await tool_discovery.handle_call(*args)
            return message if message is not None else await task_control.handle_call(*args)

        tool_execution_batch = ToolExecutionBatch(self, control_handler=handle_runtime_control)

        try:
            while run_state.can_start_round():
                round_index = run_state.start_round()
                await self._wait_if_paused()
                round_start_event_count = len(tool_events)
                round_tools = tool_discovery.model_tools()
                round_enable_thinking = enable_thinking
                round_reasoning_effort = reasoning_effort
                guidance_prompt, guidance_text = self._pop_user_guidance(conversation_id)
                if guidance_prompt:
                    run_state.record_guidance()
                    messages.append({
                        "role": "user",
                        "content": guidance_text,
                    })
                    self.write_event({
                        "event": "guidance",
                        "message": guidance_text,
                    })
                    await self.flush()
                self.write_event({"event": "status", "status": "thinking", "message": "正在连接模型"})
                await self.flush()
                round_result = await tool_call_loop.run_model_round(
                    round_index=round_index,
                    settings=self.runtime.settings,
                    model=model,
                    messages=self._messages_for_model_round(messages, round_tools),
                    tools=round_tools,
                    enable_thinking=round_enable_thinking,
                    reasoning_effort=round_reasoning_effort,
                    consecutive_idle_timeouts=run_state.consecutive_idle_timeouts,
                    argument_observation_threshold=run_state.argument_observation_threshold,
                    large_argument_observations=run_state.large_argument_observations,
                )
                tool_call_chunks = round_result.tool_call_chunks
                if round_result.visual_context_delivery:
                    records = apply_visual_context_delivery(
                        metadata.get("visual_context_evidence", []), round_result.visual_context_delivery,
                    )
                    metadata["visual_context_evidence"] = records
                    self.write_event({
                        "event": "visual_context", "records": records,
                        "message": "已记录图片上下文的 Provider 传输状态；该状态不代表视觉审查通过。",
                    })
                round_content_parts = round_result.content_parts
                round_reasoning_parts = round_result.reasoning_parts
                round_finish_reason = round_result.finish_reason
                interrupted_by_guidance = round_result.interrupted_by_guidance
                run_state.consecutive_idle_timeouts = round_result.consecutive_idle_timeouts
                run_state.large_argument_observations = (
                    round_result.large_argument_observations
                )
                content_parts.extend(round_content_parts)
                reasoning_parts.extend(round_reasoning_parts)
                if round_result.request_budget is not None:
                    metadata["request_budget"] = round_result.request_budget
                    if round_result.request_budget.get("context_limit"):
                        metadata["effective_context_limit"] = round_result.request_budget.get(
                            "context_limit"
                        )
                if round_result.usage is not None:
                    metadata["usage"] = round_result.usage
                if round_result.finish_reasons:
                    metadata.setdefault("model_finish_reasons", []).extend(
                        round_result.finish_reasons
                    )
                if not round_result.model_error and not round_result.idle_timeout:
                    messages = run_state.transient_model_context.consume_from(messages)
                if round_result.model_error:
                    run_state.model_provider_error = round_result.model_error
                    break
                if round_result.idle_timeout:
                    continue
                late_guidance_prompt, late_guidance_text = self._pop_user_guidance(conversation_id)
                if late_guidance_prompt:
                    run_state.record_guidance()
                    if round_content_parts:
                        self._discard_parts(content_parts, round_content_parts)
                        self._discard_parts(reasoning_parts, round_reasoning_parts)
                        self.write_event({
                            "event": "message_replace",
                            "message": "".join(content_parts),
                            "clear_reasoning": interrupted_by_guidance,
                        })
                        await self.flush()
                    messages.append({
                        "role": "user",
                        "content": late_guidance_text,
                    })
                    self.write_event({
                        "event": "guidance",
                        "message": late_guidance_text,
                    })
                    await self.flush()
                    continue

                tool_calls = self._complete_tool_calls(tool_call_chunks, round_index)
                if round_result.text_tool_call_recovered:
                    self._discard_parts(content_parts, round_content_parts)
                    self._discard_parts(reasoning_parts, round_reasoning_parts)
                    round_content_parts = []
                    round_reasoning_parts = []
                    self.write_event({
                        "event": "message_replace", "message": "".join(content_parts),
                        "clear_reasoning": True, "discard_reasoning": True,
                    })
                    await self.flush()
                if not tool_calls and round_result.protocol_error:
                    metadata.setdefault("model_protocol_errors", []).append({
                        "code": round_result.protocol_error,
                        "round": round_index,
                        "finish_reason": round_finish_reason,
                        "tool_call_chunk_count": len(tool_call_chunks),
                    })
                    self._discard_parts(content_parts, round_content_parts)
                    self._discard_parts(reasoning_parts, round_reasoning_parts)
                    self.write_event({
                        "event": "message_replace",
                        "message": "".join(content_parts),
                        "clear_reasoning": True,
                    })
                    self.write_event({
                        "event": "error", "error": round_result.protocol_error,
                        "protocol_error": round_result.protocol_error, "terminal": False,
                    })
                    protocol_message = {
                        "role": "system",
                        "content": missing_tool_call_payload_prompt(round_result.protocol_error),
                    }
                    messages.append(protocol_message)
                    run_state.transient_model_context.add(protocol_message)
                    await self.flush()
                    continue
                if not tool_calls:
                    break

                if round_content_parts:
                    self._discard_parts(content_parts, round_content_parts)
                    self.write_event({
                        "event": "message_replace",
                        "message": "".join(content_parts),
                    })
                    await self.flush()

                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": tool_calls,
                })
                batch_result = await tool_execution_batch.execute(
                    tool_calls=tool_calls,
                    tool_name_map=tool_name_map,
                    workspace_path=workspace.path,
                    finish_reason=round_finish_reason,
                    previous_tool_events=tool_events,
                    state=tool_execution_state,
                )
                tool_execution_state = batch_result.state
                tool_events.extend(batch_result.tool_events)
                messages.extend(batch_result.model_messages)
                run_state.transient_model_context.add_from(batch_result.model_messages)
                round_events = tool_events[round_start_event_count:]
                visual_context = build_visual_context_messages(
                    round_events,
                    model_config=self.runtime.settings.get_model_config(model),
                    workspace_path=workspace.path,
                    data_dir=getattr(self.runtime.settings, "data_dir", None),
                    tool_task_lookup=getattr(getattr(self.runtime, "tool_tasks", None), "get", None),
                )
                if visual_context.records:
                    messages.extend(visual_context.messages)
                    audit_records = [
                        {
                            key: value
                            for key, value in record.items()
                            if key != "data_url"
                        }
                        for record in visual_context.records
                    ]
                    metadata.setdefault("visual_context_evidence", []).extend(audit_records)
                    self.write_event({
                        "event": "visual_context",
                        "records": audit_records,
                        "message": "已准备视觉证据及图片附件状态，等待下一轮模型请求。",
                    })
                    await self.flush()
                if round_events:
                    execution_context_pack = build_context_pack(
                        phase="execution",
                        user_content=content,
                        task_contract=task_contract,
                        active_focus=active_focus,
                        capability_snapshot=capability_snapshot,
                        capability_preflight=capability_preflight,
                        tool_events=tool_events,
                        execution_plan=execution_plan,
                        round_index=round_index,
                        context_hygiene_report=context_hygiene_report,
                        task_id=str(getattr(run, "task_id", "") or ""),
                    )
                    metadata["context_pack"] = execution_context_pack
                    metadata.setdefault("context_packs", []).append(execution_context_pack)
                    self.write_event({
                        "event": "context_pack",
                        "pack": execution_context_pack,
                    })
                    await self.flush()
                convergence_decision = build_execution_convergence_decision(tool_events)
                repeated_failure_count = convergence_decision.consecutive_failure_count
                failure_route_attempt_count = convergence_decision.route_attempt_count
                repeated_failure_action = convergence_decision.action
                if repeated_failure_action in {
                    REPORT_REPETITION,
                    ESCALATE_NO_PROGRESS,
                }:
                    repeated_tool = str(tool_events[-1].get("tool") or "unknown tool")
                    escalated = repeated_failure_action == ESCALATE_NO_PROGRESS
                    metadata["execution_convergence"] = convergence_decision.to_dict()
                    if escalated:
                        metadata["execution_convergence_escalated"] = True
                    self.write_event({
                        "event": "status",
                        "status": (
                            "repeated_route_budget_observed"
                            if escalated
                            else "repeated_route_observed"
                        ),
                        "message": (
                            f"{repeated_tool} 在当前无进展窗口内已出现 {failure_route_attempt_count} 次同一路线失败，"
                            + (
                                "已记录预算事实。"
                                if escalated
                                else "已记录重复失败事实。"
                            )
                        ),
                        "tool": repeated_tool,
                        "failure_count": repeated_failure_count,
                        "route_attempt_count": failure_route_attempt_count,
                        "execution_convergence": convergence_decision.to_dict(),
                    })
                    await self.flush()
            else:
                run_state.max_rounds_exceeded = True
                self.write_event({
                    "event": "status",
                    "status": "max_tool_rounds",
                    "message": "已达到当前执行轮次预算，正在保存诊断信息",
                })
                await self.flush()
        except tornado.web.HTTPError as exc:
            run_state.model_provider_error = str(exc.reason or exc)
            metadata["model_provider_error"] = run_state.model_provider_error
            self.write_event({
                "event": "error",
                "error": run_state.model_provider_error,
                "terminal": False,
            })
            await self.flush()

        finalization_outcome = await RunFinalizer(self).finalize(
            RunFinalizationRequest(
                conversation_id=conversation_id,
                conversation=conversation,
                workspace=workspace,
                model=model,
                mode_config=mode_config,
                effective_mode=effective_mode,
                user_content=content,
                metadata=metadata,
                content_parts=content_parts,
                reasoning_parts=reasoning_parts,
                tool_events=tool_events,
                task_contract=task_contract,
                workspace_snapshot=workspace_snapshot,
                active_focus=active_focus,
                capability_snapshot=capability_snapshot,
                capability_preflight=capability_preflight,
                context_hygiene_report=context_hygiene_report,
                run=run,
                execution_plan=execution_plan,
                change_baseline=change_baseline,
                execution_state=run_state,
                requires_code_write=code_change_intent,
                recon_tool_count=tool_execution_state.recon_tool_count,
                write_repair_mode=tool_execution_state.write_repair_mode,
                context_tokens=context_tokens,
            )
        )
        # 异步提取记忆（不阻塞响应）
        if (
            self.runtime.settings.is_memory_auto_extract_enabled()
            and not finalization_outcome.max_rounds_exceeded
        ):
            asyncio.create_task(self._extract_and_store_memories(
                messages,
                model,
                conversation_id,
                workspace_id=str(conversation.workspace_id or ""),
            ))

    async def _extract_and_store_memories(
        self,
        messages: list[dict[str, Any]],
        model: str,
        conversation_id: str,
        workspace_id: str = "",
    ) -> None:
        """异步提取记忆，在对话响应发送后运行。"""
        try:
            from runtime.memory_extractor import extract_and_store_memories

            await extract_and_store_memories(
                store=self.runtime.settings.memory_store,
                messages=messages,
                model=model,
                settings=self.runtime.settings,
                conversation_id=conversation_id,
                workspace_id=workspace_id,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Background memory extraction failed")

