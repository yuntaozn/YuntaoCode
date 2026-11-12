from __future__ import annotations

from typing import Any


TOOL_ATTEMPT_OBSERVATION_SCHEMA_VERSION = "tool_attempt_observation.v1"

PROTOCOL_REASONS = frozenset({
    "invalid_tool_input",
    "malformed_tool_arguments",
    "non_object_tool_arguments",
    "truncated_tool_call",
    "unknown_tool",
})

CAPABILITY_REASONS = frozenset({
    "capability_service_unavailable",
    "plugin_disabled",
})

CONFIRMATION_REASONS = frozenset({
    "user_cancelled_tool",
})

SAFETY_REASONS = frozenset({
    "ai_plugin_draft_workspace_guard",
    "capability_pack_workspace_guard",
})


def build_tool_attempt_observation(
    *,
    tool_id: str,
    arguments: dict[str, Any] | None,
    reason: str,
    message: str,
    raw_tool_name: str = "",
    raw_arguments_text: str = "",
    missing_fields: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """为未能运行的工具调用构建面向模型的事实记录。

    该记录有意只作观察：不声明任务失败，也不选择下一条路线；它只说明本次具体尝试
    为何无法由 Runtime 执行。"""

    normalized_reason = str(reason or "tool_call_not_executed").strip()
    normalized_tool_id = str(tool_id or "").strip()
    input_summary = _input_summary(arguments, raw_arguments_text=raw_arguments_text)
    fields = _string_list(missing_fields, limit=12)
    boundary = _boundary(normalized_reason)
    recoverable = _recoverable(normalized_reason)
    return {
        "schema_version": TOOL_ATTEMPT_OBSERVATION_SCHEMA_VERSION,
        "kind": "tool_attempt_observation",
        "status": "not_executed",
        "boundary": boundary,
        "tool": normalized_tool_id,
        "raw_tool_name": str(raw_tool_name or "").strip(),
        "reason": normalized_reason,
        "message": _short(message, 900),
        "recoverable_by_model": recoverable,
        "hard_runtime_boundary": _hard_runtime_boundary(normalized_reason),
        "missing_fields": fields,
        "input_summary": input_summary,

    }


def tool_attempt_output(observation: dict[str, Any]) -> dict[str, Any]:
    """返回保留旧版 reason/message 字段的紧凑工具输出。"""

    reason = str(observation.get("reason") or "tool_call_not_executed")
    message = str(observation.get("message") or "")
    return {
        "type": "tool_attempt_observation",
        "schema_version": observation.get("schema_version")
        or TOOL_ATTEMPT_OBSERVATION_SCHEMA_VERSION,
        "reason": reason,
        "message": message,
        "observation": observation,
    }


def format_tool_attempt_observation(observation: dict[str, Any]) -> str:
    """将观察记录格式化，供提示、诊断或测试断言使用。"""

    if not isinstance(observation, dict):
        return ""
    lines = [
        "Tool attempt observation:",
        f"- status: {observation.get('status') or 'not_executed'}",
        f"- tool: {observation.get('tool') or 'unknown'}",
        f"- reason: {observation.get('reason') or 'unknown'}",
        f"- boundary: {observation.get('boundary') or 'runtime'}",
    ]
    message = str(observation.get("message") or "").strip()
    if message:
        lines.append(f"- message: {_short(message, 360)}")
    missing = _string_list(observation.get("missing_fields"), limit=12)
    if missing:
        lines.append(f"- missing fields: {', '.join(missing)}")
    summary = observation.get("input_summary") if isinstance(observation.get("input_summary"), dict) else {}
    if summary:
        bits: list[str] = []
        if summary.get("keys"):
            bits.append("keys=" + ",".join(_string_list(summary.get("keys"), limit=12)))
        if summary.get("path"):
            bits.append(f"path={summary.get('path')}")
        if summary.get("content_chars") is not None:
            bits.append(f"content_chars={summary.get('content_chars')}")
        if summary.get("raw_argument_chars") is not None:
            bits.append(f"raw_argument_chars={summary.get('raw_argument_chars')}")
        if bits:
            lines.append("- input summary: " + "; ".join(bits))
    return "\n".join(lines)


def _boundary(reason: str) -> str:
    if reason in PROTOCOL_REASONS:
        return "tool_call_protocol"
    if reason in CAPABILITY_REASONS:
        return "capability_availability"
    if reason in CONFIRMATION_REASONS:
        return "user_confirmation"
    if reason in SAFETY_REASONS:
        return "safety_boundary"
    return "runtime_boundary"


def _recoverable(reason: str) -> bool:
    if reason in {"plugin_disabled", "user_cancelled_tool"}:
        return False
    return True


def _hard_runtime_boundary(reason: str) -> bool:
    return reason in CAPABILITY_REASONS or reason in CONFIRMATION_REASONS or reason in SAFETY_REASONS


def _input_summary(arguments: dict[str, Any] | None, *, raw_arguments_text: str) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    summary: dict[str, Any] = {
        "keys": sorted(str(key) for key in args.keys())[:24],
    }
    raw_text = str(raw_arguments_text or "")
    if raw_text:
        summary["raw_argument_chars"] = len(raw_text)
    path = (
        args.get("path")
        or args.get("output_path")
        or args.get("file_path")
        or args.get("filepath")
        or ""
    )
    if path:
        summary["path"] = _short(str(path), 360)
    content = args.get("content")
    if isinstance(content, str):
        summary["content_chars"] = len(content)
    patch = args.get("patch")
    if isinstance(patch, str):
        summary["patch_chars"] = len(patch)
    command = args.get("command")
    if isinstance(command, str) and command.strip():
        summary["command"] = _short(command, 360)
    return summary


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _short(text: Any, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"
