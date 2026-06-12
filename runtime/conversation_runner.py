from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import tornado.web

from runtime.assistant_modes import get_mode_config
from runtime.context_manager import compress_context, count_messages_tokens, get_context_limit
from runtime.conversation_interactions import (
    confirm_responses as _confirm_responses,
    pending_confirms as _pending_confirms,
    runtime_guidance as _runtime_guidance,
)
from runtime.model_providers.client import stream_chat_completion
from runtime.agent_strategy import task_contract as _tc
from runtime.agent_strategy import tool_event_roles as _event_roles
from runtime.agent_strategy.classifiers import (
    finish_reason_indicates_truncation,
    infer_requested_min_output_chars,
)
from runtime.agent_strategy.policy import deterministic_plan_gate, resolve_profile
from runtime.agent_strategy.profiles import profile_to_public_dict
from runtime.run_result import build_run_result
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

    def _apply_guidance_contract_updates(
        self,
        task_contract: dict[str, Any],
        guidance_text: str,
    ) -> bool:
        min_chars = infer_requested_min_output_chars(guidance_text)
        if min_chars <= 0 or min_chars == int(task_contract.get("expected_min_output_chars") or 0):
            return False
        task_contract["expected_min_output_chars"] = min_chars
        task_contract["success_conditions"] = _tc.success_conditions_for_contract(task_contract)
        overrides = list(task_contract.get("system_overrides") or [])
        overrides.append("expected_min_output_chars")
        task_contract["system_overrides"] = list(dict.fromkeys(str(item) for item in overrides if item))
        self._active_task_contract = task_contract
        return True

    def write_event(self, payload: dict[str, Any]) -> None:
        self.runtime.run_events.emit(self._active_run_id, payload)

    async def flush(self, include_footers: bool = False) -> None:
        return None

    def write_json_line(self, payload: dict[str, Any]) -> None:
        return None

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
        messages = self._build_model_messages(
            conversation,
            workspace.to_public_dict(),
            mode=effective_mode,
        )
        conversation_attachments = self.runtime.attachments.list_for_conversation(conversation_id)
        self._active_attachment_ids = tuple(record.id for record in conversation_attachments)
        image_attachments = [record for record in attachments if record.is_image]
        # Current-turn images become multimodal input. Other attachments remain
        # in the message catalog and are read through controlled tools.
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

        # --- Context compression ---
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
        metadata["context_hygiene"] = context_hygiene_report
        _lang = i18n.get_lang(self._helper.request) if hasattr(self._helper, "request") else ""
        mode_config = get_mode_config(effective_mode, _lang)
        tools, tool_name_map = self._build_model_tools(mode_config)
        max_rounds = mode_config["max_rounds"]
        enable_thinking = bool(payload.get("enable_thinking", True))
        reasoning_effort = str(payload.get("reasoning_effort") or "medium")
        planning_policy = self._normalize_planning_policy(payload)
        confirmation_policy = self._normalize_confirmation_policy(payload)
        plan_mode = planning_policy
        execution_mode = self._normalize_execution_mode({"planning_policy": planning_policy})
        plan_execution = False
        plan_decision: dict[str, Any] = {
            "mode": plan_mode,
            "enabled": False,
            "reason": "",
            "source": "user",
        }
        execution_plan: dict[str, Any] | None = None
        change_baseline = await self._capture_git_status(workspace.path, mode_config)
        task_intent = self._classify_task_intent(
            content,
            effective_mode,
            conversation,
        )
        hard_no_write_lock = self._has_no_write_instruction(content)
        expected_document_coverage = self._expects_full_document_output(content, conversation)
        expected_min_output_chars = self._expected_min_output_chars(content, conversation)
        task_contract = self._build_task_contract(
            task_intent=task_intent,
            mode=effective_mode,
            planning_policy=planning_policy,
            confirmation_policy=confirmation_policy,
            workspace_path=workspace.path,
            expected_document_coverage=expected_document_coverage,
            expected_min_output_chars=expected_min_output_chars,
        )
        inherited_contract = self._previous_task_contract_context(conversation, content)
        direct_contract_inheritance = _tc.looks_like_execute_contract_followup(content)
        if inherited_contract and direct_contract_inheritance and not hard_no_write_lock:
            task_contract = _tc.inherit_task_contract_for_followup(inherited_contract, task_contract)
            metadata["inherited_task_contract"] = True
        elif self._should_use_model_task_contract(
            content,
            task_intent,
            hard_no_write_lock,
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
                hard_no_write_lock=hard_no_write_lock,
                expected_document_coverage=expected_document_coverage,
                expected_min_output_chars=expected_min_output_chars,
                previous_contract=inherited_contract,
            )
        task_intent = str(task_contract.get("intent") or task_intent)
        code_change_intent = bool(task_contract.get("requires_write"))
        state_change_intent = bool(task_contract.get("requires_state_change"))
        agent_profile = resolve_profile(
            task_intent,
            effective_mode,
            code_change_intent=code_change_intent,
            state_change_intent=state_change_intent,
        )
        plan_gate = deterministic_plan_gate(
            content,
            task_intent,
            effective_mode,
            plan_mode,
            profile=agent_profile,
        )
        self._active_task_contract = task_contract
        self._active_confirmation_policy = confirmation_policy
        messages.append({
            "role": "system",
            "content": self._task_contract_prompt(task_contract),
        })
        self.write_event({"event": "task_contract", "contract": task_contract})
        await self.flush()
        if task_intent == "read_only_analysis":
            messages.append({
                "role": "system",
                "content": (
                    self._read_only_task_prompt(workspace.path)
                    if hard_no_write_lock
                    else self._analysis_first_task_prompt(workspace.path)
                ),
            })
        metadata["task_intent"] = task_intent
        metadata["agent_profile"] = profile_to_public_dict(agent_profile)
        metadata["hard_no_write_lock"] = hard_no_write_lock
        metadata["code_change_intent"] = code_change_intent
        metadata["state_change_intent"] = state_change_intent
        metadata["planning_policy"] = planning_policy
        metadata["confirmation_policy"] = confirmation_policy
        # Deprecated compatibility alias for older UI/run readers.
        metadata["execution_mode"] = execution_mode
        metadata["task_contract"] = task_contract
        missing_write_retries = 0
        tool_contract_failed = False
        max_rounds_exceeded = False
        recon_budget_exceeded = False
        recon_tool_count = 0
        recon_refusals = 0
        recon_budget = 16 if self._looks_like_simple_code_change(content) else 24
        seen_recon_signatures: set[str] = set()
        write_only_mode = False
        write_only_rounds = 0
        write_only_prompt_added = False
        write_repair_mode = False
        write_repair_rounds = 0
        write_failure_count = 0
        force_full_file_rewrite = False
        required_tool_choice_supported = True
        read_file_ranges: list[dict[str, Any]] = []  # track file ranges already read to discourage exact repeats
        last_read_summary_key = ""
        post_deliverable_mode = False
        post_deliverable_rounds = 0
        post_deliverable_idle_rounds = 0
        post_deliverable_refusals = 0
        post_deliverable_confirmations = 0
        round_had_post_deliverable_change = False
        round_had_post_deliverable_verification = False
        consecutive_idle_timeouts = 0
        final_answer_mode = False
        verifier_retry_prompted = False
        dangling_action_retries = 0
        malformed_tool_call_retries = 0
        progress_observer_count = 0
        stagnant_rounds = 0
        last_progress_key = ""
        convergence_stopped = False
        strategy_change_intervened = False
        runtime_intervention_pending = False
        runtime_intervention_count = 0
        staged_execution = False
        stage_sequence: list[str] = []
        stage_index = 0
        stage_round_counts: dict[str, int] = {}
        stage_prompted: set[str] = set()
        stage_transitions: list[dict[str, Any]] = []

        try:
            def advance_stage(reason: str) -> bool:
                nonlocal stage_index
                if not staged_execution or stage_index >= len(stage_sequence) - 1:
                    return False
                current = stage_sequence[stage_index]
                stage_index += 1
                stage_transitions.append({
                    "from": current,
                    "to": stage_sequence[stage_index],
                    "reason": reason,
                })
                return True

            if task_contract.get("source") == "model" and plan_mode == "auto":
                plan_execution = bool(task_contract.get("requires_plan"))
                plan_decision = {
                    "mode": plan_mode,
                    "enabled": plan_execution,
                    "reason": "模型任务契约已给出 requires_plan",
                    "source": "task_contract",
                }
            elif not plan_gate.needs_model_judge:
                plan_execution = bool(plan_gate.enabled)
                plan_decision = plan_gate.to_public_dict(plan_mode)
            elif plan_mode == "auto":
                self.write_event({"event": "status", "status": "plan_deciding", "message": "正在判断是否需要计划执行"})
                await self.flush()
                plan_decision = await self._decide_plan_execution(
                    model=model,
                    messages=messages,
                    workspace_path=workspace.path,
                    mode=effective_mode,
                    user_content=content,
                )
                plan_execution = bool(plan_decision.get("enabled"))
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
                metadata["plan_execution_mode"] = "audit_then_execute"

            staged_execution = False
            if staged_execution:
                stage_sequence = self._execution_stage_sequence(
                    effective_mode,
                    code_change_intent,
                    task_intent,
                )
                metadata["stage_execution"] = True
                metadata["stage_sequence"] = ["planner", *stage_sequence]

            for round_index in range(max_rounds):
                round_start_event_count = len(tool_events)
                round_tools = tools
                round_tool_choice = None
                round_enable_thinking = enable_thinking
                round_reasoning_effort = reasoning_effort
                current_stage = (
                    stage_sequence[stage_index]
                    if staged_execution and stage_index < len(stage_sequence)
                    else ""
                )
                guidance_prompt, guidance_text = self._pop_runtime_guidance(conversation_id)
                if guidance_prompt:
                    if self._apply_guidance_contract_updates(task_contract, guidance_text):
                        metadata["task_contract"] = task_contract
                        self.write_event({"event": "task_contract", "contract": task_contract})
                        await self.flush()
                    runtime_intervention_pending = True
                    runtime_intervention_count += 1
                    final_answer_mode = False
                    stage_prompted.clear()
                    if execution_plan:
                        self._interrupt_execution_plan(execution_plan)
                        self.write_event({"event": "plan", "plan": execution_plan})
                        await self.flush()
                    messages.append({
                        "role": "system",
                        "content": self._runtime_intervention_prompt(
                            workspace.path,
                            current_stage,
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
                if runtime_intervention_pending:
                    current_stage = ""
                    runtime_intervention_pending = False
                if current_stage and current_stage not in stage_prompted:
                    stage_prompted.add(current_stage)
                    self.write_event({
                        "event": "status",
                        "status": f"stage_{current_stage}",
                        "message": self._stage_status_message(current_stage),
                    })
                    await self.flush()
                if current_stage:
                    stage_round_counts[current_stage] = stage_round_counts.get(current_stage, 0) + 1
                    # 阶段只提供角色提示与状态展示，不再决定模型能看到哪些工具。
                    # 真正的权限、安全和确认在工具执行层处理。
                    round_tools = tools
                    round_enable_thinking = current_stage in {"explorer", "editor", "reviewer"}
                    round_reasoning_effort = "low"
                    if current_stage == "editor" and code_change_intent:
                        if write_repair_mode:
                            write_repair_rounds += 1
                            round_tool_choice = None
                        else:
                            round_tool_choice = None
                if final_answer_mode:
                    round_tools = None
                    round_enable_thinking = False
                    round_reasoning_effort = "low"
                elif (
                    self._has_successful_target_deliverable(
                        task_contract,
                        tool_events,
                        workspace.path,
                        effective_mode,
                    )
                    and post_deliverable_mode
                ):
                    post_deliverable_rounds += 1
                    # 如果上一轮继续产生目标产物，重置空闲计数器。
                    if round_had_post_deliverable_change:
                        post_deliverable_idle_rounds = 0
                    else:
                        post_deliverable_idle_rounds += 1
                    # 达到终止条件时，先发确认事件给用户，等待响应
                    if (
                        post_deliverable_idle_rounds > 3
                        or post_deliverable_rounds > 10
                    ) and post_deliverable_confirmations < 1:
                        # 发送确认事件并等待用户决策
                        post_deliverable_confirmations += 1
                        confirm_event = asyncio.Event()
                        _pending_confirms[conversation_id] = confirm_event
                        _confirm_responses.pop(conversation_id, None)
                        self.write_event({
                            "event": "confirm",
                            "message": f"已执行 {post_deliverable_rounds} 轮，是否继续？",
                            "progress": {
                                "rounds": post_deliverable_rounds,
                                "idle_rounds": post_deliverable_idle_rounds,
                                "deliverables": len(_event_roles.successful_deliverable_events(
                                    tool_events,
                                    task_contract=task_contract,
                                    workspace_path=workspace.path,
                                    mode=effective_mode,
                                )),
                                "file_writes": len([
                                    e for e in tool_events
                                    if e.get("status") == "success"
                                    and self._is_write_tool(str(e.get("tool") or ""))
                                ]),
                            },
                        })
                        await self.flush()
                        # 等待用户确认；确认态不设置自动超时。
                        try:
                            await confirm_event.wait()
                        finally:
                            _pending_confirms.pop(conversation_id, None)
                        user_action = _confirm_responses.pop(conversation_id, "cancel")
                        if user_action == "continue":
                            # 用户确认继续，重置计数器
                            post_deliverable_idle_rounds = 0
                            self.write_event({
                                "event": "status",
                                "status": "resumed",
                                "message": "用户确认继续执行",
                            })
                            await self.flush()
                            round_tools = tools
                            round_enable_thinking = False
                            round_reasoning_effort = "low"
                        else:
                            # 用户取消或超时，进入终止流程
                            messages.append({
                                "role": "system",
                                "content": self._final_answer_prompt(workspace.path),
                            })
                            final_answer_mode = True
                            round_tools = None
                            round_enable_thinking = False
                            round_reasoning_effort = "low"
                    else:
                        round_tools = tools
                        round_enable_thinking = False
                        round_reasoning_effort = "low"
                elif code_change_intent and not self._has_successful_write(tool_events) and write_only_mode:
                    write_only_rounds += 1
                    if write_repair_mode:
                        write_repair_rounds += 1
                        round_tool_choice = None
                    else:
                        round_tools = tools
                    if not write_repair_mode:
                        round_tool_choice = None
                    round_enable_thinking = False
                    round_reasoning_effort = "low"
                if agent_profile.id == "chat" and not plan_execution:
                    round_tools = None
                    round_tool_choice = None
                    round_enable_thinking = enable_thinking
                    round_reasoning_effort = reasoning_effort
                self.write_event({"event": "status", "status": "thinking", "message": "正在连接模型"})
                await self.flush()
                tool_call_chunks: list[dict[str, Any]] = []
                round_content_parts: list[str] = []
                round_reasoning_parts: list[str] = []
                retry_round_without_required_tool_choice = False
                interrupted_by_guidance = False
                round_finish_reason = ""

                async for event in stream_chat_completion(
                    settings=self.runtime.settings,
                    model=model,
                    messages=self._messages_for_model_round(messages, round_tools),
                    enable_thinking=round_enable_thinking,
                    reasoning_effort=round_reasoning_effort,
                    tools=round_tools or None,
                    tool_choice=round_tool_choice,
                ):
                    if event.get("heartbeat"):
                        self.write_event({
                            "event": "heartbeat",
                            "message": event.get("message") or "模型仍在处理，请稍候",
                            "idle_seconds": event.get("idle_seconds"),
                            "phase": event.get("phase") or "model_stream",
                            "connection_alive": event.get("connection_alive", True),
                        })
                        await self.flush()
                        continue
                    if event.get("error"):
                        # 空闲超时：通知前端并重试或终止
                        if event.get("idle_timeout"):
                            consecutive_idle_timeouts += 1
                            if consecutive_idle_timeouts >= 2:
                                self.write_event({
                                    "event": "error",
                                    "error": "模型服务连续超时，请检查网络连接或稍后重试",
                                })
                                await self.flush()
                                return
                            self.write_event({
                                "event": "status",
                                "status": "idle_timeout",
                                "message": "模型响应超时，正在重试...",
                            })
                            await self.flush()
                            break
                        if round_tool_choice == "required":
                            required_tool_choice_supported = False
                            retry_round_without_required_tool_choice = True
                            messages.append({
                                "role": "system",
                                "content": (
                                    "模型服务未接受 required 工具选择参数。下一轮仍提供执行相关工具，"
                                    "请先读取必要上下文，再调用 code.edit_file、code.replace_text；较大完整文件请使用 filesystem 文本草稿工具最终写入。"
                                ),
                            })
                            self.write_event({
                                "event": "status",
                                "status": "tool_choice_fallback",
                                "message": "模型服务未接受强制工具参数，改用执行工具集重试",
                            })
                            await self.flush()
                            break
                        self.write_event({"event": "error", "error": event["error"]})
                        await self.flush()
                        return
                    if event.get("message"):
                        consecutive_idle_timeouts = 0
                        content_parts.append(event["message"])
                        round_content_parts.append(event["message"])
                        self.write_event({"event": "message", "message": event["message"]})
                    if event.get("reasoning"):
                        consecutive_idle_timeouts = 0
                        reasoning_parts.append(event["reasoning"])
                        round_reasoning_parts.append(event["reasoning"])
                        self.write_event({"event": "reasoning", "reasoning": event["reasoning"]})
                    if event.get("tool_calls"):
                        consecutive_idle_timeouts = 0
                        self._merge_tool_call_chunks(tool_call_chunks, event["tool_calls"])
                    if event.get("usage"):
                        metadata["usage"] = event["usage"]
                    if event.get("finish_reason") is not None:
                        round_finish_reason = str(event["finish_reason"])
                        metadata.setdefault("model_finish_reasons", []).append(round_finish_reason)
                    await self.flush()
                    if _runtime_guidance.get(conversation_id):
                        interrupted_by_guidance = True
                        self.write_event({
                            "event": "status",
                            "status": "runtime_intervention",
                            "message": "收到插话，正在暂停当前输出并重新审视任务",
                        })
                        await self.flush()
                        break

                late_guidance_prompt, late_guidance_text = self._pop_runtime_guidance(conversation_id)
                if late_guidance_prompt:
                    if self._apply_guidance_contract_updates(task_contract, late_guidance_text):
                        metadata["task_contract"] = task_contract
                        self.write_event({"event": "task_contract", "contract": task_contract})
                        await self.flush()
                    runtime_intervention_pending = True
                    runtime_intervention_count += 1
                    final_answer_mode = False
                    stage_prompted.clear()
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
                        "content": self._runtime_intervention_prompt(
                            workspace.path,
                            current_stage,
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

                if retry_round_without_required_tool_choice:
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
                if not tool_calls:
                    round_text = "".join(round_content_parts).strip()
                    raw_round_text = (
                        "".join(round_content_parts) + "\n" + "".join(round_reasoning_parts)
                    ).strip()
                    if (
                        raw_round_text
                        and self._has_unresolved_tool_call_markup(raw_round_text)
                        and malformed_tool_call_retries < 1
                    ):
                        malformed_tool_call_retries += 1
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
                        messages.append({
                            "role": "system",
                            "content": self._malformed_tool_call_prompt(
                                workspace.path,
                                raw_round_text,
                            ),
                        })
                        continue
                    if (
                        round_text
                        and self._looks_like_dangling_action(round_text)
                        and dangling_action_retries < 1
                    ):
                        dangling_action_retries += 1
                        self._discard_parts(content_parts, round_content_parts)
                        self._discard_parts(reasoning_parts, round_reasoning_parts)
                        self.write_event({
                            "event": "message_replace",
                            "message": "".join(content_parts),
                            "clear_reasoning": True,
                        })
                        self.write_event({
                            "event": "status",
                            "status": "dangling_action_retry",
                            "message": "模型停在待执行动作，正在要求它实际调用工具或完成总结。",
                        })
                        await self.flush()
                        messages.append({
                            "role": "system",
                            "content": self._dangling_action_prompt(
                                workspace.path,
                                round_text,
                                tool_events,
                                effective_mode,
                                allow_state_change=bool(task_contract.get("requires_state_change")),
                            ),
                        })
                        continue
                    if (
                        staged_execution
                        and current_stage in {"explorer", "writer", "integrity_gate", "verifier"}
                        and round_content_parts
                    ):
                        messages.append({
                            "role": "assistant",
                            "content": "".join(round_content_parts).strip(),
                        })
                    if staged_execution and current_stage:
                        if current_stage == "explorer":
                            if advance_stage("explorer_completed_without_more_tools"):
                                continue
                        elif current_stage == "creator":
                            self.write_event({
                                "event": "status",
                                "status": "progress_observer",
                                "message": "创作阶段尚未调用文档写入/导出工具，正在提示模型继续推进。",
                            })
                            await self.flush()
                            messages.append({
                                "role": "system",
                                "content": self._progress_observer_prompt(
                                    workspace.path,
                                    current_stage,
                                    tool_events,
                                    code_change_intent,
                                    "creator_no_output_tool",
                                ),
                            })
                            continue
                        elif current_stage == "verifier":
                            if (
                                self._has_successful_write(tool_events)
                                and not self._has_successful_verification(tool_events, effective_mode)
                                and not verifier_retry_prompted
                            ):
                                verifier_retry_prompted = True
                                messages.append({
                                    "role": "system",
                                    "content": self._verifier_retry_prompt(effective_mode, workspace.path),
                                })
                                self.write_event({
                                    "event": "status",
                                    "status": "verifier_retry",
                                    "message": "验证阶段尚未调用验证工具，正在要求模型执行一次实际验证。",
                                })
                                await self.flush()
                                continue
                            if (
                                task_contract.get("requires_verification")
                                and self._has_successful_write(tool_events)
                                and not self._has_successful_verification(tool_events, effective_mode)
                            ):
                                self.write_event({
                                    "event": "status",
                                    "status": "progress_observer",
                                    "message": "验证者阶段尚未调用验证工具，正在提示模型继续推进。",
                                })
                                await self.flush()
                                messages.append({
                                    "role": "system",
                                    "content": self._progress_observer_prompt(
                                        workspace.path,
                                        current_stage,
                                        tool_events,
                                        code_change_intent,
                                        "verifier_no_verification_tool",
                                    ),
                                })
                                continue
                            if advance_stage("verifier_completed_without_more_tools"):
                                continue
                        elif current_stage == "writer":
                            if advance_stage("writer_completed_without_file_output"):
                                continue
                        elif current_stage == "integrity_gate":
                            if advance_stage("integrity_gate_completed"):
                                continue
                        elif current_stage == "reviewer":
                            break
                        elif current_stage == "editor" and self._has_successful_write(tool_events):
                            if advance_stage("editor_already_wrote"):
                                continue
                        elif current_stage == "editor":
                            if missing_write_retries < 2:
                                missing_write_retries += 1
                                if code_change_intent and not write_repair_mode:
                                    write_only_mode = True
                                    write_only_prompt_added = False
                                messages.append({
                                    "role": "system",
                                    "content": self._tool_contract_correction_prompt(
                                        workspace.path,
                                        write_only=write_only_mode and not write_repair_mode,
                                    ),
                                })
                                self.write_event({
                                    "event": "status",
                                    "status": "tool_contract_retry",
                                    "message": "执行者阶段没有调用写入工具，正在继续要求模型执行真实修改。",
                                })
                                await self.flush()
                                continue
                            self.write_event({
                                "event": "status",
                                "status": "progress_observer",
                                "message": "执行者阶段仍未写入，正在进行进度纠偏而不是停止任务。",
                            })
                            await self.flush()
                            messages.append({
                                "role": "system",
                                "content": self._progress_observer_prompt(
                                    workspace.path,
                                    current_stage,
                                    tool_events,
                                    code_change_intent,
                                    "editor_no_write_tool",
                                ),
                            })
                            continue
                    if code_change_intent and not self._has_successful_write(tool_events):
                        self._discard_parts(content_parts, round_content_parts)
                        self._discard_parts(reasoning_parts, round_reasoning_parts)
                        self.write_event({
                            "event": "message_replace",
                            "message": "".join(content_parts),
                            "clear_reasoning": True,
                        })
                        self.write_event({
                            "event": "status",
                            "status": "tool_contract_failed",
                            "message": "模型没有调用本地写入工具；系统记录真实失败，不再注入纠偏提示。",
                        })
                        await self.flush()
                        break
                        if missing_write_retries < 1:
                            missing_write_retries += 1
                            if not write_repair_mode:
                                write_only_mode = True
                                write_only_prompt_added = False
                            self.write_event({
                                "event": "status",
                                "status": "tool_contract_retry",
                                "message": "模型没有调用本地写入工具，正在重新要求它执行真实修改",
                            })
                            await self.flush()
                            messages.append({
                                "role": "system",
                                "content": self._tool_contract_correction_prompt(
                                    workspace.path,
                                    write_only=write_only_mode,
                                ),
                            })
                            continue
                        self.write_event({
                            "event": "status",
                            "status": "progress_observer",
                            "message": "模型仍未调用本地写入工具，正在进行进度纠偏。",
                        })
                        await self.flush()
                        messages.append({
                            "role": "system",
                            "content": self._progress_observer_prompt(
                                workspace.path,
                                current_stage,
                                tool_events,
                                code_change_intent,
                                "missing_write_tool_after_retry",
                            ),
                        })
                        continue
                    if (
                        task_contract.get("requires_verification")
                        and self._has_successful_target_deliverable(
                            task_contract,
                            tool_events,
                            workspace.path,
                            effective_mode,
                        )
                        and not self._has_successful_target_verification(
                            task_contract,
                            tool_events,
                            workspace.path,
                            effective_mode,
                        )
                    ):
                        self._discard_parts(content_parts, round_content_parts)
                        self._discard_parts(reasoning_parts, round_reasoning_parts)
                        if not verifier_retry_prompted:
                            verifier_retry_prompted = True
                            messages.append({
                                "role": "system",
                                "content": self._verifier_retry_prompt(effective_mode, workspace.path),
                            })
                            self.write_event({
                                "event": "status",
                                "status": "verifier_retry",
                                "message": "目标产物已出现但尚未取得验证证据，正在要求模型调用只读验证能力。",
                            })
                            await self.flush()
                            continue
                        self.write_event({
                            "event": "status",
                            "status": "verification_contract_failed",
                            "message": "目标产物已出现但没有成功验证；系统记录真实结果，不再继续空转。",
                        })
                        await self.flush()
                        break
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
                round_had_post_deliverable_change = False
                round_had_post_deliverable_verification = False
                for tool_call in tool_calls:
                    tool_id, arguments = self._tool_call_details(tool_call, tool_name_map)
                    if finish_reason_indicates_truncation(round_finish_reason):
                        tool_message, tool_event = self._skipped_tool_call(
                            tool_call,
                            tool_id,
                            arguments,
                            reason="truncated_tool_call",
                            message=(
                                "The model response stopped at its output limit while building "
                                "this tool call. The runtime did not execute incomplete arguments. "
                                "Retry with materially smaller complete arguments; split large "
                                "content across several tool calls."
                            ),
                        )
                        tool_events.append(tool_event)
                        self.write_event({"event": "tool", **tool_event})
                        await self.flush()
                        messages.append(tool_message)
                        continue
                    if hard_no_write_lock and self._is_state_changing_tool(tool_id):
                        tool_message, tool_event = self._skipped_tool_call(
                            tool_call,
                            tool_id,
                            arguments,
                            reason="hard_no_write_lock",
                            message="用户已明确要求不要修改/只分析，执行层已拦截会改变本地状态的工具调用。",
                        )
                        tool_events.append(tool_event)
                        self.write_event({"event": "tool", **tool_event})
                        await self.flush()
                        messages.append(tool_message)
                        continue
                    plan_step_index = self._mark_next_plan_step_running(
                        execution_plan,
                        tool_call,
                    )
                    if plan_step_index is not None and execution_plan:
                        self.write_event({
                            "event": "plan_step",
                            "index": plan_step_index,
                            "step": execution_plan["steps"][plan_step_index],
                        })
                        await self.flush()
                    self._active_tool_events = tool_events
                    self._active_current_stage = current_stage or ""
                    self._active_post_deliverable_mode = post_deliverable_mode
                    if (
                        code_change_intent
                        and not self._has_successful_write(tool_events)
                        and self._is_recon_tool(tool_id)
                        and not write_repair_mode
                    ):
                        signature = self._tool_signature(tool_id, arguments)
                        is_duplicate = signature in seen_recon_signatures
                        if recon_tool_count >= recon_budget and not is_duplicate:
                            recon_refusals += 1
                            recon_budget_exceeded = True
                            write_only_mode = True
                            if recon_refusals <= 3:
                                messages.append({
                                    "role": "system",
                                    "content": self._recon_budget_prompt(recon_budget, workspace.path),
                                })
                                messages.pop()
                        # 读取/搜索不再被硬拒绝。执行后由契约与重复检测决定是否继续推进。
                        tool_message, tool_event = await self._execute_tool_call(
                            tool_call,
                            tool_name_map,
                            workspace.path,
                        )
                        if (
                            tool_event.get("status") == "success"
                            and arguments.get("path")
                        ):
                            if not is_duplicate:
                                seen_recon_signatures.add(signature)
                                recon_tool_count += 1
                            else:
                                duplicate_hint = {
                                    "role": "system",
                                    "content": (
                                        "提示：本次读取与之前的同名同范围读取重复。"
                                        "如已掌握目标文件内容，请尽快调用 "
                                        "code.edit_file / code.replace_text 进入写入；较大完整文件请使用 filesystem.finalize_text_file。"
                                        "如需查看不同范围，请改变 start_line / end_line 参数。"
                                    ),
                                }
                                messages.append(duplicate_hint)
                                messages.pop()
                    else:
                        tool_message, tool_event = await self._execute_tool_call(
                            tool_call,
                            tool_name_map,
                            workspace.path,
                        )
                    tool_events.append(tool_event)
                    if self._is_recoverable_write_failure(tool_id, tool_event):
                        write_failure_count += 1
                        write_repair_mode = True
                        write_only_mode = False
                        if write_failure_count >= 2:
                            force_full_file_rewrite = True
                        # 自动读取目标文件片段，直接注入上下文，避免模型拒绝读取
                        auto_read_content = ""
                        repair_prompt = self._write_repair_prompt(
                            tool_id,
                            arguments,
                            tool_event,
                            workspace.path,
                            force_full_file_rewrite=force_full_file_rewrite,
                        )
                        if auto_read_content:
                            repair_prompt += f"\n\n系统已自动读取目标文件的相关内容：\n```\n{auto_read_content}\n```\n请基于以上实际内容构造准确的 old_text。"
                        messages.append({
                            "role": "system",
                            "content": repair_prompt,
                        })
                        messages.pop()
                        self.write_event({
                            "event": "status",
                            "status": "write_repair_mode",
                            "message": "写入工具匹配失败，已自动读取目标文件并切换为修复模式。",
                        })
                        await self.flush()
                    elif self._is_write_tool(tool_id) and tool_event.get("status") == "success":
                        write_repair_mode = False
                        force_full_file_rewrite = False
                    if tool_id == "filesystem.read_file" and tool_event.get("status") == "success":
                        read_file_ranges.append(
                            self._read_file_range_record(arguments, tool_event)
                        )
                    if post_deliverable_mode and tool_event.get("status") == "success":
                        event_role = _event_roles.classify_tool_event_role(
                            tool_event,
                            task_contract=task_contract,
                            workspace_path=workspace.path,
                            mode=effective_mode,
                        )
                        if event_role == _event_roles.DELIVERABLE:
                            round_had_post_deliverable_change = True
                        elif (
                            event_role == _event_roles.VERIFICATION
                            or self._is_deliverable_verification_tool(tool_id)
                        ):
                            round_had_post_deliverable_verification = True
                    self.write_event({"event": "tool", **tool_event})
                    await self.flush()
                    if plan_step_index is not None and execution_plan:
                        self._finish_plan_step(execution_plan, plan_step_index, tool_event)
                        self.write_event({
                            "event": "plan_step",
                            "index": plan_step_index,
                            "step": execution_plan["steps"][plan_step_index],
                        })
                        await self.flush()
                    messages.append(tool_message)
                round_events = tool_events[round_start_event_count:]
                repeated_failure_count = self._consecutive_repeated_failure_count(tool_events)
                repeated_failure_action = self._repeated_failure_action(
                    tool_events,
                    strategy_change_intervened=strategy_change_intervened,
                )
                if repeated_failure_action == "none":
                    strategy_change_intervened = False
                if repeated_failure_action == "stop":
                    convergence_stopped = True
                    repeated_tool = str(tool_events[-1].get("tool") or "unknown tool")
                    self.write_event({
                        "event": "status",
                        "status": "repeated_tool_failure",
                        "message": (
                            f"{repeated_tool} 已连续出现 {repeated_failure_count} 次相同失败，"
                            "执行已停止重复重试，正在保存真实结果。"
                        ),
                        "tool": repeated_tool,
                        "failure_count": repeated_failure_count,
                    })
                    await self.flush()
                    break
                if repeated_failure_action == "change_strategy":
                    strategy_change_intervened = True
                    repeated_tool = str(tool_events[-1].get("tool") or "unknown tool")
                    messages.append({
                        "role": "system",
                        "content": self._repeated_failure_strategy_prompt(
                            workspace.path,
                            current_stage,
                            tool_events,
                        ),
                    })
                    self.write_event({
                        "event": "status",
                        "status": "strategy_change_required",
                        "message": (
                            f"{repeated_tool} 已连续出现 2 次相同失败，"
                            "正在要求模型重新判断并更换执行策略。"
                        ),
                        "tool": repeated_tool,
                        "failure_count": repeated_failure_count,
                    })
                    await self.flush()
                    continue
                progress_key = self._progress_key(tool_events, effective_mode)
                if progress_key and progress_key == last_progress_key:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                    last_progress_key = progress_key
                if (
                    code_change_intent
                    and not self._has_successful_write(tool_events)
                    and progress_observer_count < 1
                    and (
                        stagnant_rounds >= 2
                        or (recon_tool_count >= recon_budget and round_events)
                        or self._round_has_only_non_progress(round_events)
                    )
                ):
                    progress_observer_count += 1
                    messages.append({
                        "role": "system",
                        "content": self._progress_observer_prompt(
                            workspace.path,
                            current_stage,
                            tool_events,
                            code_change_intent,
                            "stagnant_before_write",
                        ),
                    })
                    messages.pop()
                    self.write_event({
                        "event": "status",
                        "status": "progress_observer",
                        "message": "进度观察器发现执行没有接近写入，已提示模型调整下一步。",
                    })
                    await self.flush()
                    continue
                if staged_execution and current_stage:
                    stage_limit = self._stage_round_limit(current_stage, effective_mode, code_change_intent)
                    if current_stage == "explorer" and stage_round_counts.get(current_stage, 0) >= stage_limit:
                        if advance_stage("explorer_round_limit_reached"):
                            continue
                    if current_stage == "editor":
                        if self._has_successful_write(tool_events):
                            if advance_stage("editor_write_success"):
                                continue
                        elif stage_round_counts.get(current_stage, 0) >= stage_limit:
                            if write_repair_mode and write_repair_rounds <= 3:
                                messages.append({
                                    "role": "system",
                                    "content": (
                                        "写入修复仍未完成。请基于刚才读取到的真实文件片段，"
                                        "立即再次调用 code.edit_file、code.replace_text；较大完整文件请使用 filesystem 文本草稿工具。"
                                    ),
                                })
                                self.write_event({
                                    "event": "status",
                                    "status": "write_repair_retry",
                                    "message": "写入修复模式需要额外一轮，正在继续尝试真实写入。",
                                })
                                await self.flush()
                                continue
                            self.write_event({
                                "event": "status",
                                "status": "progress_observer",
                                "message": "执行者阶段尚未写入，正在提示模型调整策略继续执行。",
                            })
                            await self.flush()
                            messages.append({
                                "role": "system",
                                "content": self._progress_observer_prompt(
                                    workspace.path,
                                    current_stage,
                                    tool_events,
                                    code_change_intent,
                                    "editor_round_limit_without_write",
                                ),
                            })
                            continue
                    if current_stage == "writer":
                        if advance_stage("writer_tool_round_completed"):
                            continue
                    if current_stage == "creator":
                        if self._has_successful_write(tool_events):
                            if advance_stage("creator_output_success"):
                                continue
                        elif stage_round_counts.get(current_stage, 0) >= stage_limit:
                            self.write_event({
                                "event": "status",
                                "status": "progress_observer",
                                "message": "创作阶段尚未输出文件，正在提示模型继续推进。",
                            })
                            await self.flush()
                            messages.append({
                                "role": "system",
                                "content": self._progress_observer_prompt(
                                    workspace.path,
                                    current_stage,
                                    tool_events,
                                    code_change_intent,
                                    "creator_round_limit_without_output",
                                ),
                            })
                            continue
                    if current_stage == "integrity_gate":
                        if advance_stage("integrity_gate_tool_round_completed"):
                            continue
                    if current_stage == "verifier":
                        if self._has_successful_verification(tool_events, effective_mode):
                            if advance_stage("verifier_tool_round_completed"):
                                continue
                        elif stage_round_counts.get(current_stage, 0) >= stage_limit:
                            if advance_stage("verifier_round_limit_reached"):
                                continue
                        else:
                            continue
                if self._has_successful_target_deliverable(
                    task_contract,
                    tool_events,
                    workspace.path,
                    effective_mode,
                ):
                    if self._has_successful_target_verification(
                        task_contract,
                        tool_events,
                        workspace.path,
                        effective_mode,
                    ):
                        messages.append({
                            "role": "system",
                            "content": self._final_answer_prompt(workspace.path),
                        })
                        final_answer_mode = True
                        self.write_event({
                            "event": "status",
                            "status": "success_conditions_met",
                            "message": "目标产物与验证均已完成，正在生成最终结果",
                        })
                        await self.flush()
                        continue
                    if not post_deliverable_mode:
                        post_deliverable_mode = True
                        messages.append({
                            "role": "system",
                            "content": self._post_deliverable_prompt(workspace.path),
                        })
                        messages.pop()
                        self.write_event({
                            "event": "status",
                            "status": "post_deliverable_stage",
                            "message": "目标产物已出现，进度观察器建议继续验证或总结",
                        })
                        await self.flush()
                        continue
                    if post_deliverable_rounds >= 3 and (
                        round_had_post_deliverable_verification
                        or (
                            post_deliverable_refusals > 2
                            and not round_had_post_deliverable_change
                        )
                    ):
                        messages.append({
                            "role": "system",
                            "content": self._final_answer_prompt(workspace.path),
                        })
                        final_answer_mode = True
                        self.write_event({
                            "event": "status",
                            "status": "finalizing",
                            "message": "目标产物完成后的执行已收束，正在生成最终结果",
                        })
                        await self.flush()
                        continue
                if read_file_ranges and code_change_intent:
                    read_summary_key = json.dumps(read_file_ranges[-8:], ensure_ascii=False, sort_keys=True)
                    if len(read_file_ranges) >= 2 and read_summary_key != last_read_summary_key:
                        last_read_summary_key = read_summary_key
                        messages.append({
                            "role": "system",
                            "content": self._read_range_summary_prompt(
                                workspace.path,
                                read_file_ranges[-8:],
                            ),
                        })
                        messages.pop()
                if (
                    write_only_mode
                    and not write_only_prompt_added
                    and code_change_intent
                    and not self._has_successful_write(tool_events)
                ):
                    write_only_prompt_added = True
                    messages.append({
                        "role": "system",
                        "content": self._write_only_stage_prompt(workspace.path),
                    })
                    messages.pop()
                    self.write_event({
                        "event": "status",
                        "status": "write_only_stage",
                        "message": "已进入执行压力阶段，下一轮保留必要读取/搜索并要求推进到真实修改",
                    })
                    await self.flush()
                if (
                    code_change_intent
                    and not self._has_successful_write(tool_events)
                    and recon_tool_count >= recon_budget
                    and recon_refusals == 0
                ):
                    write_only_mode = True
                    messages.append({
                        "role": "system",
                        "content": self._recon_budget_prompt(recon_budget, workspace.path),
                    })
                    messages.pop()
                    self.write_event({
                        "event": "status",
                        "status": "recon_budget_exhausted",
                        "message": "已完成足够的搜索/读取，正在要求模型进入写入步骤",
                    })
                    await self.flush()
                if (
                    code_change_intent
                    and not self._has_successful_write(tool_events)
                    and write_only_rounds >= 4
                    and recon_refusals >= 4
                ):
                    recon_budget_exceeded = True
                    self.write_event({
                        "event": "status",
                        "status": "progress_observer",
                        "message": "模型仍在重复读取/搜索，正在进行进度纠偏。",
                    })
                    await self.flush()
                    messages.append({
                        "role": "system",
                        "content": self._progress_observer_prompt(
                            workspace.path,
                            current_stage,
                            tool_events,
                            code_change_intent,
                            "repeated_recon_without_write",
                        ),
                    })
                    messages.pop()
                    break
            else:
                max_rounds_exceeded = True
                self.write_event({
                    "event": "status",
                    "status": "max_tool_rounds",
                    "message": "工具调用轮次达到上限，正在保存诊断信息",
                })
                await self.flush()
        except tornado.web.HTTPError as exc:
            self.write_event({"event": "error", "error": exc.reason})
            await self.flush()
            return

        contract_failures = self._task_contract_failures(
            task_contract,
            tool_events,
            effective_mode,
        )
        if contract_failures:
            metadata["contract_failures"] = contract_failures
            tool_contract_failed = True

        if convergence_stopped and self._has_successful_write(tool_events):
            assistant_content = (
                "执行已停止重复重试：本轮已有文件写入成功，但后续工具连续返回相同错误，"
                "系统没有继续空转。请检查下方失败记录和已写入文件后再决定是否继续。"
            )
        elif convergence_stopped:
            assistant_content = (
                "执行未完成：同一工具连续返回相同错误，系统已停止重复重试。"
                "请检查下方失败记录，修正调用参数或任务说明后再继续。"
            )
        elif max_rounds_exceeded and self._has_successful_write(tool_events):
            assistant_content = self._max_rounds_after_write_message(max_rounds, tool_events)
        elif max_rounds_exceeded:
            assistant_content = self._max_rounds_message(max_rounds, tool_events)
        elif recon_budget_exceeded and tool_contract_failed:
            assistant_content = (
                "未完成需要的写入/导出：模型一直停留在读取/搜索阶段，已经超过本轮允许的侦察预算，"
                "系统已停止继续空转。本轮没有成功生成或更新任务目标产物。"
            )
        elif tool_contract_failed and "missing_target_deliverable_verification" in contract_failures:
            model_content = "".join(content_parts).strip()
            assistant_content = (
                f"{model_content}\n\n" if model_content else ""
            ) + (
                "未完整完成：本轮已经生成或更新目标产物，但没有成功取得真实验证证据，"
                "因此系统不会把它标记为完整完成。请继续下一轮执行验证。"
            )
        elif tool_contract_failed:
            model_content = "".join(content_parts).strip()
            assistant_content = (
                f"{model_content}\n\n" if model_content else ""
            ) + (
                "未完成需要的写入/导出：本轮没有成功生成或更新任务目标产物，"
                "因此本轮没有生成或修改目标文件。"
            )
        else:
            assistant_content = "".join(content_parts).strip() or "模型没有返回内容。"
        assistant_content = self._strip_native_tool_call_blocks(assistant_content).strip()
        if not assistant_content:
            assistant_content = "模型没有返回可显示的最终内容。"
        reasoning = self._strip_native_tool_call_blocks("".join(reasoning_parts)).strip()
        if reasoning:
            metadata["reasoning"] = reasoning
        if tool_events:
            metadata["tool_events"] = tool_events
        if max_rounds_exceeded:
            metadata["max_rounds_exceeded"] = True
            metadata["max_rounds"] = max_rounds
        if recon_budget_exceeded:
            metadata["recon_budget_exceeded"] = True
            metadata["recon_budget"] = recon_budget
            metadata["recon_tool_count"] = recon_tool_count
            metadata["recon_refusals"] = recon_refusals
        if write_only_mode:
            metadata["write_only_mode_used"] = True
            metadata["write_only_rounds"] = write_only_rounds
            metadata["required_tool_choice_supported"] = required_tool_choice_supported
        if write_repair_mode:
            metadata["write_repair_mode_used"] = True
            metadata["write_repair_rounds"] = write_repair_rounds
        if runtime_intervention_count:
            metadata["runtime_intervention_count"] = runtime_intervention_count
        if malformed_tool_call_retries:
            metadata["malformed_tool_call_retries"] = malformed_tool_call_retries
        if progress_observer_count:
            metadata["progress_observer_count"] = progress_observer_count
            metadata["stagnant_rounds"] = stagnant_rounds
        if convergence_stopped:
            metadata["convergence_stopped"] = True
        if post_deliverable_mode:
            metadata["post_deliverable_mode_used"] = True
            metadata["post_deliverable_rounds"] = post_deliverable_rounds
            metadata["post_deliverable_refusals"] = post_deliverable_refusals
        if staged_execution:
            metadata["stage_round_counts"] = stage_round_counts
            metadata["stage_transitions"] = stage_transitions
        if execution_plan:
            self._complete_remaining_plan_steps(
                execution_plan,
                failed=convergence_stopped or max_rounds_exceeded or tool_contract_failed or any(event.get("status") == "failure" for event in tool_events),
                had_tool_events=bool(tool_events),
            )
            metadata["execution_plan"] = execution_plan
        change_summary = await self._build_change_summary(
            workspace.path,
            mode_config,
            change_baseline,
            tool_events,
        )
        if change_summary:
            metadata["change_summary"] = change_summary
            self.write_event({"event": "changes", "summary": change_summary})
            await self.flush()
        run_result = build_run_result(
            workspace_path=workspace.path,
            tool_events=tool_events,
            change_summary=change_summary,
            mode=effective_mode,
            requires_code_write=code_change_intent,
            expected_document_coverage=bool(task_contract.get("expected_document_coverage")),
            expected_min_output_chars=int(task_contract.get("expected_min_output_chars") or 0),
            task_contract=task_contract,
            contract_failed=tool_contract_failed,
            max_rounds_exceeded=max_rounds_exceeded,
            convergence_stopped=convergence_stopped,
        )
        metadata["run_result"] = run_result
        self.write_event({"event": "result", "result": run_result})
        await self.flush()
        run_result_status = str(run_result.get("status") or "")
        if run_result_status == "failure" and not (
            max_rounds_exceeded or tool_contract_failed
        ):
            assistant_content = self._synthesize_failure_answer(
                workspace.path,
                tool_events,
                run_result,
            )
            metadata["synthesized_final_answer"] = True
        elif run_result_status == "partial":
            assistant_content = self._synthesize_partial_answer(
                workspace.path,
                tool_events,
                run_result,
            )
            metadata["synthesized_final_answer"] = True
        elif self._needs_synthesized_final_answer(assistant_content, tool_events):
            assistant_content = self._synthesize_final_answer(
                workspace.path,
                tool_events,
                change_summary,
                effective_mode,
                task_contract,
            )
            metadata["synthesized_final_answer"] = True
        execution_notice = self._build_execution_notice(
            effective_mode,
            assistant_content,
            tool_events,
            requires_code_write=code_change_intent,
            contract_failed=tool_contract_failed,
            max_rounds_exceeded=max_rounds_exceeded,
        )
        if execution_notice:
            metadata["execution_notice"] = execution_notice
        assistant_message = self.runtime.conversations.add_message(
            conversation_id,
            "assistant",
            assistant_content,
            metadata,
        )
        # Recalculate context tokens after all messages/tool rounds are done
        try:
            final_messages = self._build_model_messages(
                conversation,
                workspace.to_public_dict(),
                mode=effective_mode,
            )
            context_tokens = count_messages_tokens(final_messages)
        except Exception:
            context_tokens = context_tokens if isinstance(context_tokens, int) else 0
        done_event = {
            "event": "done",
            "conversation": conversation.to_public_dict(include_messages=True),
            "assistant": assistant_message.to_public_dict(),
            "context_tokens": context_tokens,
            "context_limit": get_context_limit(model, self.runtime.settings),
        }
        if metadata.get("usage"):
            done_event["usage"] = metadata["usage"]
        done_event["run_status"] = self._run_status_from_result(run_result)
        self.write_event(done_event)
        await self.flush()

        # Async memory extraction (non-blocking)
        if self.runtime.settings.is_memory_auto_extract_enabled() and not max_rounds_exceeded:
            asyncio.create_task(self._extract_and_store_memories(messages, model, conversation_id))

    async def _extract_and_store_memories(
        self,
        messages: list[dict[str, Any]],
        model: str,
        conversation_id: str,
    ) -> None:
        """Async memory extraction - runs after the conversation response is sent."""
        try:
            from runtime.memory_extractor import extract_and_store_memories

            await extract_and_store_memories(
                store=self.runtime.settings.memory_store,
                messages=messages,
                model=model,
                settings=self.runtime.settings,
                conversation_id=conversation_id,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Background memory extraction failed")

