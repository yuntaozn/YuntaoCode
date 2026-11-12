"""执行模型提出的一批工具调用。

批处理控制器管理协议顺序和执行账目，不选择工具，也不重新解释任务。
工具响应保留 Provider 调用顺序，只返回执行结果与协议错误事实。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

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

    def __init__(
        self,
        host: ToolExecutionHost,
        *,
        control_handler: Callable[..., Awaitable[dict[str, Any] | None]] | None = None,
    ) -> None:
        self._host = host
        self._control_handler = control_handler

    async def execute(
        self,
        *,
        tool_calls: list[dict[str, Any]],
        tool_name_map: dict[str, str],
        workspace_path: str,
        finish_reason: str,
        previous_tool_events: list[dict[str, Any]],
        state: ToolExecutionState,
    ) -> ToolExecutionBatchResult:
        next_state = state.copy()
        batch_events: list[dict[str, Any]] = []
        tool_messages: list[dict[str, Any]] = []

        for tool_call in tool_calls:
            await self._host._wait_if_paused()
            tool_id, arguments = self._host._tool_call_details(
                tool_call,
                tool_name_map,
            )
            if self._control_handler is not None:
                control_message = await self._control_handler(
                    tool_call, tool_id, arguments, finish_reason,
                )
                if control_message is not None:
                    tool_messages.append(control_message)
                    continue
            if finish_reason_indicates_truncation(finish_reason):
                tool_message, tool_event = self._host._skipped_tool_call(
                    tool_call,
                    tool_id,
                    arguments,
                    reason="truncated_tool_call",
                    message=(
                        "The model response stopped at its output limit while building "
                        "this tool call. The runtime did not execute incomplete arguments."
                    ),
                )
                batch_events.append(tool_event)
                tool_messages.append(tool_message)
                await self._publish({"event": "tool", **tool_event})
                if self._host._is_recoverable_write_failure(tool_id, tool_event):
                    next_state.write_repair_mode = True
                    await self._publish({
                        "event": "status",
                        "status": "write_repair_mode",
                        "message": "写入工具参数被截断，未执行该调用；已记录失败事实。",
                    })
                continue

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
                    await self._publish({
                        "event": "status", "status": "repeated_read_observed",
                        "tool": tool_id, "message": "已记录同一工具与范围的重复读取。",
                    })
                else:
                    next_state.seen_recon_signatures.add(signature)
                    next_state.recon_tool_count += 1

            if self._host._is_recoverable_write_failure(tool_id, tool_event):
                next_state.write_repair_mode = True
                await self._publish({
                    "event": "status",
                    "status": "write_repair_mode",
                    "message": "已记录写入工具失败；模型将收到原始工具结果。",
                })
            elif self._host._is_write_tool(tool_id) and tool_event.get("status") == "success":
                next_state.write_repair_mode = False

            if tool_id == "filesystem.read_file" and tool_event.get("status") == "success":
                next_state.read_file_ranges.append(
                    self._host._read_file_range_record(arguments, tool_event)
                )

            await self._publish({"event": "tool", **tool_event})

        self._host._set_active_tool_events([*previous_tool_events, *batch_events])
        return ToolExecutionBatchResult(
            tool_events=batch_events,
            model_messages=tool_messages,
            state=next_state,
        )

    async def _publish(self, payload: dict[str, Any]) -> None:
        self._host.write_event(payload)
        await self._host.flush()
