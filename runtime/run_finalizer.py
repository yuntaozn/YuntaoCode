"""Post-loop Run finalization controller.

The finalizer turns already-observed model and tool facts into a RunResult,
recovery checkpoint, final user-facing answer, summary Context Pack, persisted
assistant message, and done event. It does not decide whether the model should
continue a tool loop or which execution strategy it should choose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from runtime.agent_strategy.classifiers import (
    has_successful_write,
    strip_native_tool_call_blocks,
)
from runtime.agent_strategy.plan_tracker import complete_remaining_plan_steps
from runtime.context_manager import count_messages_tokens, get_context_limit
from runtime.context_pack import build_context_pack
from runtime.run_recovery import build_result_context_snapshot
from runtime.run_result import build_run_result
from runtime.run_result_presenter import append_changed_files_footer
from runtime.run_execution_state import RunExecutionState


class RunFinalizationHost(Protocol):
    runtime: Any

    def _task_contract_failures(
        self,
        task_contract: dict[str, Any],
        tool_events: list[dict[str, Any]],
        mode: str | None,
    ) -> list[str]: ...

    def _max_rounds_after_write_message(
        self,
        max_rounds: int,
        tool_events: list[dict[str, Any]],
    ) -> str: ...

    def _max_rounds_message(
        self,
        max_rounds: int,
        tool_events: list[dict[str, Any]],
    ) -> str: ...

    async def _build_change_summary(
        self,
        workspace_path: str,
        mode_config: dict[str, Any],
        change_baseline: Any,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None: ...

    def _answer_only_final_answer_error(
        self,
        content: str,
        tool_events: list[dict[str, Any]],
        task_contract: dict[str, Any] | None = None,
    ) -> str: ...

    def _needs_synthesized_final_answer(
        self,
        content: str,
        tool_events: list[dict[str, Any]],
        *,
        task_contract: dict[str, Any] | None = None,
    ) -> bool: ...

    async def _generate_result_synthesis_answer(
        self,
        *,
        model: str,
        workspace_path: str,
        user_content: str,
        task_contract: dict[str, Any],
        run_result: dict[str, Any],
        previous_answer: str,
    ) -> tuple[str, dict[str, Any]]: ...

    def _synthesize_failure_answer(
        self,
        workspace_path: str,
        tool_events: list[dict[str, Any]],
        run_result: dict[str, Any],
    ) -> str: ...

    def _synthesize_partial_answer(
        self,
        workspace_path: str,
        tool_events: list[dict[str, Any]],
        run_result: dict[str, Any],
    ) -> str: ...

    def _synthesize_final_answer(
        self,
        workspace_path: str,
        tool_events: list[dict[str, Any]],
        change_summary: dict[str, Any] | None,
        mode: str | None,
        task_contract: dict[str, Any] | None = None,
    ) -> str: ...

    def _build_execution_notice(
        self,
        mode: str | None,
        assistant_content: str,
        tool_events: list[dict[str, Any]],
        *,
        requires_code_write: bool,
        contract_failed: bool,
        max_rounds_exceeded: bool,
        run_result: dict[str, Any],
    ) -> str: ...

    def _build_model_messages(
        self,
        conversation: Any,
        workspace: dict[str, Any],
        *,
        record_memory_usage: bool = True,
    ) -> list[dict[str, Any]]: ...

    def _run_status_from_result(self, run_result: dict[str, Any]) -> str: ...

    def write_event(self, payload: dict[str, Any]) -> None: ...

    async def flush(self, include_footers: bool = False) -> None: ...


@dataclass
class RunFinalizationRequest:
    conversation_id: str
    conversation: Any
    workspace: Any
    model: str
    mode_config: dict[str, Any]
    effective_mode: str
    user_content: str
    metadata: dict[str, Any]
    content_parts: list[str]
    reasoning_parts: list[str]
    tool_events: list[dict[str, Any]]
    task_contract: dict[str, Any]
    workspace_snapshot: dict[str, Any]
    active_focus: dict[str, Any]
    capability_snapshot: dict[str, Any]
    capability_preflight: dict[str, Any]
    context_hygiene_report: dict[str, Any]
    run: Any
    execution_plan: dict[str, Any] | None
    change_baseline: Any
    execution_state: RunExecutionState
    requires_code_write: bool
    recon_tool_count: int
    write_repair_mode: bool
    context_tokens: int


@dataclass
class RunFinalizationOutcome:
    assistant_content: str
    run_result: dict[str, Any]
    metadata: dict[str, Any]
    context_tokens: int
    max_rounds_exceeded: bool


class RunFinalizer:
    """Persist and present final Run facts after the execution loop ends."""

    def __init__(self, host: RunFinalizationHost) -> None:
        self._host = host

    async def finalize(self, request: RunFinalizationRequest) -> RunFinalizationOutcome:
        metadata = request.metadata
        tool_events = request.tool_events
        task_contract = request.task_contract
        state = request.execution_state
        contract_failures = self._host._task_contract_failures(
            task_contract,
            tool_events,
            request.effective_mode,
        )
        tool_contract_failed = bool(contract_failures)
        if contract_failures:
            metadata["contract_failures"] = contract_failures

        assistant_content = initial_assistant_content(
            model_content="".join(request.content_parts).strip(),
            model_provider_error=state.model_provider_error,
            no_progress_budget_exhausted=state.no_progress_budget_exhausted,
            has_successful_write=has_successful_write(tool_events),
            max_rounds_exceeded=state.max_rounds_exceeded,
            max_rounds_after_write_message=self._host._max_rounds_after_write_message(
                state.round_limit,
                tool_events,
            ),
            max_rounds_message=self._host._max_rounds_message(
                state.round_limit,
                tool_events,
            ),
            tool_contract_failed=tool_contract_failed,
            contract_failures=contract_failures,
        )
        assistant_content = strip_native_tool_call_blocks(assistant_content).strip()
        if not assistant_content:
            assistant_content = "模型没有返回可显示的最终内容。"
        reasoning = strip_native_tool_call_blocks("".join(request.reasoning_parts)).strip()
        if reasoning:
            metadata["reasoning"] = reasoning
        if tool_events:
            metadata["tool_events"] = tool_events
        if state.max_rounds_exceeded:
            metadata["max_rounds_exceeded"] = True
            metadata["max_rounds"] = state.round_limit
        metadata["recon_tool_count"] = request.recon_tool_count
        if request.write_repair_mode:
            metadata["write_repair_mode_used"] = True
        if state.runtime_intervention_count:
            metadata["runtime_intervention_count"] = state.runtime_intervention_count
        if state.malformed_tool_call_retries:
            metadata["malformed_tool_call_retries"] = state.malformed_tool_call_retries
        if state.progress_observer_count:
            metadata["progress_observer_count"] = state.progress_observer_count
            metadata["stagnant_rounds"] = state.stagnant_rounds
        if state.no_progress_budget_exhausted:
            metadata["no_progress_budget_exhausted"] = True
        if state.completion_review.review_count:
            metadata["completion_review_count"] = state.completion_review.review_count

        if request.execution_plan:
            complete_remaining_plan_steps(
                request.execution_plan,
                failed=(
                    state.no_progress_budget_exhausted
                    or state.max_rounds_exceeded
                    or bool(state.model_provider_error)
                    or (
                        any(event.get("status") == "failure" for event in tool_events)
                        and not any(
                            event.get("status") in {"success", "partial"}
                            for event in tool_events
                        )
                    )
                ),
                had_tool_events=bool(tool_events),
            )
            metadata["execution_plan"] = request.execution_plan

        change_summary = await self._host._build_change_summary(
            request.workspace.path,
            request.mode_config,
            request.change_baseline,
            tool_events,
        )
        if change_summary:
            metadata["change_summary"] = change_summary
            await self._publish({"event": "changes", "summary": change_summary})

        final_answer_error = self._host._answer_only_final_answer_error(
            assistant_content,
            tool_events,
            task_contract,
        )
        if final_answer_error:
            metadata["final_answer_error"] = final_answer_error
        run_result = build_run_result(
            workspace_path=request.workspace.path,
            tool_events=tool_events,
            change_summary=change_summary,
            mode=request.effective_mode,
            requires_code_write=request.requires_code_write,
            expected_document_coverage=bool(
                task_contract.get("expected_document_coverage")
            ),
            expected_min_output_chars=int(
                task_contract.get("expected_min_output_chars") or 0
            ),
            task_contract=task_contract,
            contract_failed=tool_contract_failed,
            max_rounds_exceeded=state.max_rounds_exceeded,
            no_progress_budget_exhausted=state.no_progress_budget_exhausted,
            preflight_advisories=_preflight_advisories(request.capability_preflight),
            model_error=state.model_provider_error,
            final_answer_error=final_answer_error,
        )
        metadata["run_result"] = run_result

        verification_context_pack = build_context_pack(
            phase="verification",
            user_content=request.user_content,
            workspace_snapshot=request.workspace_snapshot,
            task_contract=task_contract,
            active_focus=request.active_focus,
            capability_snapshot=request.capability_snapshot,
            capability_preflight=request.capability_preflight,
            run_result=run_result,
            context_hygiene_report=request.context_hygiene_report,
            task_id=str(getattr(request.run, "task_id", "") or ""),
        )
        metadata["context_pack"] = verification_context_pack
        metadata.setdefault("context_packs", []).append(verification_context_pack)
        self._host.write_event({"event": "context_pack", "pack": verification_context_pack})
        self._host.write_event({"event": "result", "result": run_result})
        await self._host.flush()

        await self._create_recovery_checkpoint(
            request=request,
            run_result=run_result,
            metadata=metadata,
        )

        assistant_content = await self._synthesize_answer(
            request=request,
            assistant_content=assistant_content,
            run_result=run_result,
            change_summary=change_summary,
            tool_contract_failed=tool_contract_failed,
            metadata=metadata,
        )
        assistant_content_with_files = append_changed_files_footer(
            assistant_content,
            run_result,
            change_summary,
        )
        if assistant_content_with_files != assistant_content:
            assistant_content = assistant_content_with_files
            metadata["changed_files_footer_appended"] = True

        execution_notice = self._host._build_execution_notice(
            request.effective_mode,
            assistant_content,
            tool_events,
            requires_code_write=request.requires_code_write,
            contract_failed=tool_contract_failed,
            max_rounds_exceeded=state.max_rounds_exceeded,
            run_result=run_result,
        )
        if execution_notice:
            metadata["execution_notice"] = execution_notice

        summary_context_pack = build_context_pack(
            phase="summary",
            user_content=request.user_content,
            workspace_snapshot=request.workspace_snapshot,
            task_contract=task_contract,
            active_focus=request.active_focus,
            run_result=run_result,
            assistant_content=assistant_content,
            context_hygiene_report=request.context_hygiene_report,
            task_id=str(getattr(request.run, "task_id", "") or ""),
        )
        metadata["context_pack"] = summary_context_pack
        metadata.setdefault("context_packs", []).append(summary_context_pack)
        self._host.write_event({"event": "context_pack", "pack": summary_context_pack})

        assistant_message = self._host.runtime.conversations.add_message(
            request.conversation_id,
            "assistant",
            assistant_content,
            metadata,
        )
        context_tokens = self._final_context_tokens(request)
        done_event = {
            "event": "done",
            "conversation": request.conversation.to_public_dict(include_messages=True),
            "assistant": assistant_message.to_public_dict(),
            "context_tokens": context_tokens,
            "context_limit": (
                metadata.get("effective_context_limit")
                or get_context_limit(request.model, self._host.runtime.settings)
            ),
            "run_status": self._host._run_status_from_result(run_result),
        }
        if metadata.get("usage"):
            done_event["usage"] = metadata["usage"]
        await self._publish(done_event)

        return RunFinalizationOutcome(
            assistant_content=assistant_content,
            run_result=run_result,
            metadata=metadata,
            context_tokens=context_tokens,
            max_rounds_exceeded=state.max_rounds_exceeded,
        )

    async def _create_recovery_checkpoint(
        self,
        *,
        request: RunFinalizationRequest,
        run_result: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        task_id = str(getattr(request.run, "task_id", "") or "")
        if not task_id:
            return
        snapshot_payload = build_result_context_snapshot(
            task_id=task_id,
            run_id=str(request.run.id),
            task_contract=request.task_contract,
            run_result=run_result,
        )
        snapshot_record = self._host.runtime.product_tasks.create_context_snapshot(
            task_id=task_id,
            run_id=str(request.run.id),
            phase="recovery",
            snapshot=snapshot_payload,
        )
        checkpoint = self._host.runtime.product_tasks.create_checkpoint(
            task_id=task_id,
            run_id=str(request.run.id),
            kind="run_result",
            state=str(run_result.get("status") or ""),
            context_snapshot_id=snapshot_record["id"],
            data={
                "run_result": run_result,
                "task_contract": request.task_contract,
            },
        )
        metadata["context_snapshot_id"] = snapshot_record["id"]
        metadata["checkpoint_id"] = checkpoint["id"]
        await self._publish({"event": "checkpoint", "checkpoint": checkpoint})

    async def _synthesize_answer(
        self,
        *,
        request: RunFinalizationRequest,
        assistant_content: str,
        run_result: dict[str, Any],
        change_summary: dict[str, Any] | None,
        tool_contract_failed: bool,
        metadata: dict[str, Any],
    ) -> str:
        status = str(run_result.get("status") or "")
        needs_fact_based_answer = (
            status in {"failure", "partial", "stopped"}
            or self._host._needs_synthesized_final_answer(
                assistant_content,
                request.tool_events,
                task_contract=request.task_contract,
            )
        )
        model_synthesized = False
        if needs_fact_based_answer and not request.execution_state.model_provider_error:
            try:
                synthesized, synthesis_metadata = (
                    await self._host._generate_result_synthesis_answer(
                        model=request.model,
                        workspace_path=request.workspace.path,
                        user_content=request.user_content,
                        task_contract=request.task_contract,
                        run_result=run_result,
                        previous_answer=assistant_content,
                    )
                )
                if synthesized:
                    assistant_content = synthesized
                    model_synthesized = True
                    metadata["synthesized_final_answer"] = True
                    metadata["synthesized_final_answer_source"] = (
                        "model_from_runtime_facts"
                    )
                    if synthesis_metadata:
                        metadata["result_synthesis"] = {
                            key: value
                            for key, value in synthesis_metadata.items()
                            if key != "reasoning"
                        }
            except Exception as exc:
                metadata["result_synthesis_error"] = str(exc)[:500]

        if model_synthesized:
            return assistant_content
        if status == "failure" and not (
            request.execution_state.max_rounds_exceeded or tool_contract_failed
        ):
            metadata["synthesized_final_answer"] = True
            metadata["synthesized_final_answer_source"] = "runtime_fallback"
            return self._host._synthesize_failure_answer(
                request.workspace.path,
                request.tool_events,
                run_result,
            )
        if status == "partial":
            metadata["synthesized_final_answer"] = True
            metadata["synthesized_final_answer_source"] = "runtime_fallback"
            return self._host._synthesize_partial_answer(
                request.workspace.path,
                request.tool_events,
                run_result,
            )
        if self._host._needs_synthesized_final_answer(
            assistant_content,
            request.tool_events,
            task_contract=request.task_contract,
        ):
            metadata["synthesized_final_answer"] = True
            metadata["synthesized_final_answer_source"] = "runtime_fallback"
            return self._host._synthesize_final_answer(
                request.workspace.path,
                request.tool_events,
                change_summary,
                request.effective_mode,
                request.task_contract,
            )
        return assistant_content

    def _final_context_tokens(self, request: RunFinalizationRequest) -> int:
        try:
            final_messages = self._host._build_model_messages(
                request.conversation,
                request.workspace.to_public_dict(),
                record_memory_usage=False,
            )
            return count_messages_tokens(final_messages)
        except Exception:
            return request.context_tokens if isinstance(request.context_tokens, int) else 0

    async def _publish(self, payload: dict[str, Any]) -> None:
        self._host.write_event(payload)
        await self._host.flush()


def initial_assistant_content(
    *,
    model_content: str,
    model_provider_error: str,
    no_progress_budget_exhausted: bool,
    has_successful_write: bool,
    max_rounds_exceeded: bool,
    max_rounds_after_write_message: str,
    max_rounds_message: str,
    tool_contract_failed: bool,
    contract_failures: list[str],
) -> str:
    """Select the pre-synthesis answer from observed finalization facts."""
    if model_provider_error:
        return (
            f"{model_content}\n\n" if model_content else ""
        ) + (
            "模型服务在工具执行后返回错误，本轮没有继续获得可用模型响应。"
            "运行记录会按已观察到的工具结果保存事实；如果已经发生写入或外部状态变化，"
            "本轮会标记为部分完成，便于继续恢复或人工检查。"
        )
    if no_progress_budget_exhausted and has_successful_write:
        return (
            "运行事实提示：本轮已有文件写入成功，但后续同一路线反复无新进展。"
            "当前 Run 已保留失败事实和已写入产物，可基于这些事实继续恢复、换参数或换工具。"
        )
    if no_progress_budget_exhausted:
        return (
            "运行事实提示：同一路线反复无新进展。"
            "当前 Run 已保留失败事实，可基于这些事实继续恢复、换参数、换工具或说明边界。"
        )
    if max_rounds_exceeded:
        return (
            max_rounds_after_write_message
            if has_successful_write
            else max_rounds_message
        )
    if tool_contract_failed and (
        "document_output_too_short" in contract_failures
        or "document_output_length_unknown" in contract_failures
    ):
        if model_content:
            return model_content
        return (
            "运行事实提示：已观察到文本/文档产物，但输出长度证据不足或低于任务目标。"
            "请基于工具记录决定是继续补全、重新导出，还是向用户说明当前证据边界。"
        )
    if tool_contract_failed and (
        "missing_target_deliverable_verification" in contract_failures
        or "missing_target_verification" in contract_failures
    ):
        if model_content:
            return model_content
        return (
            "运行事实提示：本轮缺少足够的目标验证证据。"
            "请基于已观察到的工具结果决定继续验证、换策略，或明确说明证据不足。"
        )
    if tool_contract_failed:
        if model_content:
            return model_content
        return (
            "运行事实提示：本轮观察到任务契约证据缺口。"
            "请根据工具记录继续修正或说明当前证据边界。"
        )
    return model_content or "模型没有返回内容。"


def _preflight_advisories(preflight: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(preflight, dict):
        return []
    advisories = preflight.get("advisories")
    if isinstance(advisories, list):
        return [item for item in advisories if isinstance(item, dict)]
    readiness = preflight.get("readiness_issues")
    if isinstance(readiness, list):
        return [item for item in readiness if isinstance(item, dict)]
    return []
