"""Run 级产物记录。

本模块把工具事件、RunResult、视觉证据、调试会话和验证证据中的可观察输出，
规范为统一的被动证据结构。它不判断任务意图、不选择工具、不阻止执行，
也不判断用户目标是否完成。"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from typing import Any

from runtime.agent_strategy.classifiers import is_write_tool
from runtime.debug_session import debug_session_summary, normalize_debug_session
from runtime.visual_evidence import normalize_visual_evidence, visual_evidence_summary


RUN_ARTIFACT_SCHEMA_VERSION = "run_artifact.v1"
RUN_ARTIFACT_SUMMARY_SCHEMA_VERSION = "run_artifact_summary.v1"

_PATH_FIELDS = (
    "path",
    "output_path",
    "file_path",
    "screenshot_path",
    "image_path",
    "render_path",
    "pdf_path",
    "docx_path",
    "preview_path",
)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".java",
    ".cs",
    ".go",
    ".rs",
    ".vue",
}
_DOCUMENT_EXTENSIONS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".pdf"}
_VISUAL_KINDS = {
    "image",
    "screenshot",
    "render",
    "render_image",
    "viewport_screenshot",
    "visual_capture",
    "visual_evidence",
    "pdf_page_render",
    "desktop_state",
}
_LOG_KINDS = {"debug_session", "command_output", "command_log", "stdout", "stderr", "log"}
_DRAFT_KINDS = {"draft", "text_draft"}
_EVIDENCE_KINDS = {"verification", "visual_evidence", "debug_session", "interaction_trace", "dom_text"}
_MODEL_CONTEXT_TEXT_KINDS = {
    "text",
    "text_file",
    "markdown",
    "html",
    "json",
    "log",
    "command_log",
}


def build_run_artifacts(
    *,
    workspace_path: str = "",
    tool_events: list[dict[str, Any]] | None = None,
    legacy_artifacts: list[dict[str, Any]] | None = None,
    visual_evidence: list[dict[str, Any]] | None = None,
    debug_sessions: list[dict[str, Any]] | None = None,
    verification_evidence: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """根据已观察到的运行时事实构建被动 Run 产物记录。"""

    records: list[dict[str, Any]] = []
    for index, event in enumerate(tool_events or []):
        if not isinstance(event, dict):
            continue
        records.extend(_records_from_tool_event(workspace_path, event, index))

    for item in legacy_artifacts or []:
        if not isinstance(item, dict):
            continue
        record = _record_from_legacy_artifact(workspace_path, item)
        if record:
            records.append(record)

    for item in visual_evidence or []:
        if not isinstance(item, dict):
            continue
        record = _record_from_visual_evidence(workspace_path, item)
        if record:
            records.append(record)

    for item in debug_sessions or []:
        if not isinstance(item, dict):
            continue
        record = _record_from_debug_session(item)
        if record:
            records.append(record)

    for item in verification_evidence or []:
        if not isinstance(item, dict):
            continue
        record = _record_from_verification_evidence(workspace_path, item)
        if record:
            records.append(record)

    return _dedupe_records(records)


def summarize_run_artifacts(records: list[dict[str, Any]] | None) -> dict[str, Any]:
    """返回供 UI、诊断和证据使用的紧凑计数与路径分组。"""

    artifacts = [item for item in (records or []) if isinstance(item, dict)]
    by_role: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_relevance: dict[str, int] = {}
    paths: list[str] = []
    final_paths: list[str] = []
    visual_paths: list[str] = []
    preview_paths: list[str] = []
    model_context_paths: list[str] = []
    verification_paths: list[str] = []
    diagnostic_paths: list[str] = []
    changed_paths: list[str] = []
    for item in artifacts:
        role = str(item.get("role") or "artifact")
        artifact_kind = str(item.get("artifact_kind") or item.get("kind") or "artifact")
        relevance = str(item.get("verification_relevance") or "context")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        by_role[role] = by_role.get(role, 0) + 1
        by_kind[artifact_kind] = by_kind.get(artifact_kind, 0) + 1
        by_relevance[relevance] = by_relevance.get(relevance, 0) + 1
        path = str(item.get("path") or "").strip()
        model_context_path = str(metadata.get("model_context_path") or path).strip()
        if path and path not in paths:
            paths.append(path)
        if path and role in {"final", "draft"} and path not in changed_paths:
            changed_paths.append(path)
        if path and role == "final" and path not in final_paths:
            final_paths.append(path)
        if path and (
            role in {"screenshot", "preview"}
            or artifact_kind in _VISUAL_KINDS
        ) and path not in visual_paths:
            visual_paths.append(path)
        if path and item.get("can_preview") and path not in preview_paths:
            preview_paths.append(path)
        if item.get("can_enter_model_context") and model_context_path and model_context_path not in model_context_paths:
            model_context_paths.append(model_context_path)
        if path and relevance == "verification" and path not in verification_paths:
            verification_paths.append(path)
        if path and relevance == "diagnostic" and path not in diagnostic_paths:
            diagnostic_paths.append(path)

    return {
        "schema_version": RUN_ARTIFACT_SUMMARY_SCHEMA_VERSION,
        "kind": "run_artifact_summary",
        "count": len(artifacts),
        "by_role": by_role,
        "by_artifact_kind": by_kind,
        "by_verification_relevance": by_relevance,
        "previewable_count": sum(1 for item in artifacts if item.get("can_preview")),
        "model_context_eligible_count": sum(
            1 for item in artifacts if item.get("can_enter_model_context")
        ),
        "verification_relevant_count": sum(
            1
            for item in artifacts
            if str(item.get("verification_relevance") or "")
            in {"verification", "diagnostic"}
        ),
        "paths": paths[:24],
        "changed_paths": changed_paths[:24],
        "final_paths": final_paths[:24],
        "visual_paths": visual_paths[:24],
        "preview_paths": preview_paths[:24],
        "model_context_paths": model_context_paths[:24],
        "verification_paths": verification_paths[:24],
        "diagnostic_paths": diagnostic_paths[:24],
        "path_index": _artifact_path_index(artifacts)[:24],
        "flags": {
            "has_artifacts": bool(artifacts),
            "has_final_artifacts": bool(final_paths),
            "has_visual_artifacts": bool(visual_paths),
            "has_previewable_artifacts": bool(preview_paths),
            "has_model_context_artifacts": any(
                bool(item.get("can_enter_model_context")) for item in artifacts
            ),
            "has_logs": any(str(item.get("role") or "") == "log" for item in artifacts),
            "has_verification_evidence": any(
                str(item.get("verification_relevance") or "") == "verification"
                for item in artifacts
            ),
            "has_diagnostic_artifacts": any(
                str(item.get("verification_relevance") or "") == "diagnostic"
                for item in artifacts
            ),
        },
    }


def _artifact_path_index(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回不重复内容的紧凑路径级产物事实。"""

    by_path: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        path = str(item.get("path") or metadata.get("model_context_path") or "").strip()
        if not path:
            continue
        record = by_path.setdefault(
            path,
            {
                "path": path,
                "model_context_path": str(metadata.get("model_context_path") or "").strip(),
                "roles": [],
                "artifact_kinds": [],
                "source_tools": [],
                "statuses": [],
                "verification_relevance": [],
                "can_preview": False,
                "can_enter_model_context": False,
            },
        )
        _append_unique(record["roles"], item.get("role"))
        _append_unique(record["artifact_kinds"], item.get("artifact_kind") or item.get("kind"))
        _append_unique(record["source_tools"], item.get("source_tool") or item.get("tool"))
        _append_unique(record["statuses"], item.get("status"))
        _append_unique(record["verification_relevance"], item.get("verification_relevance"))
        if not record.get("model_context_path") and metadata.get("model_context_path"):
            record["model_context_path"] = str(metadata.get("model_context_path") or "").strip()
        record["can_preview"] = bool(record.get("can_preview")) or bool(item.get("can_preview"))
        record["can_enter_model_context"] = bool(record.get("can_enter_model_context")) or bool(
            item.get("can_enter_model_context")
        )
    return list(by_path.values())


