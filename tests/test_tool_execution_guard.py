from __future__ import annotations

from typing import Any

from runtime.agent_strategy.tool_execution_guard import (
    ToolExecutionGuardChecks,
    evaluate_tool_execution_guard,
)


def _checks(
    *,
    enabled: bool = True,
    available: bool = True,
    missing_fields: list[str] | None = None,
    capability_message: str = "",
    ai_draft_message: str = "",
    document_message: str = "",
    verification_message: str = "",
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

    def capability_fallback_message(tool_id: str) -> str:
        call_log.append("capability")
        return capability_message

    def ai_plugin_draft_workspace_message(
        tool_id: str,
        arguments: dict[str, Any],
        workspace_path: str | None,
    ) -> str:
        call_log.append("ai_draft")
        return ai_draft_message

    def document_contract_message(tool_id: str, arguments: dict[str, Any]) -> str:
        call_log.append("document")
        return document_message

    def verification_runtime_message(tool_id: str, arguments: dict[str, Any]) -> str:
        call_log.append("verification")
        return verification_message

    return ToolExecutionGuardChecks(
        is_tool_enabled=is_tool_enabled,
        is_tool_available=is_tool_available,
        missing_required_input_fields=missing_required_input_fields,
        capability_fallback_message=capability_fallback_message,
        ai_plugin_draft_workspace_message=ai_plugin_draft_workspace_message,
        document_contract_message=document_contract_message,
        verification_runtime_message=verification_runtime_message,
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
        "capability",
        "ai_draft",
        "document",
        "verification",
    ]


def test_tool_execution_guard_reports_capability_boundary_as_advisory_after_schema() -> None:
    calls: list[str] = []

    decision = evaluate_tool_execution_guard(
        "shell.run_command",
        {"command": "python"},
        ".",
        _checks(
            capability_message="outside capability boundary",
            calls=calls,
        ),
    )

    assert decision is not None
    assert decision.reason == "capability_fallback_advisory"
    assert decision.blocking is False
    assert decision.message == "outside capability boundary"
    assert calls == ["enabled", "available", "missing", "capability"]


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


def test_tool_execution_guard_reports_document_and_verification_messages() -> None:
    document_decision = evaluate_tool_execution_guard(
        "filesystem.write_file",
        {"path": "translate.py"},
        ".",
        _checks(document_message="use document.translate_docx"),
    )
    verification_decision = evaluate_tool_execution_guard(
        "shell.run_command",
        {"command": "npm run dev"},
        ".",
        _checks(verification_message="long running service cannot verify"),
    )

    assert document_decision is not None
    assert document_decision.reason == "document_contract_advisory"
    assert document_decision.blocking is False
    assert verification_decision is not None
    assert verification_decision.reason == "verification_runtime_advisory"
    assert verification_decision.blocking is False
