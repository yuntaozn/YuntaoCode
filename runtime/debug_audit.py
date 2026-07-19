"""Read-only runtime debug audit summaries.

DebugAudit summarizes command/process/service evidence such as shell commands,
dependency installation attempts, preview services, timeouts, stderr, and
diagnostics. It is evidence-only: it must not decide task intent, select tools,
block execution, or mark a run complete.
"""

from __future__ import annotations

from typing import Any


DEBUG_AUDIT_SCHEMA_VERSION = "debug_audit.v1"
LONG_SESSION_SECONDS = 60.0

INSTALL_COMMAND_MARKERS = (
    " pip install",
    " python -m pip install",
    " playwright install",
    " npm install",
    " npm i ",
    " pnpm install",
    " yarn install",
    " bun install",
    " uv pip install",
    " conda install",
)
PREVIEW_SOURCE_MARKERS = ("preview.", "web.capture_page", "browser_preview")
PORT_COMMAND_MARKERS = (
    "netstat",
    "lsof",
    "get-nettcpconnection",
    "test-netconnection",
    "nc ",
    "curl ",
)
PROCESS_COMMAND_MARKERS = (
    "tasklist",
    "get-process",
    "ps ",
    "wmic process",
)


def build_debug_audit(
    *,
    debug_sessions: list[dict[str, Any]] | None = None,
    result_status: str = "",
    risks: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return a compact debug audit summary from debug-session records."""

    records = [_compact_debug_record(item) for item in debug_sessions or [] if isinstance(item, dict)]
    records = [item for item in records if item.get("kind") == "debug_session"]
    install_sessions = [item for item in records if item.get("role") == "dependency_install"]
    preview_sessions = [item for item in records if item.get("role") == "preview_service"]
    port_checks = [item for item in records if item.get("role") == "port_check"]
    process_checks = [item for item in records if item.get("role") == "process_check"]
    service_sessions = [item for item in records if item.get("service")]
    timed_out_sessions = [item for item in records if item.get("timed_out")]
    failed_sessions = [item for item in records if item.get("status") in {"failed", "timed_out"}]
    warning_sessions = [item for item in records if item.get("status") == "warning"]
    runtime_error_sessions = [item for item in records if item.get("has_runtime_errors")]
    long_sessions = [
        item for item in records
        if _safe_float(item.get("duration_seconds"), 0.0) >= LONG_SESSION_SECONDS
    ]
    diagnostic_count = sum(_safe_int(item.get("diagnostic_count"), 0) for item in records)
    stdout_chars = sum(_safe_int(item.get("stdout_chars"), 0) for item in records)
    stderr_chars = sum(_safe_int(item.get("stderr_chars"), 0) for item in records)
    truncated_streams = [
        item for item in records
        if item.get("stdout_truncated") or item.get("stderr_truncated")
    ]

    return {
        "schema_version": DEBUG_AUDIT_SCHEMA_VERSION,
        "kind": "debug_audit",
        "boundary": "evidence_only",
        "result_status": str(result_status or ""),
        "counts": {
            "debug_sessions": len(records),
            "dependency_install_sessions": len(install_sessions),
            "preview_sessions": len(preview_sessions),
            "service_sessions": len(service_sessions),
            "port_checks": len(port_checks),
            "process_checks": len(process_checks),
            "timed_out_sessions": len(timed_out_sessions),
            "failed_sessions": len(failed_sessions),
            "warning_sessions": len(warning_sessions),
            "runtime_error_sessions": len(runtime_error_sessions),
            "long_sessions": len(long_sessions),
            "diagnostics": diagnostic_count,
            "stdout_chars": stdout_chars,
            "stderr_chars": stderr_chars,
            "truncated_streams": len(truncated_streams),
        },
        "flags": {
            "has_debug_evidence": bool(records),
            "has_dependency_install": bool(install_sessions),
            "has_preview_service": bool(preview_sessions),
            "has_service_evidence": bool(service_sessions),
            "has_port_or_process_check": bool(port_checks or process_checks),
            "has_timeout": bool(timed_out_sessions),
            "has_failure": bool(failed_sessions),
            "has_warning": bool(warning_sessions),
            "has_runtime_errors": bool(runtime_error_sessions),
            "has_long_session": bool(long_sessions),
            "has_truncated_streams": bool(truncated_streams),
        },
        "risk_codes": _unique(risks)[:16],
        "records": records[-16:],
        "dependency_install_sessions": install_sessions[-8:],
        "preview_sessions": preview_sessions[-8:],
        "service_sessions": service_sessions[-8:],
        "long_sessions": long_sessions[-8:],
        "problem_sessions": [*failed_sessions, *warning_sessions, *timed_out_sessions][-12:],
    }


def _compact_debug_record(item: dict[str, Any]) -> dict[str, Any]:
    command = str(item.get("command") or "")
    source_type = str(item.get("source_type") or "")
    role = _debug_role(command=command, source_type=source_type, service=item.get("service"))
    kind = str(item.get("kind") or "")
    if not kind and _looks_like_debug_session_record(item):
        kind = "debug_session"
    return {
        "schema_version": str(item.get("schema_version") or ""),
        "kind": kind,
        "tool": str(item.get("tool") or ""),
        "source_type": source_type,
        "role": role,
        "command": command,
        "executable": str(item.get("executable") or ""),
        "cwd": str(item.get("cwd") or ""),
        "pid": item.get("pid"),
        "exit_code": item.get("exit_code"),
        "timed_out": bool(item.get("timed_out")),
        "timeout": item.get("timeout"),
        "started_at": str(item.get("started_at") or ""),
        "finished_at": str(item.get("finished_at") or ""),
        "duration_seconds": item.get("duration_seconds"),
        "stdout_chars": _safe_int(item.get("stdout_chars"), 0),
        "stderr_chars": _safe_int(item.get("stderr_chars"), 0),
        "stdout_truncated": bool(item.get("stdout_truncated")),
        "stderr_truncated": bool(item.get("stderr_truncated")),
        "service": item.get("service") if isinstance(item.get("service"), dict) else {},
        "diagnostic_count": _safe_int(item.get("diagnostic_count"), 0),
        "heartbeat": item.get("heartbeat") if isinstance(item.get("heartbeat"), dict) else {},
        "status": str(item.get("status") or ""),
        "has_runtime_errors": bool(item.get("has_runtime_errors")),
    }


def _debug_role(*, command: str, source_type: str, service: Any) -> str:
    normalized_command = f" {str(command or '').strip().lower()} "
    normalized_source = str(source_type or "").strip().lower()
    service_kind = ""
    if isinstance(service, dict):
        service_kind = str(service.get("kind") or service.get("type") or "").strip().lower()
    if any(marker in normalized_command for marker in INSTALL_COMMAND_MARKERS):
        return "dependency_install"
    if normalized_source.startswith(PREVIEW_SOURCE_MARKERS) or service_kind == "browser_preview":
        return "preview_service"
    if any(marker in normalized_command for marker in PORT_COMMAND_MARKERS):
        return "port_check"
    if any(marker in normalized_command for marker in PROCESS_COMMAND_MARKERS):
        return "process_check"
    if service_kind:
        return "service"
    return "command"


def _looks_like_debug_session_record(item: dict[str, Any]) -> bool:
    return any(
        key in item
        for key in (
            "command",
            "source_type",
            "executable",
            "exit_code",
            "timed_out",
            "stdout_chars",
            "stderr_chars",
            "diagnostic_count",
            "has_runtime_errors",
        )
    )


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _safe_int(value: Any, fallback: int) -> int:
    try:
        if value is None or value == "":
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any, fallback: float) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback
