"""只读的 ToolTask 进度摘要。

本模块将持久化 ToolTask 日志转换为紧凑操作事实，供 API、流事件和任务工作台使用。
它不得判断任务意图、选择工具或确定完成状态。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


TOOL_TASK_PROGRESS_SCHEMA_VERSION = "tool_task_progress.v1"
RUNNING_STATUSES = {"queued", "running", "waiting_confirmation"}
STALE_AFTER_SECONDS = 60


def build_tool_task_progress(task: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """为类似 ToolTask 的对象返回仅包含证据的进度摘要。"""

    now = now or datetime.now(timezone.utc)
    logs = _logs(task)
    created_at = _text(getattr(task, "created_at", ""))
    updated_at = _text(getattr(task, "updated_at", ""))
    last_log = _last_log(logs)
    command_start = _first_log_by_kind(logs, "command_start") or _first_log_with_key(logs, "command_role")
    last_output = _last_log_by_kind(logs, "command_output")
    last_heartbeat = _last_log_by_kind(logs, "command_heartbeat")
    cancellation = _last_log_by_kind(logs, "command_cancelled")
    last_progress_time = _text(last_log.get("time") or updated_at or created_at)
    elapsed_seconds = _seconds_between(created_at, now)
    stale_seconds = _seconds_between(last_progress_time, now)
    role = _text(_data(command_start).get("command_role"))
    if not role:
        role = _infer_role_from_tool(_text(getattr(task, "tool", "")))

    return {
        "schema_version": TOOL_TASK_PROGRESS_SCHEMA_VERSION,
        "kind": "tool_task_progress",
        "boundary": "evidence_only",
        "task_id": _text(getattr(task, "id", "")),
        "tool": _text(getattr(task, "tool", "")),
        "status": _text(getattr(task, "status", "")),
        "created_at": created_at,
        "updated_at": updated_at,
        "elapsed_seconds": elapsed_seconds,
        "stale_seconds": stale_seconds,
        "can_cancel": _text(getattr(task, "status", "")) in RUNNING_STATUSES,
        "command": {
            "role": role,
            "cwd": _text(_data(command_start).get("cwd")),
            "timeout": _data(command_start).get("timeout"),
            "observable": bool(_data(command_start).get("observable")),
        },
        "last_log": _compact_log(last_log),
        "last_output": _compact_log(last_output),
        "last_heartbeat": _compact_log(last_heartbeat),
        "cancellation": _compact_log(cancellation),
        "counts": {
            "logs": len(logs),
            "output_events": _count_logs_by_kind(logs, "command_output"),
            "heartbeat_events": _count_logs_by_kind(logs, "command_heartbeat"),
            "warning_events": sum(1 for item in logs if _text(item.get("level")) == "warning"),
            "error_events": sum(1 for item in logs if _text(item.get("level")) == "error"),
        },
        "flags": {
            "has_live_output": bool(last_output),
            "has_heartbeat": bool(last_heartbeat),
            "has_cancellation": bool(cancellation),
            "is_dependency_install": role == "dependency_install",
            "is_long_running": role in {"dependency_install", "preview_service", "service"},
            "is_stale": stale_seconds is not None and stale_seconds >= STALE_AFTER_SECONDS,
        },
    }


def _logs(task: Any) -> list[dict[str, Any]]:
    value = getattr(task, "logs", None)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _last_log(logs: list[dict[str, Any]]) -> dict[str, Any]:
    return logs[-1] if logs else {}


def _first_log_by_kind(logs: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    for item in logs:
        if _text(_data(item).get("kind")) == kind:
            return item
    return {}


def _last_log_by_kind(logs: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    for item in reversed(logs):
        if _text(_data(item).get("kind")) == kind:
            return item
    return {}


def _first_log_with_key(logs: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for item in logs:
        if key in _data(item):
            return item
    return {}


def _count_logs_by_kind(logs: list[dict[str, Any]], kind: str) -> int:
    return sum(1 for item in logs if _text(_data(item).get("kind")) == kind)


def _compact_log(log: dict[str, Any]) -> dict[str, Any]:
    if not log:
        return {}
    data = _data(log)
    return {
        "time": _text(log.get("time")),
        "level": _text(log.get("level")),
        "message": _text(log.get("message"))[:1200],
        "kind": _text(data.get("kind")),
        "stream": _text(data.get("stream")),
        "elapsed_seconds": data.get("elapsed_seconds"),
        "silent_seconds": data.get("silent_seconds"),
    }


def _data(log: dict[str, Any]) -> dict[str, Any]:
    value = log.get("data")
    return value if isinstance(value, dict) else {}


def _seconds_between(iso_text: str, now: datetime) -> int | None:
    parsed = _parse_datetime(iso_text)
    if not parsed:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _parse_datetime(value: str) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _infer_role_from_tool(tool_id: str) -> str:
    if tool_id.startswith("preview.") or tool_id.startswith("web."):
        return "preview_service"
    return "command"


def _text(value: Any) -> str:
    return str(value or "").strip()
