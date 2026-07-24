"""Read-only visual verification summaries.

VisualVerification summarizes screenshot/render/browser preview evidence for
RunResult, RunEvidence, and the UI. It does not decide task intent, select a
preview tool, or mark a task complete. It only gathers observable facts so the
model and user can see whether visual evidence existed, whether it had runtime
errors, and whether it entered model context.
"""

from __future__ import annotations

from typing import Any

from runtime.visual_evidence import visual_evidence_summary


VISUAL_VERIFICATION_SCHEMA_VERSION = "visual_verification.v1"


def build_visual_verification_summary(
    *,
    visual_evidence: list[dict[str, Any]] | None = None,
    debug_sessions: list[dict[str, Any]] | None = None,
    visual_context: list[dict[str, Any]] | None = None,
    verification_evidence: list[dict[str, Any]] | None = None,
    required_modalities: list[str] | tuple[str, ...] | None = None,
    observed_modalities: list[str] | tuple[str, ...] | None = None,
    missing_modalities: list[str] | tuple[str, ...] | None = None,
    result_status: str = "",
    risks: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return an evidence-only visual verification summary."""

    visual_records = _visual_records(visual_evidence)
    model_context_records = _visual_context_records(visual_context)
    injected_paths = {
        str(item.get("path") or "")
        for item in model_context_records
        if str(item.get("path") or "").strip()
    }
    for record in visual_records:
        path = str(record.get("path") or "")
        record["injected_into_model_context"] = bool(
            record.get("injected_into_model_context") or path and path in injected_paths
        )

    debug_records = _debug_records(debug_sessions)
    verification_records = _visual_verification_records(verification_evidence)
    required = _unique(required_modalities)
    observed = _unique(observed_modalities)
    missing = _unique(missing_modalities)
    risk_codes = _unique(risks)
    runtime_error_records = [
        record for record in visual_records
        if bool(record.get("has_runtime_errors"))
    ]
    debug_error_records = [
        record for record in debug_records
        if bool(record.get("has_runtime_errors")) or str(record.get("status") or "") not in {"", "success"}
    ]
    source_types = _unique(record.get("source_type") for record in visual_records)
    tools = _unique(record.get("tool") for record in visual_records)

    injected_count = len(model_context_records) or sum(
        1 for record in visual_records if bool(record.get("injected_into_model_context"))
    )

    return {
        "schema_version": VISUAL_VERIFICATION_SCHEMA_VERSION,
        "kind": "visual_verification",
        "boundary": "evidence_only",
        "result_status": str(result_status or ""),
        "counts": {
            "visual_evidence": len(visual_records),
            "visual_verification_records": len(verification_records),
            "debug_sessions": len(debug_records),
            "model_context_records": len(model_context_records),
            "model_context_injected": injected_count,
            "model_context_eligible": sum(
                1 for record in visual_records if bool(record.get("model_context_eligible"))
            ),
            "runtime_error_records": len(runtime_error_records),
            "debug_error_records": len(debug_error_records),
            "console_errors": sum(_safe_int(record.get("console_error_count"), 0) for record in visual_records),
            "page_errors": sum(_safe_int(record.get("page_error_count"), 0) for record in visual_records),
            "failed_requests": sum(_safe_int(record.get("failed_request_count"), 0) for record in visual_records),
        },
        "flags": {
            "has_visual_evidence": bool(visual_records),
            "has_visual_verification": bool(verification_records),
            "visual_required": "visual" in required or "visual" in missing,
            "visual_observed": "visual" in observed,
            "visual_missing": "visual" in missing,
            "has_runtime_errors": bool(runtime_error_records or debug_error_records),
            "model_context_available": any(bool(record.get("model_context_eligible")) for record in visual_records),
            "model_context_injected": bool(model_context_records)
            or any(bool(record.get("injected_into_model_context")) for record in visual_records),
        },
        "modalities": {
            "required": required,
            "observed": observed,
            "missing": missing,
        },
        "sources": {
            "tools": tools[:12],
            "source_types": source_types[:12],
        },
        "risk_codes": risk_codes[:16],
        "records": visual_records[-12:],
        "verification_records": verification_records[-12:],
        "model_context_records": model_context_records[-8:],
        "debug_sessions": debug_records[-8:],
    }


def _visual_records(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value or []:
        if not isinstance(item, dict):
            continue
        summary = visual_evidence_summary(item)
        if not summary:
            continue
        record = _compact_visual_record(summary)
        record["tool"] = str(item.get("tool") or record.get("tool") or "")
        record["status"] = str(item.get("status") or record.get("status") or "")
        record["injected_into_model_context"] = bool(item.get("injected_into_model_context"))
        key = (str(record.get("tool") or ""), str(record.get("path") or ""))
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def _visual_context_records(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value or []:
        if not isinstance(item, dict):
            continue
        summary = visual_evidence_summary(item) or item
        record = _compact_visual_record(summary)
        record["tool"] = str(item.get("tool") or record.get("tool") or "")
        record["status"] = str(item.get("status") or record.get("status") or "")
        record["injected_into_model_context"] = bool(item.get("injected_into_model_context", True))
        record["mime_type"] = str(item.get("mime_type") or "")
        key = (str(record.get("tool") or ""), str(record.get("path") or ""))
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def _compact_visual_record(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": summary.get("schema_version"),
        "kind": summary.get("kind") or "visual_evidence",
        "tool": str(summary.get("tool") or ""),
        "status": str(summary.get("status") or ""),
        "source_type": str(summary.get("source_type") or ""),
        "source_url": str(summary.get("source_url") or ""),
        "source_path": str(summary.get("source_path") or ""),
        "path": str(summary.get("path") or ""),
        "artifact_kind": str(summary.get("artifact_kind") or ""),
        "format": str(summary.get("format") or ""),
        "width": _safe_int(summary.get("width"), 0),
        "height": _safe_int(summary.get("height"), 0),
        "size": _safe_int(summary.get("size"), 0),
        "captured_at": str(summary.get("captured_at") or ""),
        "title": str(summary.get("title") or ""),
        "status_code": _safe_int(summary.get("status_code"), 0),
        "has_runtime_errors": bool(summary.get("has_runtime_errors")),
        "console_error_count": _safe_int(summary.get("console_error_count"), 0),
        "page_error_count": _safe_int(summary.get("page_error_count"), 0),
        "failed_request_count": _safe_int(summary.get("failed_request_count"), 0),
        "model_context_eligible": bool(summary.get("model_context_eligible")),
        "model_context_modality": str(summary.get("model_context_modality") or ""),
        "model_context_path": str(summary.get("model_context_path") or ""),
    }


def _debug_records(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        records.append({
            "tool": str(item.get("tool") or ""),
            "source_type": str(item.get("source_type") or ""),
            "command": str(item.get("command") or ""),
            "executable": str(item.get("executable") or ""),
            "exit_code": item.get("exit_code"),
            "timed_out": bool(item.get("timed_out")),
            "duration_seconds": item.get("duration_seconds"),
            "diagnostic_count": _safe_int(item.get("diagnostic_count"), 0),
            "status": str(item.get("status") or ""),
            "has_runtime_errors": bool(item.get("has_runtime_errors")),
            "service": item.get("service") if isinstance(item.get("service"), dict) else {},
        })
    return records


def _visual_verification_records(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        modalities = _unique(item.get("modalities"))
        if "visual" not in modalities and str(item.get("modality") or "") != "visual":
            continue
        records.append({
            "tool": str(item.get("tool") or ""),
            "path": str(item.get("path") or ""),
            "strength": str(item.get("strength") or ""),
            "sufficient": bool(item.get("sufficient")),
            "modalities": modalities or ["visual"],
            "status": str(item.get("status") or ""),
        })
    return records


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
