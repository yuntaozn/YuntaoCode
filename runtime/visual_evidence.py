"""稳定的视觉证据契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


VISUAL_EVIDENCE_SCHEMA_VERSION = "visual_evidence.v1"
VISUAL_IMAGE_FORMATS = {"png", "jpeg", "jpg", "webp"}
VISUAL_ARTIFACT_KINDS = {
    "image",
    "screenshot",
    "render",
    "render_image",
    "viewport_screenshot",
    "visual_capture",
}


def build_visual_evidence(
    *,
    source_type: str,
    screenshot_path: str = "",
    source_path: str = "",
    source_url: str = "",
    served_via: str = "",
    served_root: str = "",
    artifact_kind: str = "screenshot",
    format: str = "png",
    width: int | None = None,
    height: int | None = None,
    full_page: bool | None = None,
    size: int | None = None,
    status_code: int | None = None,
    title: str = "",
    console_errors: list[Any] | None = None,
    console_warnings: list[Any] | None = None,
    page_errors: list[Any] | None = None,
    failed_requests: list[Any] | None = None,
    has_runtime_errors: bool | None = None,
    can_enter_model_context: bool | None = None,
    captured_at: str = "",
    provider: str = "",
) -> dict[str, Any]:
    """构建稳定的视觉证据记录。

    该记录有意只作描述：不决定任务策略，也不阻止执行。Runtime 使用方可将其用于
    RunResult、紧凑模型上下文、UI 预览和未来的多模态附件。"""

    fmt = _format_name(format)
    runtime_errors = bool(has_runtime_errors)
    if has_runtime_errors is None:
        runtime_errors = bool(console_errors or page_errors or failed_requests)
    model_context_eligible = (
        bool(screenshot_path)
        and (artifact_kind or "").strip().lower() in VISUAL_ARTIFACT_KINDS
        and fmt in VISUAL_IMAGE_FORMATS
    )
    if can_enter_model_context is not None:
        model_context_eligible = bool(can_enter_model_context)

    evidence = {
        "schema_version": VISUAL_EVIDENCE_SCHEMA_VERSION,
        "kind": "visual_evidence",
        "source": {
            "type": str(source_type or "").strip() or "unknown",
            "url": str(source_url or ""),
            "path": str(source_path or ""),
            "served_via": str(served_via or ""),
            "served_root": str(served_root or ""),
            "provider": str(provider or ""),
        },
        "artifact": {
            "kind": str(artifact_kind or "screenshot"),
            "path": str(screenshot_path or ""),
            "format": fmt,
            "size": size,
            "width": width,
            "height": height,
            "full_page": full_page,
        },
        "captured_at": captured_at or _utc_now_iso(),
        "page": {
            "title": str(title or ""),
            "status_code": status_code,
        },
        "runtime": {
            "has_errors": runtime_errors,
            "console_errors": _bounded_list(console_errors, 20),
            "console_warnings": _bounded_list(console_warnings, 20),
            "page_errors": _bounded_list(page_errors, 20),
            "failed_requests": _bounded_list(failed_requests, 20),
        },
        "model_context": {
            "eligible": model_context_eligible,
            "modality": "image" if model_context_eligible else "text",
            "path": str(screenshot_path or "") if model_context_eligible else "",
        },
    }
    return evidence


def normalize_visual_evidence(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """从新的嵌套契约或旧版字段中返回视觉证据。"""

    if not isinstance(output, dict):
        return None
    existing = output.get("visual_evidence")
    if isinstance(existing, dict) and existing.get("kind") == "visual_evidence":
        return existing

    artifact_kind = str(output.get("artifact_kind") or "").strip()
    artifacts = output.get("artifacts")
    artifact_values = artifacts if isinstance(artifacts, list) else []
    artifact_names = {str(item or "").strip().lower() for item in artifact_values}
    path = str(
        output.get("path")
        or output.get("screenshot_path")
        or output.get("image_path")
        or output.get("render_path")
        or ""
    )
    if not (
        artifact_kind.lower() in VISUAL_ARTIFACT_KINDS
        or artifact_names & VISUAL_ARTIFACT_KINDS
        or _path_looks_visual(path)
    ):
        return None

    source_type = str(output.get("source_type") or output.get("type") or "tool")
    return build_visual_evidence(
        source_type=source_type,
        source_url=str(output.get("url") or output.get("final_url") or ""),
        source_path=str(output.get("source_path") or ""),
        served_via=str(output.get("served_via") or ""),
        served_root=str(output.get("served_root") or ""),
        artifact_kind=artifact_kind or "screenshot",
        screenshot_path=path,
        format=str(output.get("format") or ""),
        width=_optional_int(output.get("width")),
        height=_optional_int(output.get("height")),
        full_page=output.get("full_page") if isinstance(output.get("full_page"), bool) else None,
        size=_optional_int(output.get("size")),
        status_code=_optional_int(output.get("status_code")),
        title=str(output.get("title") or ""),
        console_errors=_as_list(output.get("console_errors")),
        console_warnings=_as_list(output.get("console_warnings")),
        page_errors=_as_list(output.get("page_errors")),
        failed_requests=_as_list(output.get("failed_requests")),
        has_runtime_errors=output.get("has_runtime_errors")
        if isinstance(output.get("has_runtime_errors"), bool)
        else None,
    )


def visual_evidence_summary(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    """返回适用于前端预览和模型上下文的紧凑摘要。"""

    if not isinstance(evidence, dict):
        return None
    if _is_visual_evidence_summary(evidence):
        return {
            "schema_version": evidence.get("schema_version") or VISUAL_EVIDENCE_SCHEMA_VERSION,
            "kind": "visual_evidence",
            "source_type": evidence.get("source_type"),
            "source_url": evidence.get("source_url"),
            "source_path": evidence.get("source_path"),
            "path": evidence.get("path"),
            "artifact_kind": evidence.get("artifact_kind"),
            "format": evidence.get("format"),
            "width": _optional_int(evidence.get("width")),
            "height": _optional_int(evidence.get("height")),
            "size": _optional_int(evidence.get("size")),
            "captured_at": evidence.get("captured_at"),
            "title": evidence.get("title"),
            "status_code": _optional_int(evidence.get("status_code")),
            "has_runtime_errors": bool(evidence.get("has_runtime_errors")),
            "console_error_count": _optional_int(evidence.get("console_error_count")) or 0,
            "page_error_count": _optional_int(evidence.get("page_error_count")) or 0,
            "failed_request_count": _optional_int(evidence.get("failed_request_count")) or 0,
            "model_context_eligible": bool(evidence.get("model_context_eligible")),
            "model_context_modality": evidence.get("model_context_modality"),
            "model_context_path": evidence.get("model_context_path") or evidence.get("path") or "",
        }
    artifact = evidence.get("artifact") if isinstance(evidence.get("artifact"), dict) else {}
    source = evidence.get("source") if isinstance(evidence.get("source"), dict) else {}
    runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else {}
    page = evidence.get("page") if isinstance(evidence.get("page"), dict) else {}
    model_context = (
        evidence.get("model_context")
        if isinstance(evidence.get("model_context"), dict)
        else {}
    )
    return {
        "schema_version": evidence.get("schema_version") or VISUAL_EVIDENCE_SCHEMA_VERSION,
        "kind": "visual_evidence",
        "source_type": source.get("type"),
        "source_url": source.get("url"),
        "source_path": source.get("path"),
        "path": artifact.get("path"),
        "artifact_kind": artifact.get("kind"),
        "format": artifact.get("format"),
        "width": artifact.get("width"),
        "height": artifact.get("height"),
        "size": artifact.get("size"),
        "captured_at": evidence.get("captured_at"),
        "title": page.get("title"),
        "status_code": page.get("status_code"),
        "has_runtime_errors": bool(runtime.get("has_errors")),
        "console_error_count": len(runtime.get("console_errors") or []),
        "page_error_count": len(runtime.get("page_errors") or []),
        "failed_request_count": len(runtime.get("failed_requests") or []),
        "model_context_eligible": bool(model_context.get("eligible")),
        "model_context_modality": model_context.get("modality"),
        "model_context_path": model_context.get("path") or "",
    }


def _is_visual_evidence_summary(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "source_type",
            "source_url",
            "source_path",
            "artifact_kind",
            "model_context_eligible",
            "model_context_path",
        )
    )


def _format_name(value: Any) -> str:
    fmt = str(value or "").strip().lower()
    if fmt == "jpg":
        return "jpeg"
    return fmt or "png"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _bounded_list(value: list[Any] | None, limit: int) -> list[Any]:
    return _as_list(value)[:limit]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _path_looks_visual(path: str) -> bool:
    lower = str(path or "").strip().lower()
    return lower.endswith((
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".pdf",
    ))
