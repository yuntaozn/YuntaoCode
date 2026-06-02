from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.agent_strategy.classifiers import is_verification_tool, is_write_tool


RUN_RESULT_SCHEMA_VERSION = "0.1"


def build_run_result(
    *,
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    change_summary: dict[str, Any] | None,
    mode: str | None,
    requires_code_write: bool = False,
    contract_failed: bool = False,
    max_rounds_exceeded: bool = False,
) -> dict[str, Any]:
    """Build deterministic run facts from tool events.

    The model may still write the final prose answer, but this structure is the
    runtime-owned source of truth for what actually happened.
    """
    write_successes: list[dict[str, Any]] = []
    write_failures: list[dict[str, Any]] = []
    verification_successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for event in tool_events:
        tool_id = str(event.get("tool") or "")
        status = str(event.get("status") or "")
        if status == "failure":
            failures.append(_failure_record(workspace_path, event))
        if is_write_tool(tool_id):
            if status == "success":
                write_successes.append(event)
            elif status == "failure":
                write_failures.append(event)
        if is_verification_tool(tool_id, mode) and status == "success":
            verification_successes.append(event)

    written_paths = _unique(
        _event_path(workspace_path, event)
        for event in write_successes
    )
    changed_paths = _changed_paths(change_summary) or written_paths
    verified = [_verification_record(workspace_path, event) for event in verification_successes]
    verified = [item for item in verified if item]

    risks: list[str] = []
    if requires_code_write and not write_successes:
        risks.append("expected_write_not_observed")
    if write_successes and not verification_successes:
        risks.append("write_not_verified")
    if write_successes and write_failures:
        risks.append("partial_write_failure")
    if contract_failed:
        risks.append("execution_contract_failed")
    if max_rounds_exceeded:
        risks.append("max_rounds_exceeded")

    status = _result_status(
        has_tool_events=bool(tool_events),
        has_write_success=bool(write_successes),
        has_failure=bool(failures),
        has_partial_write=bool(write_successes and write_failures),
        contract_failed=contract_failed,
        max_rounds_exceeded=max_rounds_exceeded,
    )
    return {
        "schema_version": RUN_RESULT_SCHEMA_VERSION,
        "kind": "run_result",
        "status": status,
        "counts": {
            "tool_events": len(tool_events),
            "write_successes": len(write_successes),
            "write_failures": len(write_failures),
            "verification_successes": len(verification_successes),
            "failures": len(failures),
        },
        "changed_paths": changed_paths,
        "written_paths": written_paths,
        "verified": verified[:12],
        "failures": failures[:12],
        "risks": _unique(risks),
        "flags": {
            "requires_code_write": bool(requires_code_write),
            "contract_failed": bool(contract_failed),
            "max_rounds_exceeded": bool(max_rounds_exceeded),
        },
    }


def _result_status(
    *,
    has_tool_events: bool,
    has_write_success: bool,
    has_failure: bool,
    has_partial_write: bool,
    contract_failed: bool,
    max_rounds_exceeded: bool,
) -> str:
    if contract_failed:
        return "failure"
    if max_rounds_exceeded:
        return "stopped"
    if has_partial_write:
        return "partial"
    if has_failure:
        return "failure"
    if has_write_success or has_tool_events:
        return "success"
    return "no_tool_activity"


def _changed_paths(change_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(change_summary, dict):
        return []
    paths: list[str] = []
    for item in change_summary.get("files") or []:
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]))
    return _unique(paths)


def _failure_record(workspace_path: str, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": str(event.get("tool") or ""),
        "path": _event_path(workspace_path, event),
        "error": str(event.get("error") or "")[:500],
    }


def _verification_record(workspace_path: str, event: dict[str, Any]) -> dict[str, Any]:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    record = {
        "tool": str(event.get("tool") or ""),
        "path": _event_path(workspace_path, event),
    }
    if event_input.get("query"):
        record["query"] = str(event_input["query"])
    return record


def _event_path(workspace_path: str, event: dict[str, Any]) -> str:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    value = (
        output.get("path")
        or output.get("output_path")
        or event_input.get("output_path")
        or event_input.get("path")
        or ""
    )
    if not value:
        return ""
    return _relative_workspace_path(workspace_path, str(value))


def _relative_workspace_path(workspace_path: str, value: str) -> str:
    normalized_workspace = workspace_path.replace("\\", "/").rstrip("/")
    normalized_value = value.replace("\\", "/")
    if normalized_workspace:
        workspace_prefix = normalized_workspace.lower() + "/"
        value_lower = normalized_value.lower()
        if value_lower == normalized_workspace.lower():
            return "."
        if value_lower.startswith(workspace_prefix):
            return normalized_value[len(normalized_workspace) + 1:]
    try:
        workspace = Path(workspace_path).resolve()
        path = Path(value)
        if not path.is_absolute():
            return str(path).replace("\\", "/")
        return str(path.resolve().relative_to(workspace)).replace("\\", "/")
    except (OSError, ValueError):
        return value.replace("\\", "/")


def _unique(values: Any) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
