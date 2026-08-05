from __future__ import annotations

import asyncio
import json
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
from runtime.agent_strategy.capability_grounding import ground_task_contract_with_capabilities
from runtime.agent_strategy.capability_router import (
    build_task_route_evidence,
    format_task_route_evidence_for_prompt,
)
from runtime.agent_strategy import task_contract as _tc
from runtime.agent_strategy import tool_event_roles as _event_roles
from runtime.agent_strategy.project_context import build_active_focus_snapshot
from runtime.agent_strategy.policy import resolve_plan_execution, resolve_profile
from runtime.agent_strategy.profiles import profile_to_public_dict
from runtime.agent_strategy.convergence import (
    ESCALATE_NO_PROGRESS,
    REPORT_REPETITION,
    build_execution_convergence_decision,
)
from runtime.agent_strategy.run_finalization import (
    COMPLETION_REVIEW,
    build_completion_review_gate,
)
from runtime.context_pack import (
    build_context_pack,
    format_context_pack_for_prompt,
    is_context_pack_prompt_for_phase,
)
from runtime.run_finalizer import RunFinalizationRequest, RunFinalizer
from runtime.run_execution_state import RunExecutionState
from runtime.run_completion import (
    build_completion_decision,
    build_completion_evidence_pack,
    extract_completion_self_assessment,
)
from runtime.run_result import build_run_result
from runtime.run_recovery import format_recovery_context
from runtime.visual_context import build_visual_context_messages
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

    def _task_requires_target_deliverable(self, task_contract: dict[str, Any] | None) -> bool:
        return bool(
            isinstance(task_contract, dict)
            and (
                task_contract.get("requires_write")
                or task_contract.get("requires_state_change")
            )
        )

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
        tools, tool_name_map = self._build_model_tools(mode_config)
        max_rounds = mode_config["max_rounds"]
        enable_thinking = bool(payload.get("enable_thinking", True))
        reasoning_effort = str(payload.get("reasoning_effort") or "medium")
        planning_policy = self._normalize_planning_policy(payload)
        confirmation_policy = self._normalize_confirmation_policy(payload)
        plan_execution = False
        plan_decision: dict[str, Any] = {
            "mode": planning_policy,
            "enabled": False,
            "reason": "",
            "source": "user",
        }
        execution_plan: dict[str, Any] | None = None
        change_baseline = await self._capture_git_status(workspace.path, mode_config)
        # 保持初始契约中性。语义任务分类由模型侧任务契约负责，
        # 包括文档覆盖范围和大小判断。
        task_intent = "answer_only"
        task_contract = self._build_task_contract(
            task_intent=task_intent,
            mode=effective_mode,
            planning_policy=planning_policy,
            confirmation_policy=confirmation_policy,
            workspace_path=workspace.path,
        )
        available_task_lineage_candidates = self._task_lineage_candidates(conversation, content)
        task_lineage_candidates: list[dict[str, Any]] = []
        task_lineage_availability = self._task_lineage_availability(
            available_task_lineage_candidates
        )
        context_pack = build_context_pack(
            phase="task_contract",
            user_content=content,
            workspace_snapshot=workspace_snapshot,
            previous_contract=None,
            task_lineage_availability=task_lineage_availability,
            task_candidates=task_lineage_candidates,
            memory_context=memory_context,
            context_hygiene_report=context_hygiene_report,
            task_id=str(getattr(run, "task_id", "") or ""),
        )
        context_pack_prompt = format_context_pack_for_prompt(context_pack)
        metadata["context_pack"] = context_pack
        metadata.setdefault("context_packs", []).append(context_pack)
        metadata["task_lineage_availability"] = task_lineage_availability
        self.write_event({
            "event": "context_pack",
            "pack": context_pack,
        })
        if self._should_use_model_task_contract(
            content,
            task_intent,
            conversation,
        ):
            self.write_event({
                "event": "status",
                "status": "task_contract_deciding",
                "message": "正在判断任务契约",
            })
            await self.flush()
            task_contract = await self._decide_task_contract(
                model=model,
                messages=messages,
                workspace_path=workspace.path,
                user_content=content,
                fallback_contract=task_contract,
                previous_contract=None,
                workspace_context=context_pack_prompt,
            )
            if (
                available_task_lineage_candidates
                and _tc.contract_requests_task_lineage(task_contract)
            ):
                task_lineage_candidates = available_task_lineage_candidates
                lineage_context_pack = build_context_pack(
                    phase="task_contract",
                    user_content=content,
                    workspace_snapshot=workspace_snapshot,
                    previous_contract=None,
                    task_lineage_availability=task_lineage_availability,
                    task_candidates=task_lineage_candidates,
                    memory_context=memory_context,
                    context_hygiene_report=context_hygiene_report,
                    task_id=str(getattr(run, "task_id", "") or ""),
                )
                lineage_context_pack_prompt = format_context_pack_for_prompt(
                    lineage_context_pack
                )
                metadata["context_pack"] = lineage_context_pack
                metadata.setdefault("context_packs", []).append(lineage_context_pack)
                metadata["task_lineage_candidates"] = task_lineage_candidates
                metadata["task_lineage_exposure"] = {
                    "source": "model_task_contract",
                    "reason": str(
                        task_contract.get("task_lineage_request_reason") or ""
                    ),
                    "candidate_count": len(task_lineage_candidates),
                }
                self.write_event({
                    "event": "status",
                    "status": "task_lineage_context_requested",
                    "message": "模型请求查看历史任务候选，正在展开候选事实",
                })
                self.write_event({
                    "event": "context_pack",
                    "pack": lineage_context_pack,
                    "reason": "model_requested_task_lineage",
                })
                await self.flush()
                task_contract = await self._decide_task_contract(
                    model=model,
                    messages=messages,
                    workspace_path=workspace.path,
                    user_content=content,
                    fallback_contract=task_contract,
                    previous_contract=None,
                    workspace_context=lineage_context_pack_prompt,
                )
            referenced_contract = self._referenced_task_candidate_contract(
                task_lineage_candidates,
                task_contract.get("referenced_task_candidate_id"),
            )
            continuity_contract = referenced_contract
            if (
                continuity_contract
                and _tc.should_apply_task_continuity(
                    task_contract,
                    current_user_content=content,
                )
            ):
                task_contract = _tc.apply_task_continuity(
                    task_contract,
                    previous_contract=continuity_contract,
                    current_user_content=content,
                )
                metadata["applied_task_continuity"] = True
                if referenced_contract:
                    metadata["applied_task_candidate_id"] = str(
                        task_contract.get("referenced_task_candidate_id") or ""
                    )
        active_focus = build_active_focus_snapshot(
            task_contract,
            task_lineage_candidates,
            workspace_snapshot=workspace_snapshot,
        )
        metadata["active_focus"] = active_focus
        capability_snapshot = self._build_capability_snapshot(mode_config)
        if ground_task_contract_with_capabilities(
            task_contract,
            capability_snapshot,
            user_content=content,
        ):
            task_contract["success_conditions"] = _tc.success_conditions_for_contract(task_contract)
            metadata["capability_grounded_task_contract"] = True
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
        mcp_auto_start_results = await self._auto_start_mcp_services_for_preflight(capability_preflight)
        if mcp_auto_start_results:
            metadata["mcp_auto_start"] = mcp_auto_start_results
            successful_auto_starts = [
                item for item in mcp_auto_start_results
                if isinstance(item, dict) and item.get("status") == "started"
            ]
            message = (
                "MCP service auto-start completed; refreshing capability snapshot"
                if successful_auto_starts
                else "MCP service auto-start attempted but did not make the capability available"
            )
            self.write_event({
                "event": "status",
                "status": "mcp_auto_start",
                "message": message,
            })
            capability_snapshot = self._build_capability_snapshot(mode_config)
            if ground_task_contract_with_capabilities(
                task_contract,
                capability_snapshot,
                user_content=content,
            ):
                task_contract["success_conditions"] = _tc.success_conditions_for_contract(task_contract)
                metadata["capability_grounded_task_contract"] = True
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
            task_contract=task_contract,
            active_focus=active_focus,
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
        messages.append({
            "role": "system",
            "content": self._task_contract_prompt(task_contract),
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
        capability_prompt = self._capability_boundary_prompt(capability_preflight)
        if capability_prompt:
            messages.append({"role": "system", "content": capability_prompt})
        route_prompt = format_task_route_evidence_for_prompt(task_route_evidence)
        if route_prompt:
            messages.append({"role": "system", "content": route_prompt})
        metadata["task_intent"] = task_intent
        metadata["agent_profile"] = profile_to_public_dict(agent_profile)
        metadata["code_change_intent"] = code_change_intent
        metadata["state_change_intent"] = state_change_intent
        metadata["planning_policy"] = planning_policy
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
        tool_execution_batch = ToolExecutionBatch(self)

        try:
            async def rejudge_guidance_contract(guidance_text: str) -> None:
                nonlocal task_contract
                nonlocal task_intent
                nonlocal code_change_intent
                nonlocal state_change_intent
                nonlocal active_focus
                nonlocal capability_snapshot
                nonlocal capability_preflight

                task_contract = await self._decide_task_contract(
                    model=model,
                    messages=messages,
                    workspace_path=workspace.path,
                    user_content=guidance_text,
                    fallback_contract=task_contract,
                    previous_contract=task_contract,
                    workspace_context="",
                )
                if ground_task_contract_with_capabilities(
                    task_contract,
                    capability_snapshot,
                    user_content=guidance_text,
                ):
                    task_contract["success_conditions"] = _tc.success_conditions_for_contract(
                        task_contract
                    )
                task_intent = str(task_contract.get("intent") or task_intent)
                code_change_intent = bool(task_contract.get("requires_write"))
                state_change_intent = bool(task_contract.get("requires_state_change"))
                active_focus = build_active_focus_snapshot(
                    task_contract,
                    task_lineage_candidates,
                    workspace_snapshot=workspace_snapshot,
                )
                capability_preflight = self._preflight_task_capabilities(
                    task_contract,
                    capability_snapshot,
                )
                self._active_task_contract = task_contract
                self._active_capability_preflight = capability_preflight
                metadata["task_contract"] = task_contract
                metadata["active_focus"] = active_focus
                metadata["capability_preflight"] = capability_preflight
                self.write_event({"event": "task_contract", "contract": task_contract})
                messages.append({
                    "role": "system",
                    "content": self._task_contract_prompt(task_contract),
                })
                await self.flush()

            resolved_plan = resolve_plan_execution(task_contract, planning_policy)
            plan_execution = bool(resolved_plan.enabled)
            plan_decision = resolved_plan.to_public_dict(planning_policy)
            metadata["plan_decision"] = plan_decision
            self.write_event({"event": "plan_decision", "decision": plan_decision})
            await self.flush()

            if plan_execution:
                self.write_event({"event": "status", "status": "planning", "message": "正在生成计划"})
                await self.flush()
                execution_plan = await self._generate_execution_plan(
                    model=model,
                    messages=messages,
                    workspace_path=workspace.path,
                    mode=effective_mode,
                    enable_thinking=enable_thinking,
                    reasoning_effort=reasoning_effort,
                )
                metadata["execution_plan"] = execution_plan
                self.write_event({"event": "plan", "plan": execution_plan})
                await self.flush()
                messages.append({
                    "role": "assistant",
                    "content": self._format_execution_plan_for_context(execution_plan),
                })
                messages.append({
                    "role": "system",
                    "content": self._execute_plan_prompt(execution_plan, effective_mode),
                })
                metadata["plan_execution_strategy"] = "audit_then_execute"

            while run_state.can_start_round():
                round_index = run_state.start_round()
                await self._wait_if_paused()
                round_start_event_count = len(tool_events)
                round_tools = tools
                round_enable_thinking = enable_thinking
                round_reasoning_effort = reasoning_effort
                guidance_prompt, guidance_text = self._pop_user_guidance(conversation_id)
                if guidance_prompt:
                    await rejudge_guidance_contract(guidance_text)
                    run_state.record_guidance()
                    if execution_plan:
                        self._interrupt_execution_plan(execution_plan)
                        self.write_event({"event": "plan", "plan": execution_plan})
                        await self.flush()
                    messages.append({
                        "role": "system",
                        "content": self._guidance_reorientation_prompt(
                            workspace.path,
                            tool_events,
                            execution_plan,
                        ),
                    })
                    messages.append({
                        "role": "user",
                        "content": guidance_prompt,
                    })
                    self.write_event({
                        "event": "guidance",
                        "message": guidance_text,
                    })
                    await self.flush()
                self.write_event({"event": "status", "status": "thinking", "message": "正在连接模型"})
                await self.flush()
                round_result = await tool_call_loop.run_model_round(
                    settings=self.runtime.settings,
                    model=model,
                    messages=self._messages_for_model_round(messages, round_tools),
                    tools=round_tools,
                    enable_thinking=round_enable_thinking,
                    reasoning_effort=round_reasoning_effort,
                    has_runtime_facts=bool(tool_events),
                    consecutive_idle_timeouts=run_state.consecutive_idle_timeouts,
                    argument_observation_threshold=run_state.argument_observation_threshold,
                    large_argument_observations=run_state.large_argument_observations,
                )
                tool_call_chunks = round_result.tool_call_chunks
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
                    if round_result.fatal:
                        return
                    break
                if round_result.idle_timeout:
                    if round_result.fatal:
                        return
                    continue
                late_guidance_prompt, late_guidance_text = self._pop_user_guidance(conversation_id)
                if late_guidance_prompt:
                    await rejudge_guidance_contract(late_guidance_text)
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
                    if execution_plan:
                        self._interrupt_execution_plan(execution_plan)
                        self.write_event({"event": "plan", "plan": execution_plan})
                        await self.flush()
                    messages.append({
                        "role": "system",
                        "content": self._guidance_reorientation_prompt(
                            workspace.path,
                            tool_events,
                            execution_plan,
                        ),
                    })
                    messages.append({
                        "role": "user",
                        "content": late_guidance_prompt,
                    })
                    self.write_event({
                        "event": "guidance",
                        "message": late_guidance_text,
                    })
                    await self.flush()
                    continue

                tool_calls = self._complete_tool_calls(tool_call_chunks, round_index)
                if not tool_calls:
                    native_tool_calls = self._extract_native_tool_calls(
                        "".join(round_content_parts) + "\n" + "".join(round_reasoning_parts),
                        round_index,
                    )
                    if native_tool_calls:
                        tool_calls = native_tool_calls
                        self._discard_parts(content_parts, round_content_parts)
                        self._discard_parts(reasoning_parts, round_reasoning_parts)
                        round_content_parts = []
                        round_reasoning_parts = []
                        self.write_event({
                            "event": "message_replace",
                            "message": "".join(content_parts),
                            "clear_reasoning": True,
                            "discard_reasoning": True,
                        })
                        self.write_event({
                            "event": "status",
                            "status": "native_tool_call",
                            "message": "检测到模型原始工具调用，正在转为本地工具执行。",
                        })
                        await self.flush()
                round_text = "".join(round_content_parts).strip()
                completion_self_assessment = None
                if run_state.completion_review.pending and not tool_calls and round_text:
                    cleaned_text, completion_self_assessment = (
                        extract_completion_self_assessment(round_text)
                    )
                    if completion_self_assessment:
                        self._discard_parts(content_parts, round_content_parts)
                        round_content_parts = [cleaned_text]
                        content_parts.extend(round_content_parts)
                        round_text = cleaned_text
                        self.write_event({
                            "event": "message_replace",
                            "message": "".join(content_parts),
                            "clear_reasoning": False,
                        })
                        await self.flush()
                raw_round_text = (
                    "".join(round_content_parts) + "\n" + "".join(round_reasoning_parts)
                ).strip()
                if run_state.completion_review.pending:
                    decision_reason = ""
                    if (
                        not tool_calls
                        and raw_round_text
                        and self._has_unresolved_tool_call_markup(raw_round_text)
                    ):
                        decision_reason = "malformed_tool_call"
                    decision = build_completion_decision(
                        review_count=run_state.completion_review.review_count,
                        run_result=run_state.completion_review.latest_result,
                        tool_calls=tool_calls,
                        content=round_text,
                        finish_reason=round_finish_reason,
                        reason=decision_reason,
                        evidence_pack=run_state.completion_review.latest_evidence_pack,
                        self_assessment=completion_self_assessment,
                    )
                    metadata.setdefault("completion_decisions", []).append(decision)
                    self.write_event({"event": "completion_decision", "decision": decision})
                    await self.flush()
                    run_state.completion_review.consume()
                if not tool_calls:
                    if (
                        raw_round_text
                        and self._has_unresolved_tool_call_markup(raw_round_text)
                        and run_state.malformed_tool_call_retries < 1
                    ):
                        run_state.malformed_tool_call_retries += 1
                        self._discard_parts(content_parts, round_content_parts)
                        self._discard_parts(reasoning_parts, round_reasoning_parts)
                        self.write_event({
                            "event": "message_replace",
                            "message": "".join(content_parts),
                            "clear_reasoning": True,
                        })
                        self.write_event({
                            "event": "status",
                            "status": "malformed_tool_call_retry",
                            "message": "检测到不可执行的工具调用格式，正在要求模型重新发送结构化调用。",
                        })
                        await self.flush()
                        malformed_message = {
                            "role": "system",
                            "content": self._malformed_tool_call_prompt(
                                workspace.path,
                                raw_round_text,
                            ),
                        }
                        messages.append(malformed_message)
                        run_state.transient_model_context.add(malformed_message)
                        continue
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
                    execution_plan=execution_plan,
                    finish_reason=round_finish_reason,
                    previous_tool_events=tool_events,
                    state=tool_execution_state,
                )
                tool_execution_state = batch_result.state
                tool_events.extend(batch_result.tool_events)
                messages.extend(batch_result.model_messages)
                run_state.transient_model_context.add_from(batch_result.model_messages)
                round_events = tool_events[round_start_event_count:]
                if (
                    run_state.round_number >= run_state.round_limit
                    and run_state.round_limit < run_state.hard_round_limit
                    and any(
                        str(event.get("status") or "") in {"success", "partial"}
                        for event in round_events
                    )
                ):
                    previous_limit, new_limit = run_state.extend_round_budget()
                    self.write_event({
                        "event": "status",
                        "status": "round_budget_extended",
                        "message": (
                            f"第 {run_state.round_number} 轮仍观察到新进展，执行预算已从 "
                            f"{previous_limit} 轮延长到 {new_limit} 轮。"
                        ),
                        "previous_limit": previous_limit,
                        "round_limit": new_limit,
                        "hard_round_limit": run_state.hard_round_limit,
                    })
                    await self.flush()
                visual_context = build_visual_context_messages(
                    round_events,
                    model_config=self.runtime.settings.get_model_config(model),
                    workspace_path=workspace.path,
                    data_dir=getattr(self.runtime.settings, "data_dir", None),
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
                        "message": "已把工具产生的视觉证据加入下一轮模型上下文。",
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
                    execution_context_prompt = format_context_pack_for_prompt(execution_context_pack)
                    if execution_context_prompt:
                        messages = [
                            message
                            for message in messages
                            if not (
                                message.get("role") == "system"
                                and is_context_pack_prompt_for_phase(
                                    message.get("content"),
                                    "execution",
                                )
                            )
                        ]
                        messages.append({
                            "role": "system",
                            "content": execution_context_prompt,
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
                    convergence_message = {
                        "role": "system",
                        "content": self._execution_convergence_prompt(
                            workspace.path,
                            tool_events,
                        ),
                    }
                    messages.append(convergence_message)
                    run_state.transient_model_context.add(convergence_message)
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
                                "已将预算事实反馈给模型继续判断。"
                                if escalated
                                else "已将重复事实反馈给模型自行判断下一步。"
                            )
                        ),
                        "tool": repeated_tool,
                        "failure_count": repeated_failure_count,
                        "route_attempt_count": failure_route_attempt_count,
                        "execution_convergence": convergence_decision.to_dict(),
                    })
                    await self.flush()
                    continue
                has_target_deliverable = self._has_successful_target_deliverable(
                    task_contract,
                    tool_events,
                    workspace.path,
                    effective_mode,
                )
                requires_target_deliverable = self._task_requires_target_deliverable(task_contract)
                has_task_evidence = bool(_event_roles.successful_task_evidence_events(
                    tool_events,
                    task_contract=task_contract,
                    workspace_path=workspace.path,
                    mode=effective_mode,
                ))
                completion_review_gate = build_completion_review_gate(
                    requires_target_deliverable=requires_target_deliverable,
                    has_target_deliverable=has_target_deliverable,
                    has_task_evidence=has_task_evidence,
                    has_unreviewed_evidence=(
                        len(tool_events)
                        > run_state.completion_review.event_count
                    ),
                )
                if completion_review_gate.action == COMPLETION_REVIEW:
                    task_contract_facts = task_contract if isinstance(task_contract, dict) else {}
                    provisional_result = build_run_result(
                        workspace_path=workspace.path,
                        tool_events=tool_events,
                        change_summary=None,
                        mode=effective_mode,
                        requires_code_write=code_change_intent,
                        expected_document_coverage=bool(
                            task_contract_facts.get("expected_document_coverage")
                        ),
                        expected_min_output_chars=int(
                            task_contract_facts.get("expected_min_output_chars") or 0
                        ),
                        task_contract=task_contract,
                        contract_failed=False,
                        max_rounds_exceeded=run_state.max_rounds_exceeded,
                    )
                    completion_evidence_pack = build_completion_evidence_pack(
                        workspace_path=workspace.path,
                        task_contract=task_contract,
                        run_result=provisional_result,
                        tool_events=tool_events,
                        completion_decisions=metadata.get("completion_decisions"),
                        task_route_evidence=metadata.get("task_route_evidence"),
                    )
                    run_state.completion_review.begin(
                        event_count=len(tool_events),
                        run_result=provisional_result,
                        evidence_pack=completion_evidence_pack,
                    )
                    completion_review_message = {
                        "role": "system",
                        "content": self._completion_review_prompt(
                            workspace.path,
                            task_contract,
                            provisional_result,
                            tool_events=tool_events,
                            completion_decisions=metadata.get("completion_decisions"),
                            task_route_evidence=metadata.get("task_route_evidence"),
                            evidence_pack=completion_evidence_pack,
                        ),
                    }
                    messages.append(completion_review_message)
                    run_state.transient_model_context.add(completion_review_message)
                    self.write_event({
                        "event": "status",
                        "status": "completion_review",
                        "message": "任务已有可观察证据，正在要求模型基于运行事实自审是否真正完成。",
                        "review": {
                            "count": run_state.completion_review.review_count,
                            "run_result_status": provisional_result.get("status"),
                            "risks": provisional_result.get("risks") or [],
                            "evidence_pack_schema": completion_evidence_pack.get("schema_version"),
                        },
                    })
                    await self.flush()
                    continue
                if tool_execution_state.read_file_ranges and code_change_intent:
                    read_summary_key = json.dumps(
                        tool_execution_state.read_file_ranges[-8:],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if (
                        len(tool_execution_state.read_file_ranges) >= 2
                        and read_summary_key != run_state.last_read_summary_key
                    ):
                        run_state.last_read_summary_key = read_summary_key
                        read_summary_message = {
                            "role": "system",
                            "content": self._read_range_summary_prompt(
                                workspace.path,
                                tool_execution_state.read_file_ranges[-8:],
                            ),
                        }
                        messages.append(read_summary_message)
                        run_state.transient_model_context.add(read_summary_message)
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
            can_continue_with_runtime_facts = bool(tool_events)
            self.write_event({
                "event": "error",
                "error": run_state.model_provider_error,
                "terminal": not can_continue_with_runtime_facts,
                "recoverable": can_continue_with_runtime_facts,
            })
            await self.flush()
            if not tool_events:
                return

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

