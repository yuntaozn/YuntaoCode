from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolExecutionGuardDecision:
    reason: str
    message: str


@dataclass(frozen=True)
class ToolExecutionGuardChecks:
    is_tool_enabled: Callable[[str], bool]
    is_tool_available: Callable[[str], bool]
    missing_required_input_fields: Callable[[str, dict[str, Any]], Sequence[str]]
    ai_plugin_draft_workspace_message: Callable[[str, dict[str, Any], str | None], str]


def evaluate_tool_execution_guard(
    tool_id: str,
    arguments: dict[str, Any],
    workspace_path: str | None,
    checks: ToolExecutionGuardChecks,
) -> ToolExecutionGuardDecision | None:
    """返回已解析工具的第一个执行前 Guard 决策。

    只检查可用性、必填参数和能力草稿写入边界，不评价模型选择的执行路线；
    无效调用绝不进入用户确认。"""
    if not checks.is_tool_enabled(tool_id):
        return ToolExecutionGuardDecision(
            reason="plugin_disabled",
            message=f"插件已禁用，不能调用工具：{tool_id}",
        )

    if not checks.is_tool_available(tool_id):
        return ToolExecutionGuardDecision(
            reason="capability_service_unavailable",
            message=f"能力服务尚未连接，不能调用工具：{tool_id}",
        )

    missing_fields = list(checks.missing_required_input_fields(tool_id, arguments))
    if missing_fields:
        return ToolExecutionGuardDecision(
            reason="invalid_tool_input",
            message=(
                f"工具调用缺少必填参数：{', '.join(missing_fields)}。"
                "本次调用没有执行。"
            ),
        )

    guard_message = checks.ai_plugin_draft_workspace_message(tool_id, arguments, workspace_path)
    if guard_message:
        return ToolExecutionGuardDecision(
            reason="ai_plugin_draft_workspace_guard",
            message=guard_message,
        )

    return None
