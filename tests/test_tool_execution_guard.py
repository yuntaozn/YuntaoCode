from __future__ import annotations

from typing import Any

import pytest

from runtime.agent_strategy.tool_execution_guard import (
    ToolExecutionGuardChecks,
    evaluate_tool_execution_guard,
)


def _checks(
    *,
    enabled: bool = True,
    available: bool = True,
    missing_fields: list[str] | None = None,
    ai_draft_message: str = "",
    calls: list[str] | None = None,
) -> ToolExecutionGuardChecks:
    call_log = calls if calls is not None else []

    def is_tool_enabled(tool_id: str) -> bool:
        call_log.append("enabled")
        return enabled

    def is_tool_available(tool_id: str) -> bool:
        call_log.append("available")
        return available

    def missing_required_input_fields(tool_id: str, arguments: dict[str, Any]) -> list[str]:
        call_log.append("missing")
        return list(missing_fields or [])


    def ai_plugin_draft_workspace_message(
        tool_id: str,
        arguments: dict[str, Any],
        workspace_path: str | None,
    ) -> str:
        call_log.append("ai_draft")
        return ai_draft_message


    return ToolExecutionGuardChecks(
        is_tool_enabled=is_tool_enabled,
        is_tool_available=is_tool_available,
        missing_required_input_fields=missing_required_input_fields,
        ai_plugin_draft_workspace_message=ai_plugin_draft_workspace_message,
    )


def test_tool_execution_guard_allows_clean_tool_call() -> None:
    calls: list[str] = []

    decision = evaluate_tool_execution_guard(
        "filesystem.write_file",
        {"path": "demo.txt", "content": "ok"},
        ".",
        _checks(calls=calls),
    )

    assert decision is None
    assert calls == [
        "enabled",
        "available",
        "missing",
        "ai_draft",
    ]


def test_tool_execution_guard_reports_missing_required_fields() -> None:
    decision = evaluate_tool_execution_guard(
        "filesystem.write_file",
        {"content": "ok"},
        ".",
        _checks(missing_fields=["path"]),
    )

    assert decision is not None
    assert decision.reason == "invalid_tool_input"
    assert "path" in decision.message
    assert "本次调用没有执行" in decision.message


@pytest.mark.parametrize("settings,reason,expected_calls", [
    ({"enabled": False}, "plugin_disabled", ["enabled"]),
    ({"available": False}, "capability_service_unavailable", ["enabled", "available"]),
    ({"ai_draft_message": "reserved draft path"}, "ai_plugin_draft_workspace_guard", ["enabled", "available", "missing", "ai_draft"]),
])
def test_execution_boundaries_still_reject_before_confirmation(settings, reason, expected_calls):
    calls = []
    decision = evaluate_tool_execution_guard(
        "filesystem.write_file", {"path": "ai-plugins/draft.py"}, ".",
        _checks(**settings, calls=calls),
    )
    assert decision.reason == reason
    assert calls == expected_calls
