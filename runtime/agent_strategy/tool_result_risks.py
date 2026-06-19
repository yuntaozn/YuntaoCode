from __future__ import annotations

from typing import Any


def assess_tool_result_risks(
    tool_id: str,
    status: str,
    output: Any,
    *,
    error: Any = "",
) -> list[dict[str, Any]]:
    """Return advisory risks discovered in a completed tool result.

    Risks are model-facing evidence and audit facts. They do not choose the
    model's next action and do not block later tool calls.
    """
    normalized_status = str(status or "").strip()
    if normalized_status == "failure":
        return _failed_tool_risks(tool_id, output, error=error)
    if normalized_status != "success" or not isinstance(output, dict):
        return []

    risks: list[dict[str, Any]] = []
    integrity = output.get("integrity")
    if isinstance(integrity, dict) and integrity.get("checked") is True and integrity.get("valid") is not True:
        issues = [
            str(issue).strip()
            for issue in integrity.get("issues") or []
            if str(issue).strip()
        ]
        risks.append({
            "code": "artifact_integrity_invalid",
            "severity": "warning",
            "source": tool_id,
            "path": str(output.get("path") or ""),
            "issues": issues,
            "action": "assess_before_state_change",
            "suggested_tools": ["filesystem.transform_text"],
            "blocking": False,
            "message": (
                "The inspected artifact has an integrity warning. Before changing local state, "
                "assess this evidence and choose whether to repair the artifact, continue with "
                "an explicit assumption, or stop and report the risk. Prefer a bounded local "
                "transformation over retransmitting the complete artifact."
            ),
        })
    return risks


def attach_tool_result_risks(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a payload copy with model-facing runtime risk evidence."""
    risks = assess_tool_result_risks(
        str(payload.get("tool") or ""),
        str(payload.get("status") or ""),
        payload.get("output"),
        error=payload.get("error"),
    )
    if not risks:
        return dict(payload)
    # Keep risks before potentially large output so compact transport cannot
    # truncate the advisory before the model sees it.
    return {"runtime_risks": risks, **payload}


def _failed_tool_risks(tool_id: str, output: Any, *, error: Any = "") -> list[dict[str, Any]]:
    if not _is_external_capability_tool(tool_id):
        return []
    text = _failure_text(output, error=error)
    if not text:
        text = "tool call failed"
    unsupported = _looks_like_unsupported_capability_tool(text)
    code = (
        "external_capability_tool_unsupported"
        if unsupported
        else "external_capability_tool_failed"
    )
    action = (
        "refresh_capability_or_choose_alternative"
        if unsupported
        else "do_not_retry_same_call_blindly"
    )
    return [{
        "code": code,
        "severity": "warning",
        "source": str(tool_id or ""),
        "message": (
            "The external capability tool failed in this run. Treat this as "
            "runtime evidence, avoid repeating the same call without new "
            "information, and either choose another available strategy, run a "
            "small roundtrip check, restart/refresh the capability, or report "
            "the limitation honestly."
        ),
        "detail": text[:500],
        "action": action,
        "blocking": False,
    }]


def _is_external_capability_tool(tool_id: str) -> bool:
    normalized = str(tool_id or "").strip()
    return normalized.startswith("mcp_") or normalized.startswith("mcp.")


def _failure_text(output: Any, *, error: Any = "") -> str:
    parts: list[str] = []
    if isinstance(error, str) and error.strip():
        parts.append(error.strip())
    if isinstance(output, dict):
        for key in ("message", "error", "content"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    elif isinstance(output, str) and output.strip():
        parts.append(output.strip())
    return " ".join(parts)


def _looks_like_unsupported_capability_tool(text: str) -> bool:
    lowered = str(text or "").lower()
    terms = (
        "unknown command",
        "unknown tool",
        "unsupported",
        "not supported",
        "not implemented",
        "method not found",
        "no such tool",
        "unrecognized command",
    )
    return any(term in lowered for term in terms)
