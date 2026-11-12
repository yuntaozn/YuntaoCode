"""循环结束后的 Run 收尾控制器。

Finalizer 将已观察到的模型与工具事实转换为 RunResult、恢复 Checkpoint、
主模型答案、摘要 Context Pack、持久化助手消息和 done 事件。
它不决定模型是否应继续工具循环，也不选择执行策略。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from runtime.context_manager import count_messages_tokens, get_context_limit
from runtime.context_pack import build_context_pack
from runtime.run_recovery import build_result_context_snapshot
from runtime.run_result import build_run_result
from runtime.run_execution_state import RunExecutionState


class RunFinalizationHost(Protocol):
    runtime: Any

    async def _wait_if_paused(self) -> None: ...

    async def _build_change_summary(
        self,
        workspace_path: str,
        mode_config: dict[str, Any],
        change_baseline: Any,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None: ...


    def _build_execution_notice(
        self,
        mode: str | None,
        assistant_content: str,
        tool_events: list[dict[str, Any]],
        *,
        requires_code_write: bool,
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


def _latest_completion_decision(metadata: dict[str, Any]) -> dict[str, Any] | None:
    values = metadata.get("completion_decisions")
    if not isinstance(values, list):
        return None
    for item in reversed(values):
        if isinstance(item, dict):
            return item
    return None


class RunFinalizer:
    """执行循环结束后持久化并展示最终 Run 事实。"""

    def __init__(self, host: RunFinalizationHost) -> None:
        self._host = host

    def _build_result(
        self,
        *,
        request: RunFinalizationRequest,
        change_summary: dict[str, Any] | None,
        final_answer_error: str,
        answer_text: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        task_contract = request.task_contract
        return build_run_result(
            workspace_path=request.workspace.path,
            tool_events=request.tool_events,
            change_summary=change_summary,
            mode=request.effective_mode,
            requires_code_write=request.requires_code_write,
            task_contract=task_contract,
            max_rounds_exceeded=request.execution_state.max_rounds_exceeded,
            preflight_advisories=_preflight_advisories(request.capability_preflight),
            model_error=request.execution_state.model_provider_error,
            final_answer_error=final_answer_error,
            answer_text=answer_text,
            completion_decision=_latest_completion_decision(metadata),
            visual_context=metadata.get("visual_context_evidence"),
        )

    async def finalize(self, request: RunFinalizationRequest) -> RunFinalizationOutcome:
        metadata = request.metadata
        tool_events = request.tool_events
        task_contract = request.task_contract
        state = request.execution_state
        model_content = "".join(request.content_parts)
        assistant_content = initial_assistant_content(
            model_content=model_content,
            model_provider_error=state.model_provider_error,
            max_rounds_exceeded=state.max_rounds_exceeded,
            round_limit=state.round_limit,
        )
        reasoning = "".join(request.reasoning_parts).strip()
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
        if state.guidance_count:
            metadata["guidance_count"] = state.guidance_count
            metadata["runtime_intervention_count"] = state.guidance_count
        if request.execution_plan:
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

        # 用户可能在最后一次模型响应或变更摘要期间暂停；发布结果前尊重该状态。
        await self._host._wait_if_paused()
        final_answer_error = "" if model_content.strip() else "model did not return a final answer"
        run_result = self._build_result(
            request=request, change_summary=change_summary,
            final_answer_error=final_answer_error,
            answer_text=model_content if model_content.strip() else None,
            metadata=metadata,
        )
        if final_answer_error:
            metadata["final_answer_error"] = final_answer_error
        else:
            metadata.pop("final_answer_error", None)
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

        execution_notice = self._host._build_execution_notice(
            request.effective_mode,
            assistant_content,
            tool_events,
            requires_code_write=request.requires_code_write,
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
    *, model_content: str, model_provider_error: str,
    max_rounds_exceeded: bool, round_limit: int,
) -> str:
    """保留主模型原文；缺少正文时只显示实际中断或缺失事实。"""
    if model_content.strip():
        return model_content
    if model_provider_error:
        return f"模型服务错误：{model_provider_error}"
    if max_rounds_exceeded:
        return f"执行轮次预算已用完（{round_limit} 轮），模型未返回最终内容。"
    return "模型未返回最终内容。"


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
