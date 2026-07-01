"""Shared debug-session evidence contracts for runtime tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


DEBUG_SESSION_SCHEMA_VERSION = "debug_session.v1"


def build_debug_session(
    *,
    source_type: str,
    command: str = "",
    executable: str = "",
    args: list[Any] | None = None,
    cwd: str = "",
    pid: int | None = None,
    exit_code: int | None = None,
    timed_out: bool = False,
    timeout: int | None = None,
    stdout: str = "",
    stderr: str = "",
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    diagnostics: list[dict[str, Any]] | None = None,
    service: dict[str, Any] | None = None,
    started_at: str = "",
    finished_at: str = "",
    duration_seconds: float | None = None,
    heartbeat: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable, advisory debug-session evidence record."""

    status = _status(exit_code=exit_code, timed_out=timed_out, stderr=stderr)
    return {
        "schema_version": DEBUG_SESSION_SCHEMA_VERSION,
        "kind": "debug_session",
        "source": {
            "type": str(source_type or "").strip() or "tool",
        },
        "command": {
            "display": str(command or ""),
            "executable": str(executable or ""),
            "args": [str(item) for item in (args or [])],
            "cwd": str(cwd or ""),
        },
        "process": {
            "pid": pid,
            "exit_code": exit_code,
            "timed_out": bool(timed_out),
            "timeout": timeout,
            "started_at": started_at or _utc_now_iso(),
            "finished_at": finished_at or "",
            "duration_seconds": duration_seconds,
        },
        "streams": {
            "stdout_preview": str(stdout or "")[:4000],
            "stderr_preview": str(stderr or "")[:2000],
            "stdout_chars": len(str(stdout or "")),
            "stderr_chars": len(str(stderr or "")),
            "stdout_truncated": bool(stdout_truncated),
            "stderr_truncated": bool(stderr_truncated),
        },
        "service": service or {},
        "diagnostics": (diagnostics or [])[:10],
        "heartbeat": heartbeat or {},
        "health": {
            "status": status,
            "has_runtime_errors": status != "success",
        },
    }


def normalize_debug_session(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return debug-session evidence from nested or legacy shell-like fields."""

    if not isinstance(output, dict):
        return None
    existing = output.get("debug_session")
    if isinstance(existing, dict) and existing.get("kind") == "debug_session":
        return existing
    if not _looks_like_debug_output(output):
        return None
    return build_debug_session(
        source_type=str(output.get("type") or "tool"),
        command=str(output.get("display_command") or output.get("command") or ""),
        executable=str(output.get("executable") or ""),
        args=output.get("args") if isinstance(output.get("args"), list) else [],
        cwd=str(output.get("cwd") or ""),
        pid=_optional_int(output.get("pid")),
        exit_code=_optional_int(output.get("exit_code")),
        timed_out=bool(output.get("timed_out")),
        timeout=_optional_int(output.get("timeout")),
        stdout=str(output.get("stdout") or ""),
        stderr=str(output.get("stderr") or ""),
        stdout_truncated=bool(output.get("stdout_truncated")),
        stderr_truncated=bool(output.get("stderr_truncated")),
        diagnostics=output.get("diagnostics") if isinstance(output.get("diagnostics"), list) else [],
        service=output.get("service") if isinstance(output.get("service"), dict) else {},
    )


def debug_session_summary(session: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a compact summary suitable for RunResult and model context."""

    if not isinstance(session, dict):
        return None
    if _is_debug_session_summary(session):
        return {
            "schema_version": session.get("schema_version") or DEBUG_SESSION_SCHEMA_VERSION,
            "kind": "debug_session",
            "source_type": session.get("source_type"),
            "command": session.get("command"),
            "executable": session.get("executable"),
            "cwd": session.get("cwd"),
            "pid": _optional_int(session.get("pid")),
            "exit_code": _optional_int(session.get("exit_code")),
            "timed_out": bool(session.get("timed_out")),
            "timeout": _optional_int(session.get("timeout")),
            "duration_seconds": _optional_float(session.get("duration_seconds")),
            "stdout_chars": _optional_int(session.get("stdout_chars")),
            "stderr_chars": _optional_int(session.get("stderr_chars")),
            "stdout_truncated": bool(session.get("stdout_truncated")),
            "stderr_truncated": bool(session.get("stderr_truncated")),
            "service": session.get("service") if isinstance(session.get("service"), dict) else {},
            "diagnostic_count": _optional_int(session.get("diagnostic_count")) or 0,
            "status": session.get("status"),
            "has_runtime_errors": bool(session.get("has_runtime_errors")),
        }
    command = session.get("command") if isinstance(session.get("command"), dict) else {}
    process = session.get("process") if isinstance(session.get("process"), dict) else {}
    streams = session.get("streams") if isinstance(session.get("streams"), dict) else {}
    service = session.get("service") if isinstance(session.get("service"), dict) else {}
    health = session.get("health") if isinstance(session.get("health"), dict) else {}
    return {
        "schema_version": session.get("schema_version") or DEBUG_SESSION_SCHEMA_VERSION,
        "kind": "debug_session",
        "source_type": (session.get("source") or {}).get("type")
        if isinstance(session.get("source"), dict)
        else "",
        "command": command.get("display"),
        "executable": command.get("executable"),
        "cwd": command.get("cwd"),
        "pid": process.get("pid"),
        "exit_code": process.get("exit_code"),
        "timed_out": bool(process.get("timed_out")),
        "timeout": process.get("timeout"),
        "duration_seconds": process.get("duration_seconds"),
        "stdout_chars": streams.get("stdout_chars"),
        "stderr_chars": streams.get("stderr_chars"),
        "stdout_truncated": bool(streams.get("stdout_truncated")),
        "stderr_truncated": bool(streams.get("stderr_truncated")),
        "service": service,
        "diagnostic_count": len(session.get("diagnostics") or []),
        "status": health.get("status"),
        "has_runtime_errors": bool(health.get("has_runtime_errors")),
    }


def _is_debug_session_summary(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "source_type",
            "executable",
            "cwd",
            "stdout_chars",
            "diagnostic_count",
        )
    )


def _status(*, exit_code: int | None, timed_out: bool, stderr: str) -> str:
    if timed_out:
        return "timed_out"
    if exit_code is not None and exit_code != 0:
        return "failed"
    if stderr.strip():
        return "warning"
    return "success"


def _looks_like_debug_output(output: dict[str, Any]) -> bool:
    return any(
        key in output
        for key in (
            "exit_code",
            "stdout",
            "stderr",
            "timed_out",
            "display_command",
            "service",
        )
    )


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
