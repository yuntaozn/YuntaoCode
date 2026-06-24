from __future__ import annotations

from typing import Any


SHELL_STDERR_WARNING_CODE = "shell_stderr_warning"


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
    if str(tool_id or "").strip() == "shell.run_command" and shell_success_has_stderr_warning(output):
        risks.append({
            "code": SHELL_STDERR_WARNING_CODE,
            "severity": "warning",
            "source": tool_id,
            "detail": _stderr_detail(output),
            "action": "treat_as_degraded_verification_evidence",
            "blocking": False,
            "message": (
                "The command exited with code 0, but stderr contains an error-like "
                "or exception-like signal. Treat this as degraded evidence: inspect "
                "the stderr, choose a stronger verification route, or report the "
                "uncertainty honestly instead of counting it as clean verification."
            ),
        })
    for risk in _encoding_risk_records(output):
        risks.append({
            "code": "text_encoding_risk",
            "severity": "warning",
            "source": tool_id,
            "path": risk.get("path") or str(output.get("path") or ""),
            "encoding": risk.get("encoding") or output.get("encoding") or "",
            "risk_code": risk.get("code") or "",
            "detail": risk.get("message") or "",
            "action": "verify_rendered_text_encoding",
            "blocking": False,
            "message": (
                "The tool result includes text encoding evidence that may affect rendered output. "
                "Treat it as advisory evidence: inspect the affected file or rendered page, add an "
                "explicit charset/encoding fix when appropriate, or report the uncertainty."
            ),
        })
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


def _encoding_risk_records(output: dict[str, Any]) -> list[dict[str, Any]]:
    raw = output.get("encoding_risks")
    records: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            nested = item.get("risks")
            if isinstance(nested, list):
                for risk in nested:
                    if isinstance(risk, dict):
                        records.append({
                            "path": item.get("path"),
                            "encoding": item.get("encoding"),
                            "code": risk.get("code"),
                            "message": risk.get("message"),
                        })
                continue
            records.append(item)
    return records[:8]


def shell_success_has_stderr_warning(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    if output.get("timed_out") is True:
        return False
    try:
        exit_code = int(output.get("exit_code", 0) or 0)
    except (TypeError, ValueError):
        exit_code = 0
    if exit_code != 0:
        return False
    stderr = str(output.get("stderr") or "").strip()
    if not stderr:
        return False
    return _looks_like_stderr_error(stderr)


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


def _stderr_detail(output: dict[str, Any]) -> str:
    stderr = str(output.get("stderr") or "").strip()
    return " ".join(stderr.split())[:800]


def _looks_like_stderr_error(text: str) -> bool:
    lowered = str(text or "").lower()
    terms = (
        "traceback (most recent call last)",
        "exception",
        "httplistenerexception",
        "modulenotfounderror",
        "syntaxerror",
        "typeerror",
        "referenceerror",
        "commandnotfoundexception",
        "cannot find module",
        "module_not_found",
        "failed to",
        "fatal:",
        "error:",
        " error:",
        "send_error",
        "系统找不到指定的文件",
        "系统找不到指定的路径",
        "找不到指定的文件",
        "无法运行此命令",
        "出现以下错误",
    )
    return any(term in lowered for term in terms)
