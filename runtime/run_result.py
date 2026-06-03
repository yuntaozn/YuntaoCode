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
    expected_document_coverage: bool = False,
    contract_failed: bool = False,
    max_rounds_exceeded: bool = False,
) -> dict[str, Any]:
    """Build deterministic run facts from tool events.

    The model may still write the final prose answer, but this structure is the
    runtime-owned source of truth for what actually happened.
    """
    write_successes: list[dict[str, Any]] = []
    write_partials: list[dict[str, Any]] = []
    write_failures: list[dict[str, Any]] = []
    verification_successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    effective_statuses: list[str] = []

    for event in tool_events:
        tool_id = str(event.get("tool") or "")
        status = _effective_event_status(tool_id, event)
        effective_statuses.append(status)
        if status == "failure":
            failures.append(_failure_record(workspace_path, event))
        if is_write_tool(tool_id):
            if status == "success":
                write_successes.append(event)
            elif status == "partial":
                write_successes.append(event)
                write_partials.append(event)
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
    if write_partials:
        risks.append("partial_write_resumable")
    if contract_failed:
        risks.append("execution_contract_failed")
    if max_rounds_exceeded:
        risks.append("max_rounds_exceeded")
    if failures and _failures_recovered(
        tool_events,
        effective_statuses,
        write_failures=write_failures,
    ):
        risks.append("recovered_tool_failure")

    coverage_failure = _document_coverage_failure(
        workspace_path,
        tool_events,
        expected_document_coverage=expected_document_coverage,
    )
    if coverage_failure:
        failures.append(coverage_failure)
        risks.append("document_output_coverage_low")

    status = _result_status(
        has_tool_events=bool(tool_events),
        has_write_success=bool(write_successes),
        has_failure=bool(failures) and "recovered_tool_failure" not in risks,
        has_partial_write=bool(write_successes and write_failures),
        has_partial_resumable=bool(write_partials),
        has_document_coverage_failure=bool(coverage_failure),
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
            "write_partials": len(write_partials),
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
            "expected_document_coverage": bool(expected_document_coverage),
        },
    }


def _result_status(
    *,
    has_tool_events: bool,
    has_write_success: bool,
    has_failure: bool,
    has_partial_write: bool,
    has_partial_resumable: bool,
    has_document_coverage_failure: bool,
    contract_failed: bool,
    max_rounds_exceeded: bool,
) -> str:
    if contract_failed:
        return "failure"
    if max_rounds_exceeded:
        return "stopped"
    if has_document_coverage_failure:
        return "partial"
    if has_partial_resumable:
        return "partial"
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
        "error": _event_failure_message(event)[:500],
    }


def _effective_event_status(tool_id: str, event: dict[str, Any]) -> str:
    status = str(event.get("status") or "")
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if tool_id == "shell.run_command":
        try:
            exit_code = int(output.get("exit_code", 0) or 0)
        except (TypeError, ValueError):
            exit_code = 0
        if exit_code != 0:
            return "failure"
    if output.get("error") is True:
        return "failure"
    output_status = str(output.get("status") or "").strip().lower()
    if status == "partial" or output_status in {"partial", "partial_resumable"} or output.get("partial_resumable") is True:
        return "partial"
    return status


def _event_failure_message(event: dict[str, Any]) -> str:
    error = str(event.get("error") or "").strip()
    if error:
        return error
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    stderr = str(output.get("stderr") or "").strip()
    stdout = str(output.get("stdout") or "").strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    if output.get("exit_code") is not None:
        return f"exit_code={output.get('exit_code')}"
    return ""


def _failures_recovered(
    tool_events: list[dict[str, Any]],
    effective_statuses: list[str],
    *,
    write_failures: list[dict[str, Any]],
) -> bool:
    if write_failures:
        return False
    failure_indexes = [index for index, status in enumerate(effective_statuses) if status == "failure"]
    if not failure_indexes:
        return False
    last_failure = max(failure_indexes)
    return any(
        effective_statuses[index] == "success"
        and _event_indicates_progress(tool_events[index])
        for index in range(last_failure + 1, len(tool_events))
    )


def _event_indicates_progress(event: dict[str, Any]) -> bool:
    tool_id = str(event.get("tool") or "")
    if is_write_tool(tool_id):
        return True
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if tool_id == "shell.run_command":
        try:
            return int(output.get("exit_code", 0) or 0) == 0
        except (TypeError, ValueError):
            return False
    return False


def _document_coverage_failure(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    *,
    expected_document_coverage: bool,
) -> dict[str, Any] | None:
    if not expected_document_coverage:
        return None

    source_paragraphs = 0
    source_chars = 0
    for event in tool_events:
        if str(event.get("tool") or "") != "document.extract_docx_outline":
            continue
        if _effective_event_status("document.extract_docx_outline", event) != "success":
            continue
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        source_paragraphs = max(source_paragraphs, _safe_int(output.get("paragraph_count")))
        source_chars = max(source_chars, _safe_int(output.get("text_chars")))

    if source_paragraphs < 50 and source_chars < 20000:
        return None

    best_export: dict[str, Any] | None = None
    best_ratio = 0.0
    for event in tool_events:
        if str(event.get("tool") or "") != "document.export_docx":
            continue
        if _effective_event_status("document.export_docx", event) != "success":
            continue
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        out_paragraphs = max(
            _safe_int(output.get("nonempty_paragraph_count")),
            _safe_int(output.get("paragraph_count")),
        )
        out_chars = _safe_int(output.get("content_chars"))
        ratios: list[float] = []
        if source_paragraphs:
            ratios.append(out_paragraphs / max(source_paragraphs, 1))
        if source_chars:
            ratios.append(out_chars / max(source_chars, 1))
        ratio = max(ratios) if ratios else 0.0
        if best_export is None or ratio > best_ratio:
            best_export = event
            best_ratio = ratio

    if best_export is None or best_ratio >= 0.25:
        return None

    output = best_export.get("output") if isinstance(best_export.get("output"), dict) else {}
    out_paragraphs = max(
        _safe_int(output.get("nonempty_paragraph_count")),
        _safe_int(output.get("paragraph_count")),
    )
    out_chars = _safe_int(output.get("content_chars"))
    return {
        "tool": "document.export_docx",
        "path": _event_path(workspace_path, best_export),
        "error": (
            "document output coverage is too low: "
            f"source_paragraphs={source_paragraphs}, output_paragraphs={out_paragraphs}, "
            f"source_chars={source_chars}, output_chars={out_chars}"
        ),
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
