from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


DESKTOP_STATE_SCHEMA_VERSION = "desktop_state.v1"
VISUAL_EVIDENCE_SCHEMA_VERSION = "visual_evidence.v1"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_desktop_state(
    *,
    platform_name: str,
    scope: str,
    windows: list[dict[str, Any]] | None = None,
    active_window: dict[str, Any] | None = None,
    processes: list[dict[str, Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    captured_at: str = "",
) -> dict[str, Any]:
    window_records = [dict(item) for item in windows or [] if isinstance(item, dict)]
    process_records = [dict(item) for item in processes or [] if isinstance(item, dict)]
    diagnostic_records = [dict(item) for item in diagnostics or [] if isinstance(item, dict)]
    active = dict(active_window or {}) if isinstance(active_window, dict) else {}
    return {
        "schema_version": DESKTOP_STATE_SCHEMA_VERSION,
        "kind": "desktop_state",
        "source": "desktop_observation",
        "platform": str(platform_name or "unknown"),
        "scope": str(scope or "desktop"),
        "captured_at": captured_at or utc_now_iso(),
        "counts": {
            "windows": len(window_records),
            "processes": len(process_records),
            "diagnostics": len(diagnostic_records),
        },
        "active_window": active,
        "windows": window_records,
        "processes": process_records,
        "diagnostics": diagnostic_records,
    }


def build_visual_evidence(
    *,
    source_type: str,
    screenshot_path: str,
    platform_name: str,
    source_window: dict[str, Any] | None = None,
    artifact_kind: str = "screenshot",
    format: str = "png",
    width: int | None = None,
    height: int | None = None,
    size: int | None = None,
    captured_at: str = "",
    has_runtime_errors: bool = False,
    can_enter_model_context: bool | None = None,
) -> dict[str, Any]:
    fmt = _format_name(format)
    eligible = bool(screenshot_path) and fmt in {"png", "jpeg", "jpg", "webp"}
    if can_enter_model_context is not None:
        eligible = bool(can_enter_model_context)
    window = dict(source_window or {}) if isinstance(source_window, dict) else {}
    return {
        "schema_version": VISUAL_EVIDENCE_SCHEMA_VERSION,
        "kind": "visual_evidence",
        "source": {
            "type": str(source_type or "desktop"),
            "platform": str(platform_name or "unknown"),
            "window": window,
        },
        "artifact": {
            "kind": str(artifact_kind or "screenshot"),
            "path": str(screenshot_path or ""),
            "format": fmt,
            "size": size,
            "width": width,
            "height": height,
        },
        "captured_at": captured_at or utc_now_iso(),
        "runtime": {
            "has_errors": bool(has_runtime_errors),
            "console_errors": [],
            "console_warnings": [],
            "page_errors": [],
            "failed_requests": [],
        },
        "model_context": {
            "eligible": eligible,
            "modality": "image" if eligible else "text",
            "path": str(screenshot_path or "") if eligible else "",
        },
    }


def diagnostic(code: str, message: str, *, severity: str = "info", **details: Any) -> dict[str, Any]:
    return {
        "code": str(code or "desktop_observation_notice"),
        "severity": str(severity or "info"),
        "message": str(message or ""),
        "details": {key: value for key, value in details.items() if value not in (None, "", [], {})},
    }


def _format_name(value: Any) -> str:
    fmt = str(value or "").strip().lower()
    if fmt == "jpg":
        return "jpeg"
    return fmt or "png"