def _append_unique(values: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _records_from_tool_event(
    workspace_path: str,
    event: dict[str, Any],
    event_index: int,
) -> list[dict[str, Any]]:
    tool_id = str(event.get("tool") or event.get("name") or "")
    status = _effective_event_status(tool_id, event)
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    records: list[dict[str, Any]] = []

    if status in {"success", "partial"}:
        for path in _event_paths(workspace_path, event):
            kind = _primary_artifact_kind(tool_id, output, path)
            role = _artifact_role(tool_id, output, kind, event)
            records.append(_make_record(
                artifact_kind=kind,
                role=role,
                path=path,
                status=status,
                source_tool=tool_id,
                source_task_id=str(event.get("task_id") or ""),
                source_event_index=event_index,
                metadata=_path_metadata(output),
            ))

        draft_id = str(output.get("draft_id") or "").strip()
        if draft_id:
            records.append(_make_record(
                artifact_kind="text_draft",
                role="draft",
                path=_relative_workspace_path(workspace_path, str(output.get("path") or "")),
                status=status,
                source_tool=tool_id,
                source_task_id=str(event.get("task_id") or ""),
                source_event_index=event_index,
                metadata=_path_metadata(output),
            ))

    visual_record = _record_from_visual_output(workspace_path, event, event_index)
    if visual_record:
        records.append(visual_record)

    debug_record = _record_from_debug_output(event, event_index)
    if debug_record:
        records.append(debug_record)

    if _looks_like_verification_event(event):
        verification_record = _record_from_verification_evidence(
            workspace_path,
            {
                "tool": tool_id,
                "path": _first_event_path(workspace_path, event),
                "status": status,
                "strength": event.get("declared_verification_strength")
                or output.get("verification_strength"),
                "modalities": output.get("modalities") or output.get("verification_modalities"),
            },
            source_event_index=event_index,
        )
        if verification_record:
            records.append(verification_record)

    return records


def _record_from_legacy_artifact(workspace_path: str, item: dict[str, Any]) -> dict[str, Any] | None:
    path = _relative_workspace_path(workspace_path, str(item.get("path") or ""))
    draft_id = str(item.get("draft_id") or "").strip()
    if not path and not draft_id:
        return None
    artifact_kind = str(item.get("artifact_kind") or item.get("kind") or "artifact").strip()
    role = _role_from_legacy(item, artifact_kind)
    return _make_record(
        artifact_kind=artifact_kind or "artifact",
        role=role,
        path=path,
        status=str(item.get("status") or "observed"),
        source_tool=str(item.get("source_tool") or item.get("tool") or ""),
        metadata=_path_metadata(item),
    )


def _record_from_visual_output(
    workspace_path: str,
    event: dict[str, Any],
    event_index: int,
) -> dict[str, Any] | None:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    summary = visual_evidence_summary(normalize_visual_evidence(output))
    if not summary:
        return None
    record = _record_from_visual_evidence(workspace_path, summary)
    if not record:
        return None
    record["status"] = _effective_event_status(str(event.get("tool") or ""), event)
    record["source_tool"] = str(event.get("tool") or "")
    record["tool"] = record["source_tool"]
    record["source_task_id"] = str(event.get("task_id") or "")
    record["source_event_index"] = event_index
    record["id"] = _record_id(record)
    return record


def _record_from_visual_evidence(workspace_path: str, item: dict[str, Any]) -> dict[str, Any] | None:
    summary = visual_evidence_summary(item)
    if not summary:
        return None
    path = _relative_workspace_path(workspace_path, str(summary.get("path") or ""))
    if not path:
        return None
    metadata = {
        key: summary.get(key)
        for key in (
            "source_type",
            "source_url",
            "source_path",
            "format",
            "width",
            "height",
            "size",
            "captured_at",
            "title",
            "status_code",
            "has_runtime_errors",
            "console_error_count",
            "page_error_count",
            "failed_request_count",
            "model_context_modality",
            "model_context_path",
        )
        if summary.get(key) not in (None, "")
    }
    model_context_path = _relative_workspace_path(
        workspace_path,
        str(summary.get("model_context_path") or ""),
    )
    if model_context_path:
        metadata["model_context_path"] = model_context_path
    return _make_record(
        artifact_kind=str(summary.get("artifact_kind") or "screenshot"),
        role="screenshot",
        path=path,
        status=str(item.get("status") or "observed"),
        source_tool=str(item.get("tool") or ""),
        metadata=metadata,
        can_enter_model_context=bool(summary.get("model_context_eligible")),
        verification_relevance="verification",
    )


def _record_from_debug_output(
    event: dict[str, Any],
    event_index: int,
) -> dict[str, Any] | None:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    summary = debug_session_summary(normalize_debug_session(output))
    if not summary:
        return None
    record = _record_from_debug_session(summary)
    if not record:
        return None
    record["status"] = _effective_event_status(str(event.get("tool") or ""), event)
    record["source_tool"] = str(event.get("tool") or "")
    record["tool"] = record["source_tool"]
    record["source_task_id"] = str(event.get("task_id") or "")
    record["source_event_index"] = event_index
    record["id"] = _record_id(record)
    return record


def _record_from_debug_session(item: dict[str, Any]) -> dict[str, Any] | None:
    summary = debug_session_summary(item)
    if not summary:
        return None
    command = str(summary.get("command") or "")
    if not command and summary.get("pid") is None and not summary.get("service"):
        return None
    metadata = {
        key: summary.get(key)
        for key in (
            "source_type",
            "command",
            "executable",
            "cwd",
            "pid",
            "exit_code",
            "timed_out",
            "timeout",
            "started_at",
            "finished_at",
            "duration_seconds",
            "stdout_chars",
            "stderr_chars",
            "stdout_truncated",
            "stderr_truncated",
            "service",
            "diagnostic_count",
            "heartbeat",
            "has_runtime_errors",
        )
        if summary.get(key) not in (None, "")
    }
    return _make_record(
        artifact_kind="command_log",
        role="log",
        status=str(item.get("status") or summary.get("status") or "observed"),
        source_tool=str(item.get("tool") or ""),
        metadata=metadata,
        can_preview=True,
        can_enter_model_context=True,
        verification_relevance="diagnostic",
    )


def _record_from_verification_evidence(
    workspace_path: str,
    item: dict[str, Any],
    *,
    source_event_index: int | None = None,
) -> dict[str, Any] | None:
    tool_id = str(item.get("tool") or "")
    path = _relative_workspace_path(workspace_path, str(item.get("path") or ""))
    strength = str(item.get("strength") or item.get("verification_strength") or "").strip()
    modalities = _string_list(item.get("modalities"))
    if not tool_id and not path and not strength and not modalities:
        return None
    metadata = {
        "strength": strength,
        "modalities": modalities,
    }
    query = str(item.get("query") or "").strip()
    if query:
        metadata["query"] = query
    event_index = source_event_index
    if event_index is None:
        event_index = _optional_int(item.get("source_event_index"))
    return _make_record(
        artifact_kind="verification",
        role="verification",
        path=path,
        status=str(item.get("status") or "success"),
        source_tool=tool_id,
        source_event_index=event_index,
        metadata=metadata,
        can_preview=bool(path),
        can_enter_model_context=bool(path),
        verification_relevance="verification",
    )


def _make_record(
    *,
    artifact_kind: str,
    role: str,
    path: str = "",
    url: str = "",
    status: str = "",
    source_tool: str = "",
    source_task_id: str = "",
    source_event_index: int | None = None,
    metadata: dict[str, Any] | None = None,
    can_preview: bool | None = None,
    can_enter_model_context: bool | None = None,
    verification_relevance: str = "",
) -> dict[str, Any]:
    normalized_kind = str(artifact_kind or "artifact").strip() or "artifact"
    normalized_role = str(role or "artifact").strip() or "artifact"
    normalized_path = str(path or "").replace("\\", "/")
    metadata = {
        key: value
        for key, value in (metadata or {}).items()
        if value not in (None, "")
    }
    record = {
        "schema_version": RUN_ARTIFACT_SCHEMA_VERSION,
        "kind": "run_artifact",
        "artifact_kind": normalized_kind,
        "role": normalized_role,
        "path": normalized_path,
        "url": str(url or ""),
        "status": str(status or "observed"),
        "source_tool": str(source_tool or ""),
        "tool": str(source_tool or ""),
        "source_task_id": str(source_task_id or ""),
        "source_event_index": source_event_index,
        "can_preview": _can_preview(
            artifact_kind=normalized_kind,
            role=normalized_role,
            path=normalized_path,
            explicit=can_preview,
        ),
        "can_enter_model_context": _can_enter_model_context(
            artifact_kind=normalized_kind,
            role=normalized_role,
            path=normalized_path,
            explicit=can_enter_model_context,
        ),
        "verification_relevance": verification_relevance
        or _verification_relevance(normalized_kind, normalized_role),
        "metadata": metadata,
    }
    record["id"] = _record_id(record)
    return record


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str, str, str, str], int] = {}
    for item in records:
        key = (
            str(item.get("artifact_kind") or ""),
            str(item.get("role") or ""),
            str(item.get("path") or ""),
            str(item.get("url") or ""),
            str(item.get("source_tool") or ""),
            str((item.get("metadata") or {}).get("draft_id") or ""),
        )
        if key in seen:
            existing = result[seen[key]]
            result[seen[key]] = _merge_duplicate_record(existing, item)
            continue
        seen[key] = len(result)
        result.append(item)
    return result


