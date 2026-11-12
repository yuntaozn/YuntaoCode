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
    """返回已完成工具结果中的风险事实。

    风险是面向模型的证据和审计事实，不选择模型下一动作，也不阻止后续工具调用。"""
    normalized_status = str(status or "").strip()
    if normalized_status == "failure":
        if str(tool_id or "").strip() == "shell.run_command":
            return _failed_shell_risks(tool_id, output, error=error)
        return _failed_tool_risks(tool_id, output, error=error)
    if normalized_status != "success" or not isinstance(output, dict):
        return []

    risks: list[dict[str, Any]] = []
    images = output.get("inline_images")
    for image in images if isinstance(images, list) else []:
        if not isinstance(image, dict):
            continue
        if image.get("uniform_pixels") is True or image.get("omission_reason"):
            risks.append({
                "code": "visual_pixels_uniform" if image.get("uniform_pixels") else "visual_image_unavailable",
                "severity": "warning", "source": tool_id, "blocking": False,
                "content_index": image.get("content_index"),
                "pixel_ranges": image.get("pixel_ranges"),
                "omission_reason": image.get("omission_reason"),
                "message": (
                    "Captured image has uniform pixel values."
                    if image.get("uniform_pixels")
                    else "Image data was unavailable for model input."
                ),
            })
    if str(tool_id or "").strip() == "shell.run_command" and shell_success_has_stderr_warning(output):
        risks.append({
            "code": SHELL_STDERR_WARNING_CODE,
            "severity": "warning",
            "source": tool_id,
            "detail": _stderr_detail(output),
            "blocking": False,
            "message": (
                "The command exited with code 0; stderr contains an error-like signal."
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
            "blocking": False,
            "message": "The tool reported a text encoding warning.",
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
            "blocking": False,
            "message": "Artifact integrity check reported issues.",
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
    """返回附带模型侧运行时风险证据的载荷副本。"""
    result = dict(payload)
    # 兼容旧载荷时也不将历史策略建议重新投射为工具结果或风险。
    result.pop("runtime_advisories", None)
    risks = assess_tool_result_risks(
        str(payload.get("tool") or ""),
        str(payload.get("status") or ""),
        payload.get("output"),
        error=payload.get("error"),
    )
    if not risks:
        return result
    # 风险事实位于大输出之前，避免载荷压缩先截断诊断。
    return {"runtime_risks": risks, **result}


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
    return [{
        "code": code,
        "severity": "warning",
        "source": str(tool_id or ""),
        "message": (
            "External tool call failed; partial changes may remain. Rollback is unconfirmed."
        ),
        "side_effects": "unknown",
        "rollback_observed": False,
        "detail": text[:500],
        "blocking": False,
    }]


def _failed_shell_risks(tool_id: str, output: Any, *, error: Any = "") -> list[dict[str, Any]]:
    if not isinstance(output, dict):
        return []
    diagnostics = output.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        return []
    first = diagnostics[0] if isinstance(diagnostics[0], dict) else {}
    code = str(first.get("code") or "shell_command_failed_with_diagnostic")
    return [{
        "code": f"shell_{code}",
        "severity": "warning",
        "source": str(tool_id or ""),
        "message": "Shell command failed with a structured diagnostic.",
        "detail": str(first.get("message") or _failure_text(output, error=error))[:500],
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
