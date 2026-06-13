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
    capability_fallback_message: Callable[[str], str]
    ai_plugin_draft_workspace_message: Callable[[str, dict[str, Any], str | None], str]
    document_contract_message: Callable[[str, dict[str, Any]], str]
    verification_runtime_message: Callable[[str, dict[str, Any]], str]


def evaluate_tool_execution_guard(
    tool_id: str,
    arguments: dict[str, Any],
    workspace_path: str | None,
    checks: ToolExecutionGuardChecks,
) -> ToolExecutionGuardDecision | None:
    """Return the first pre-execution guard decision for a resolved tool.

    The order is part of the runtime contract. Availability and capability
    boundaries are checked before schema details, and invalid calls never enter
    user confirmation.
    """
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

    guard_message = checks.capability_fallback_message(tool_id)
    if guard_message:
        return ToolExecutionGuardDecision(
            reason="capability_fallback_blocked",
            message=guard_message,
        )

    missing_fields = list(checks.missing_required_input_fields(tool_id, arguments))
    if missing_fields:
        return ToolExecutionGuardDecision(
            reason="invalid_tool_input",
            message=(
                f"工具调用缺少必填参数：{', '.join(missing_fields)}。"
                "请补全参数后重新发送结构化工具调用；无效调用不会进入人工确认。"
            ),
        )

    guard_message = checks.ai_plugin_draft_workspace_message(tool_id, arguments, workspace_path)
    if guard_message:
        return ToolExecutionGuardDecision(
            reason="ai_plugin_draft_workspace_guard",
            message=guard_message,
        )

    guard_message = checks.document_contract_message(tool_id, arguments)
    if guard_message:
        return ToolExecutionGuardDecision(
            reason="document_contract_guard",
            message=guard_message,
        )

    guard_message = checks.verification_runtime_message(tool_id, arguments)
    if guard_message:
        return ToolExecutionGuardDecision(
            reason="invalid_verification_method",
            message=guard_message,
        )

    return None