def _merge_duplicate_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    existing_metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
    incoming_metadata = incoming.get("metadata") if isinstance(incoming.get("metadata"), dict) else {}
    merged["metadata"] = _merge_metadata(existing_metadata, incoming_metadata)
    for flag in ("can_preview", "can_enter_model_context"):
        merged[flag] = bool(existing.get(flag)) or bool(incoming.get(flag))
    if not str(merged.get("url") or "").strip() and incoming.get("url"):
        merged["url"] = incoming.get("url")
    if not str(merged.get("status") or "").strip() and incoming.get("status"):
        merged["status"] = incoming.get("status")
    if not str(merged.get("verification_relevance") or "").strip() and incoming.get("verification_relevance"):
        merged["verification_relevance"] = incoming.get("verification_relevance")
    if not str(merged.get("source_task_id") or "").strip() and incoming.get("source_task_id"):
        merged["source_task_id"] = incoming.get("source_task_id")
    if merged.get("source_event_index") is None and incoming.get("source_event_index") is not None:
        merged["source_event_index"] = incoming.get("source_event_index")
    merged["id"] = _record_id(merged)
    return merged


def _merge_metadata(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = {**current, **value}
        else:
            merged[key] = value
    return merged


def _record_id(record: dict[str, Any]) -> str:
    material = "\x1f".join(
        str(record.get(key) or "")
        for key in (
            "artifact_kind",
            "role",
            "path",
            "url",
            "source_tool",
            "source_task_id",
            "source_event_index",
        )
    )
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    material += "\x1f" + str(metadata.get("draft_id") or "")
    return "artifact_" + sha1(material.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _primary_artifact_kind(tool_id: str, output: dict[str, Any], path: str) -> str:
    explicit = str(output.get("artifact_kind") or "").strip()
    if explicit:
        return explicit
    artifacts = _string_list(output.get("artifacts"))
    for item in artifacts:
        kind = item.lower()
        if kind not in {"visual_evidence", "debug_session"}:
            return kind
    output_type = str(output.get("type") or "").strip()
    if output_type in {"file_write", "file_change_set"}:
        return "file"
    if tool_id.startswith("document."):
        return "document"
    if is_write_tool(tool_id):
        return "file"
    ext_kind = _artifact_kind_from_path(path)
    if ext_kind:
        return ext_kind
    return artifacts[0] if artifacts else "artifact"


def _artifact_role(
    tool_id: str,
    output: dict[str, Any],
    artifact_kind: str,
    event: dict[str, Any],
) -> str:
    roles = {
        item.lower()
        for item in [
            *_string_list(event.get("declared_roles")),
            *_string_list(output.get("roles")),
        ]
    }
    effects = {
        item.lower()
        for item in [
            *_string_list(event.get("declared_effects")),
            *_string_list(output.get("effects")),
        ]
    }
    kind = artifact_kind.lower()
    if roles & {"deliverable", "target_deliverable", "final", "final_artifact"}:
        return "final"
    if roles & {"draft", "working_draft"} or kind in _DRAFT_KINDS:
        return "draft"
    if kind in _VISUAL_KINDS:
        return "screenshot" if "screenshot" in kind or kind in {"image", "render"} else "preview"
    if kind in _LOG_KINDS:
        return "log"
    if roles & {"verification", "evidence"} or _looks_like_verification_event(event):
        return "verification"
    if is_write_tool(tool_id) or effects & {"file_write", "file_change", "workspace_write"}:
        return "final"
    if roles & {"temporary", "intermediate"}:
        return "intermediate"
    return "artifact"


def _role_from_legacy(item: dict[str, Any], artifact_kind: str) -> str:
    role = str(item.get("role") or "").strip()
    if role:
        return role
    kind = artifact_kind.lower()
    if kind in _DRAFT_KINDS:
        return "draft"
    if kind in _VISUAL_KINDS:
        return "screenshot"
    if kind in _LOG_KINDS:
        return "log"
    return "final"


def _path_metadata(output: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field in (
        "size",
        "created",
        "changed",
        "deleted",
        "encoding",
        "draft_id",
        "format",
        "width",
        "height",
        "captured_at",
        "text_chars",
        "line_count",
        "output_chars",
    ):
        if field in output:
            metadata[field] = output.get(field)
    validation = output.get("validation")
    if isinstance(validation, dict):
        metadata["validation"] = {
            key: validation.get(key)
            for key in ("valid", "validator", "text_chars", "line_count")
            if key in validation
        }
    return metadata


def _event_paths(workspace_path: str, event: dict[str, Any]) -> list[str]:
    tool_id = str(event.get("tool") or event.get("name") or "")
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    output_values: list[str] = []
    output_paths = output.get("paths") if isinstance(output.get("paths"), list) else []
    output_values.extend(str(item) for item in output_paths if str(item or "").strip())
    changed_paths = output.get("changed_paths") if isinstance(output.get("changed_paths"), list) else []
    output_values.extend(str(item) for item in changed_paths if str(item or "").strip())
    files = output.get("files") if isinstance(output.get("files"), list) else []
    for item in files:
        if isinstance(item, dict) and item.get("path"):
            output_values.append(str(item.get("path") or ""))
        elif str(item or "").strip():
            output_values.append(str(item))
    for field in _PATH_FIELDS:
        if output.get(field):
            output_values.append(str(output.get(field) or ""))
    summary = visual_evidence_summary(normalize_visual_evidence(output))
    if summary and summary.get("path"):
        output_values.append(str(summary.get("path") or ""))
    if output_values:
        return _unique_strings(_relative_workspace_path(workspace_path, item) for item in output_values)

    input_values: list[str] = []
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    for field in _PATH_FIELDS:
        if event_input.get(field):
            input_values.append(str(event_input.get(field) or ""))
    if is_write_tool(tool_id):
        return _unique_strings(_relative_workspace_path(workspace_path, item) for item in input_values)
    return []


def _first_event_path(workspace_path: str, event: dict[str, Any]) -> str:
    paths = _event_paths(workspace_path, event)
    return paths[0] if paths else ""


def _artifact_kind_from_path(path: str) -> str:
    suffix = Path(str(path).replace("\\", "/")).suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    if suffix in _DOCUMENT_EXTENSIONS:
        if suffix == ".pdf":
            return "pdf"
        return suffix.lstrip(".")
    if suffix in _TEXT_EXTENSIONS:
        if suffix in {".html", ".htm"}:
            return "html"
        if suffix in {".md", ".markdown"}:
            return "markdown"
        return "text_file"
    return ""


def _can_preview(
    *,
    artifact_kind: str,
    role: str,
    path: str,
    explicit: bool | None,
) -> bool:
    if explicit is not None:
        return bool(explicit)
    kind = artifact_kind.lower()
    if role in {"log", "verification"}:
        return True
    return bool(path) and (
        kind in _VISUAL_KINDS
        or kind in _MODEL_CONTEXT_TEXT_KINDS
        or kind in _DOCUMENT_EXTENSIONS
        or kind in {"file", "docx", "pptx", "xlsx", "pdf", "image"}
    )


def _can_enter_model_context(
    *,
    artifact_kind: str,
    role: str,
    path: str,
    explicit: bool | None,
) -> bool:
    if explicit is not None:
        return bool(explicit)
    kind = artifact_kind.lower()
    if role == "log":
        return True
    if kind in _VISUAL_KINDS:
        return bool(path)
    if kind in _MODEL_CONTEXT_TEXT_KINDS:
        return True
    return False


def _verification_relevance(artifact_kind: str, role: str) -> str:
    kind = artifact_kind.lower()
    if role in {"verification", "screenshot", "preview"} or kind in _EVIDENCE_KINDS:
        return "verification"
    if role == "log":
        return "diagnostic"
    if role in {"final", "draft"}:
        return "deliverable"
    return "context"


def _looks_like_verification_event(event: dict[str, Any]) -> bool:
    tool_id = str(event.get("tool") or "")
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    roles = {
        item.lower()
        for item in [
            *_string_list(event.get("declared_roles")),
            *_string_list(output.get("roles")),
        ]
    }
    if roles & {"verification", "evidence"}:
        return True
    return bool(
        event.get("declared_verification_strength")
        or output.get("verification_strength")
        or tool_id.startswith("preview.")
        or tool_id.startswith("desktop.")
        or tool_id in {"shell.run_command", "code.search"}
    )


def _effective_event_status(tool_id: str, event: dict[str, Any]) -> str:
    status = str(event.get("status") or "")
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if tool_id == "shell.run_command":
        if output.get("timed_out") is True:
            return "failure"
        try:
            exit_code = int(output.get("exit_code", 0) or 0)
        except (TypeError, ValueError):
            exit_code = 0
        if exit_code != 0:
            return "failure"
    if output.get("error") is True:
        return "failure"
    output_status = str(output.get("status") or "").strip().lower()
    if (
        status == "partial"
        or output_status in {"partial", "partial_resumable"}
        or output.get("partial_resumable") is True
    ):
        return "partial"
    return status or "observed"


def _relative_workspace_path(workspace_path: str, value: str) -> str:
    if not str(value or "").strip():
        return ""
    normalized_workspace = workspace_path.replace("\\", "/").rstrip("/")
    normalized_value = value.replace("\\", "/")
    if normalized_workspace:
        workspace_prefix = normalized_workspace.lower() + "/"
        value_lower = normalized_value.lower()
        if value_lower == normalized_workspace.lower():
            return "."
        if value_lower.startswith(workspace_prefix):
            return normalized_value[len(normalized_workspace) + 1:]
    try:
        workspace = Path(workspace_path).resolve()
        path = Path(value)
        if not path.is_absolute():
            return str(path).replace("\\", "/")
        return str(path.resolve().relative_to(workspace)).replace("\\", "/")
    except (OSError, ValueError):
        return value.replace("\\", "/")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
