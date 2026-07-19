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
    available_tool_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build a model-facing fact record for a tool call that did not run.

    The record is deliberately observational.  It does not declare the task
    failed and it does not choose the next route; it only explains why this
    specific attempt could not be executed by the runtime.
    """

    normalized_reason = str(reason or "tool_call_not_executed").strip()
    normalized_tool_id = str(tool_id or "").strip()
    input_summary = _input_summary(arguments, raw_arguments_text=raw_arguments_text)
    fields = _string_list(missing_fields, limit=12)
    available = _string_list(available_tool_ids, limit=24)
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
        "available_tool_ids": available,
        "model_decision": _model_decision(
            normalized_tool_id,
            normalized_reason,
            fields,
            input_summary,
            bool(available),
        ),
    }


def tool_attempt_output(observation: dict[str, Any]) -> dict[str, Any]:
    """Return a compact tool output that preserves old reason/message fields."""

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
    """Format the observation for prompts, diagnostics, or test assertions."""

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
    _append_list(lines, "available tools", observation.get("available_tool_ids"))
    _append_list(lines, "model decision", observation.get("model_decision"))
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


def _model_decision(
    tool_id: str,
    reason: str,
    missing_fields: list[str],
    input_summary: dict[str, Any],
    has_available_tools: bool,
) -> list[str]:
    decisions = [
        "Treat this as a failed tool attempt, not as proof that the user goal is impossible.",
    ]
    if reason == "unknown_tool":
        text = "Choose a canonical tool ID from the visible tools"
        if has_available_tools:
            text += " or call a discovery/read tool first"
        decisions.append(text + ".")
    elif reason in {"malformed_tool_arguments", "non_object_tool_arguments"}:
        decisions.append(
            "Resend the tool call using valid JSON object arguments, or answer directly if no tool is needed."
        )
    elif reason == "invalid_tool_input":
        if missing_fields:
            decisions.append(
                "Retry only after supplying the required fields: "
                + ", ".join(missing_fields)
                + "."
            )
        else:
            decisions.append("Retry only after supplying the tool schema requirements.")
    elif reason == "truncated_tool_call":
        decisions.append(
            "Use smaller complete arguments; for large code or long text, split the work into bounded file edits or chunks."
        )
    elif reason == "capability_service_unavailable":
        decisions.append(
            "Decide whether to start or refresh the capability service, choose another available route, or report the dependency boundary."
        )
    elif reason == "plugin_disabled":
        decisions.append(
            "The user/runtime disabled this tool; choose another enabled route or ask the user to enable it."
        )
    elif reason == "user_cancelled_tool":
        decisions.append(
            "The user cancelled this local action; do not repeat it blindly, and ask only if the task still requires that action."
        )
    else:
        decisions.append(
            "Use the observed reason to change arguments, choose another capability, gather missing context, verify existing output, or stop honestly."
        )
    if _looks_like_large_write(tool_id, input_summary):
        decisions.append(
            "Large write-like payload observed; prefer incremental write/edit tools instead of one oversized call."
        )
    return decisions


def _looks_like_large_write(tool_id: str, input_summary: dict[str, Any]) -> bool:
    if "write" not in tool_id and "edit" not in tool_id and "patch" not in tool_id:
        return False
    for key in ("content_chars", "patch_chars", "raw_argument_chars"):
        try:
            if int(input_summary.get(key) or 0) >= 12000:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _append_list(lines: list[str], title: str, value: Any) -> None:
    items = _string_list(value, limit=12)
    if not items:
        return
    lines.append(f"- {title}:")
    lines.extend(f"  - {_short(item, 240)}" for item in items)


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
