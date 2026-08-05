"""执行模型提出的一批工具调用。

批处理控制器管理协议顺序和执行账目，不选择工具，也不重新解释任务。
运行时建议之前始终先把工具响应返回模型，使 Provider 工具调用协议保持有效，
即使写入操作需要修复提示也不例外。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from runtime.agent_strategy.classifiers import finish_reason_indicates_truncation


class ToolExecutionHost(Protocol):
    async def _wait_if_paused(self) -> None: ...

    def _tool_call_details(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
    ) -> tuple[str, dict[str, Any]]: ...

    def _skipped_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_id: str,
        arguments: dict[str, Any],
        *,
        reason: str,
        message: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...

    def _is_recoverable_write_failure(
        self,
        tool_id: str,
        event: dict[str, Any],
    ) -> bool: ...

    def _write_repair_prompt(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        event: dict[str, Any],
        workspace_path: str,
    ) -> str: ...

    def _mark_next_plan_step_running(
        self,
        execution_plan: dict[str, Any] | None,
        tool_call: dict[str, Any],
    ) -> int | None: ...

    def _finish_plan_step(
        self,
        execution_plan: dict[str, Any],
        step_index: int,
        tool_event: dict[str, Any],
    ) -> None: ...

    def _set_active_tool_events(self, tool_events: list[dict[str, Any]]) -> None: ...

    def _is_recon_tool(self, tool_id: str) -> bool: ...

    def _tool_signature(self, tool_id: str, arguments: dict[str, Any]) -> str: ...

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
        workspace_path: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...

    def _is_write_tool(self, tool_id: str) -> bool: ...

    def _read_file_range_record(
        self,
        arguments: dict[str, Any],
        tool_event: dict[str, Any],
    ) -> dict[str, Any]: ...

    def write_event(self, payload: dict[str, Any]) -> None: ...

    async def flush(self, include_footers: bool = False) -> None: ...


@dataclass
class ToolExecutionState:
    seen_recon_signatures: set[str] = field(default_factory=set)
    recon_tool_count: int = 0
    write_repair_mode: bool = False
    read_file_ranges: list[dict[str, Any]] = field(default_factory=list)

    def copy(self) -> "ToolExecutionState":
        return ToolExecutionState(
            seen_recon_signatures=set(self.seen_recon_signatures),
            recon_tool_count=self.recon_tool_count,
            write_repair_mode=self.write_repair_mode,
            read_file_ranges=list(self.read_file_ranges),
        )


@dataclass
class ToolExecutionBatchResult:
    tool_events: list[dict[str, Any]]
    model_messages: list[dict[str, Any]]
    state: ToolExecutionState


class ToolExecutionBatch:
    """在保持协议不变量的同时执行模型选中的可见工具。"""

    def __init__(self, host: ToolExecutionHost) -> None:
        self._host = host

    async def execute(
        self,
        *,
        tool_calls: list[dict[str, Any]],
        tool_name_map: dict[str, str],
        workspace_path: str,
        execution_plan: dict[str, Any] | None,
        finish_reason: str,
        previous_tool_events: list[dict[str, Any]],
        state: ToolExecutionState,
    ) -> ToolExecutionBatchResult:
        next_state = state.copy()
        batch_events: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []
        advisories: list[dict[str, Any]] = []

        for tool_call in tool_calls:
            await self._host._wait_if_paused()
            tool_id, arguments = self._host._tool_call_details(
                tool_call,
                tool_name_map,
            )
            if finish_reason_indicates_truncation(finish_reason):
                tool_message, tool_event = self._host._skipped_tool_call(
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
                batch_events.append(tool_event)
                tool_messages.append(tool_message)
                await self._publish({"event": "tool", **tool_event})
                if self._host._is_recoverable_write_failure(tool_id, tool_event):
                    next_state.write_repair_mode = True
                    advisories.append({
                        "role": "system",
                        "content": self._host._write_repair_prompt(
                            tool_id,
                            arguments,
                            tool_event,
                            workspace_path,
                        ),
                    })
                    await self._publish({
                        "event": "status",
                        "status": "write_repair_mode",
                        "message": "写入工具参数被截断，正在要求模型换成更小步的写入策略。",
                    })
                continue

            plan_step_index = self._host._mark_next_plan_step_running(
                execution_plan,
                tool_call,
            )
            if plan_step_index is not None and execution_plan:
                await self._publish({
                    "event": "plan_step",
                    "index": plan_step_index,
                    "step": execution_plan["steps"][plan_step_index],
                })

            active_events = [*previous_tool_events, *batch_events]
            self._host._set_active_tool_events(active_events)
            duplicate_recon = False
            if self._host._is_recon_tool(tool_id) and not next_state.write_repair_mode:
                signature = self._host._tool_signature(tool_id, arguments)
                duplicate_recon = signature in next_state.seen_recon_signatures
            else:
                signature = ""

            tool_message, tool_event = await self._host._execute_tool_call(
                tool_call,
                tool_name_map,
                workspace_path,
            )
            batch_events.append(tool_event)
            tool_messages.append(tool_message)
            self._host._set_active_tool_events([*previous_tool_events, *batch_events])

            if (
                signature
                and tool_event.get("status") == "success"
                and arguments.get("path")
            ):
                if duplicate_recon:
                    advisories.append({
                        "role": "system",
                        "content": (
                            "Runtime observation only. The latest read/search repeats "
                            "the same tool and range as an earlier call. Decide whether "
                            "that evidence is already enough, whether a different range "
                            "is needed, or whether the task should move to another step."
                        ),
                    })
                else:
                    next_state.seen_recon_signatures.add(signature)
                    next_state.recon_tool_count += 1

            if self._host._is_recoverable_write_failure(tool_id, tool_event):
                next_state.write_repair_mode = True
                advisories.append({
                    "role": "system",
                    "content": self._host._write_repair_prompt(
                        tool_id,
                        arguments,
                        tool_event,
                        workspace_path,
                    ),
                })
                await self._publish({
                    "event": "status",
                    "status": "write_repair_mode",
                    "message": "写入工具失败，已把失败事实反馈给模型自行选择修复策略。",
                })
            elif self._host._is_write_tool(tool_id) and tool_event.get("status") == "success":
                next_state.write_repair_mode = False

            if tool_id == "filesystem.read_file" and tool_event.get("status") == "success":
                next_state.read_file_ranges.append(
                    self._host._read_file_range_record(arguments, tool_event)
                )

            await self._publish({"event": "tool", **tool_event})
            if plan_step_index is not None and execution_plan:
                self._host._finish_plan_step(
                    execution_plan,
                    plan_step_index,
                    tool_event,
                )
                await self._publish({
                    "event": "plan_step",
                    "index": plan_step_index,
                    "step": execution_plan["steps"][plan_step_index],
                })

        self._host._set_active_tool_events([*previous_tool_events, *batch_events])
        return ToolExecutionBatchResult(
            tool_events=batch_events,
            model_messages=[*tool_messages, *advisories],
            state=next_state,
        )

    async def _publish(self, payload: dict[str, Any]) -> None:
        self._host.write_event(payload)
        await self._host.flush()
