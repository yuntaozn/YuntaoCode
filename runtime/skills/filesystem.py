from __future__ import annotations

import asyncio
import html
import json
import shutil
from pathlib import Path
from typing import Any

from runtime.text_artifacts import (
    append_text_chunk as append_text_chunk_record,
    create_text_draft_record,
    inspect_text_draft_record,
    load_text_draft,
    save_text_draft,
    text_draft_content,
    text_draft_stats,
)
from runtime.text_encoding import (
    detect_text_encoding,
    read_text_with_encoding,
    text_encoding_risks,
    write_text_with_encoding,
)
from runtime.tool_registry import ToolRegistry, ToolSpec

MAX_READ_LINES = 500
TEXT_WRITE_CHUNK_MAX_CHARS = 8000
TEXT_TRANSFORMS = frozenset({
    "html_unescape",
})
TEXT_DRAFT_VALIDATORS = frozenset({
    "auto",
    "none",
    "html",
    "json",
    "python",
})


async def scan_folder(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    root = context.path_guard.resolve(input_data.get("path") or ".")
    if not root.exists() or not root.is_dir():
        raise ValueError(f"folder not found: {root}")

    max_depth = int(input_data.get("max_depth", 2))
    include_extensions = input_data.get("include_extensions") or []
    include_extensions = {ext.lower() for ext in include_extensions}
    result = await asyncio.to_thread(scan_folder_sync, root, max_depth, include_extensions)
    context.log("info", "folder scanned", {
        "files": result["file_count"],
        "folders": result["folder_count"],
    })
    return result


def scan_folder_sync(root: Path, max_depth: int, include_extensions: set[str]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    folders: list[str] = []

    for path in root.rglob("*"):
        rel = path.relative_to(root)
        depth = len(rel.parts)
        if depth > max_depth:
            continue
        if path.is_dir():
            folders.append(str(rel))
            continue
        if include_extensions and path.suffix.lower() not in include_extensions:
            continue
        files.append({
            "path": str(rel),
            "size": path.stat().st_size,
            "extension": path.suffix.lower(),
        })

    return {
        "root": str(root),
        "folders": folders[:500],
        "files": files[:1000],
        "folder_count": len(folders),
        "file_count": len(files),
    }


async def read_text_preview(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    if not path.exists() or not path.is_file():
        raise ValueError(f"file not found: {path}")

    max_bytes = int(input_data.get("max_bytes", 12000))
    return await asyncio.to_thread(read_text_preview_sync, path, max_bytes, input_data.get("encoding"))


def read_text_preview_sync(path: Path, max_bytes: int, encoding: str | None) -> dict[str, Any]:
    all_bytes = path.read_bytes()
    raw = all_bytes[:max_bytes]
    detected_encoding = str(encoding or detect_text_encoding(all_bytes))
    text = raw.decode(detected_encoding, errors="replace")
    try:
        full_text = all_bytes.decode(detected_encoding, errors="replace")
    except (LookupError, ValueError):
        full_text = text
    return {
        "path": str(path),
        "size": len(all_bytes),
        "encoding": detected_encoding,
        "truncated": len(all_bytes) > max_bytes,
        "text": text,
        "integrity": inspect_text_artifact_integrity(path, full_text),
        "encoding_risks": text_encoding_risks(path, full_text, detected_encoding),
    }


# ---------------------------------------------------------------------------
# read_file：带行号读取完整文件
# ---------------------------------------------------------------------------

async def read_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    if not path.exists() or not path.is_file():
        raise ValueError(f"file not found: {path}")
    start_line = input_data.get("start_line")
    end_line = input_data.get("end_line")
    return await asyncio.to_thread(read_file_sync, path, start_line, end_line)


def _detect_encoding(raw: bytes) -> str:
    return detect_text_encoding(raw)


def read_file_sync(
    path: Path,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    text, encoding = read_text_with_encoding(path)
    all_lines = text.splitlines(keepends=True)
    total_lines = len(all_lines)

    s = max(1, int(start_line)) if start_line else 1
    e = min(total_lines, int(end_line)) if end_line else total_lines
    if e - s + 1 > MAX_READ_LINES:
        e = s + MAX_READ_LINES - 1

    selected = all_lines[s - 1 : e]
    width = len(str(e))
    numbered = "".join(
        f"{str(i).rjust(width)}| {line}" for i, line in enumerate(selected, start=s)
    )
    # 不带行号的原始内容；构建 edit_file 的 old_text 时使用。
    raw_content = "".join(selected)
    integrity = inspect_text_artifact_integrity(path, text)

    has_more = e < total_lines
    next_start_line = e + 1 if has_more else None
    next_end_line = min(total_lines, e + MAX_READ_LINES) if has_more else None

    result: dict[str, Any] = {
        "path": str(path),
        "total_lines": total_lines,
        "start_line": s,
        "end_line": min(e, total_lines),
        "truncated": has_more,
        "remaining_lines": max(0, total_lines - e),
        "next_start_line": next_start_line,
        "next_end_line": next_end_line,
        "suggested_next_call": (
            {
                "path": str(path),
                "start_line": next_start_line,
                "end_line": next_end_line,
            }
            if has_more
            else None
        ),
        "encoding": encoding,
        "content": numbered,
        "raw_content": raw_content,
        "integrity": integrity,
        "encoding_risks": text_encoding_risks(path, text, encoding),
        "usage_hint": (
            "content 字段带行号前缀，仅用于显示参考。"
            "构造 code.edit_file 的 old_text / new_text 时，请基于 raw_content（不含行号前缀）的文本。"
        ),
    }
    return result


# ---------------------------------------------------------------------------
# write_file：创建或覆盖文件
# ---------------------------------------------------------------------------

async def write_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path_value = input_data.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(
            "path is required; provide an explicit file path inside the current workspace, "
            "for example ./notes.md or D:\\code\\project\\notes.md"
        )
    path = context.path_guard.resolve(path_value)
    content = input_data.get("content")
    if content is None:
        raise ValueError("content is required")
    content_text = str(content)
    create_dirs = input_data.get("create_dirs", True)
    return await asyncio.to_thread(write_file_sync, path, content_text, bool(create_dirs), context)


async def delete_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path_value = input_data.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("path is required")
    path = context.path_guard.resolve(path_value)
    missing_ok = bool(input_data.get("missing_ok", False))
    return await asyncio.to_thread(delete_file_sync, path, missing_ok, context)


async def copy_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    source_value = input_data.get("source_path") or input_data.get("source")
    if not isinstance(source_value, str) or not source_value.strip():
        raise ValueError("source_path is required")
    destination_value = (
        input_data.get("destination_path")
        or input_data.get("destination")
        or input_data.get("path")
    )
    if not isinstance(destination_value, str) or not destination_value.strip():
        raise ValueError("destination_path is required")
    source = context.path_guard.resolve(source_value)
    destination = context.path_guard.resolve(destination_value)
    create_dirs = bool(input_data.get("create_dirs", True))
    overwrite = bool(input_data.get("overwrite", True))
    return await asyncio.to_thread(
        copy_file_sync,
        source,
        destination,
        create_dirs,
        overwrite,
        context,
    )


async def apply_changes(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    operations = input_data.get("operations") or input_data.get("changes")
    create_dirs = bool(input_data.get("create_dirs", True))
    reason = str(input_data.get("reason") or "").strip()
    return await asyncio.to_thread(apply_changes_sync, operations, create_dirs, reason, context)


async def write_temp_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    temp_dir = getattr(context, "temp_dir", None)
    if temp_dir is None:
        raise ValueError("task temp directory is not available")
    path = _resolve_temp_file_path(Path(temp_dir), input_data.get("path") or input_data.get("name") or "task.txt")
    content = input_data.get("content")
    if content is None:
        raise ValueError("content is required")
    create_dirs = input_data.get("create_dirs", True)
    return await asyncio.to_thread(write_temp_file_sync, path, str(content), bool(create_dirs), Path(temp_dir), context)


async def transform_text(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path_value = input_data.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("path is required")
    transform = str(input_data.get("transform") or "").strip()
    if transform not in TEXT_TRANSFORMS:
        raise ValueError(
            "unsupported text transform; supported transforms: "
            + ", ".join(sorted(TEXT_TRANSFORMS))
        )
    path = context.path_guard.resolve(path_value)
    if not path.exists() or not path.is_file():
        raise ValueError(f"file not found: {path}")
    return await asyncio.to_thread(transform_text_sync, path, transform, context)


async def create_text_draft(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    data_dir = _text_artifact_data_dir(context)
    record = create_text_draft_record(
        title=str(input_data.get("title") or "Untitled Text Artifact"),
        path_hint=str(input_data.get("path_hint") or input_data.get("output_path") or ""),
        language=str(input_data.get("language") or ""),
        metadata=input_data.get("metadata") if isinstance(input_data.get("metadata"), dict) else {},
    )
    initial_content = str(input_data.get("content") or "")
    if initial_content:
        append_text_chunk_record(
            record,
            content=initial_content,
            label="initial",
            metadata={"source": "create_text_draft"},
            data_dir=data_dir,
        )
    record = save_text_draft(data_dir, record)
    return {
        "type": "text_artifact_draft",
        "draft_id": record["draft_id"],
        "title": record["title"],
        "path_hint": record.get("path_hint") or "",
        "language": record.get("language") or "",
        "stats": text_draft_stats(record, data_dir=data_dir),
        "message": (
            "file-backed text draft created; append complete bounded chunks with "
            "filesystem.append_text_chunk, inspect progress, then finalize with "
            "filesystem.finalize_text_file"
        ),
    }


async def append_text_chunk(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    data_dir = _text_artifact_data_dir(context)
    record = load_text_draft(data_dir, str(input_data.get("draft_id") or ""))
    sequence_value = input_data.get("sequence")
    sequence = int(sequence_value) if sequence_value is not None else None
    content = str(input_data.get("content") or "")
    chunk = append_text_chunk_record(
        record,
        content=content,
        label=str(input_data.get("label") or ""),
        sequence=sequence,
        metadata=input_data.get("metadata") if isinstance(input_data.get("metadata"), dict) else {},
        data_dir=data_dir,
    )
    record = save_text_draft(data_dir, record)
    return {
        "type": "text_artifact_draft",
        "draft_id": record["draft_id"],
        "chunk_id": chunk["chunk_id"],
        "stats": text_draft_stats(record, data_dir=data_dir),
    }


async def inspect_text_draft(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    data_dir = _text_artifact_data_dir(context)
    record = load_text_draft(data_dir, str(input_data.get("draft_id") or ""))
    preview_chars = int(input_data.get("preview_chars") or 1200)
    return inspect_text_draft_record(record, data_dir=data_dir, preview_chars=preview_chars)


async def finalize_text_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    data_dir = _text_artifact_data_dir(context)
    record = load_text_draft(data_dir, str(input_data.get("draft_id") or ""))
    output_path_value = (
        input_data.get("output_path")
        or input_data.get("path")
        or record.get("path_hint")
    )
    if not output_path_value:
        raise ValueError("output_path is required")
    path = context.path_guard.resolve(str(output_path_value))
    content = text_draft_content(record, data_dir=data_dir)
    if not content:
        raise ValueError("text draft has no content")
    validator = str(input_data.get("validator") or "auto").strip().lower() or "auto"
    validation = validate_text_artifact_content(path, content, validator=validator)
    if not validation["valid"]:
        raise ValueError("text draft validation failed: " + ", ".join(validation["issues"]))
    create_dirs = input_data.get("create_dirs", True)
    output = await asyncio.to_thread(write_file_sync, path, content, bool(create_dirs), context)
    output.update({
        "type": "file_write",
        "draft_id": record["draft_id"],
        "draft_stats": text_draft_stats(record, data_dir=data_dir),
        "validation": validation,
        "artifact_kind": "text_file",
    })
    return output


def transform_text_sync(path: Path, transform: str, context: Any) -> dict[str, Any]:
    raw = path.read_bytes()
    original, encoding = read_text_with_encoding(path)
    before_integrity = inspect_text_artifact_integrity(path, original)

    if transform == "html_unescape":
        transformed = html.unescape(original)
    else:
        raise ValueError(f"unsupported text transform: {transform}")

    changed = transformed != original
    after_integrity = inspect_text_artifact_integrity(path, transformed)
    if after_integrity.get("checked") and not after_integrity.get("valid"):
        issues = ", ".join(str(item) for item in after_integrity.get("issues") or [])
        raise ValueError(f"transformed text failed integrity check: {issues}")

    if changed:
        if callable(getattr(context, "backup_file", None)):
            context.backup_file(path)
        encoding = write_text_with_encoding(path, transformed, encoding)
    context.log("info", f"text transform {transform} {'changed' if changed else 'made no changes'}: {path}")
    return {
        "path": str(path),
        "transform": transform,
        "changed": changed,
        "encoding": encoding,
        "before_size": len(raw),
        "after_size": len(transformed.encode(encoding, errors="replace")),
        "integrity_before": before_integrity,
        "integrity": after_integrity,
        "encoding_risks": text_encoding_risks(path, transformed, encoding),
    }


def write_file_sync(path: Path, content: str, create_dirs: bool, context: Any) -> dict[str, Any]:
    created = not path.exists()
    original_encoding = "utf-8"
    if path.exists() and path.is_file():
        try:
            original_encoding = detect_text_encoding(path.read_bytes())
        except OSError:
            original_encoding = "utf-8"
    integrity = inspect_text_artifact_integrity(path, content)
    if integrity.get("checked") and not integrity.get("valid"):
        issues = ", ".join(str(item) for item in integrity.get("issues") or [])
        raise ValueError(
            f"refusing incomplete {path.suffix.lower() or 'text'} overwrite: {issues}. "
            "Provide the complete file content or use a targeted edit tool."
        )

    if callable(getattr(context, "backup_file", None)):
        context.backup_file(path)

    if create_dirs:
        path.parent.mkdir(parents=True, exist_ok=True)

    encoding = write_text_with_encoding(path, content, "utf-8" if created else original_encoding)
    context.log("info", f"{'created' if created else 'overwritten'}: {path}")
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "created": created,
        "encoding": encoding,
        "integrity": integrity,
        "encoding_risks": text_encoding_risks(path, content, encoding),
    }


def delete_file_sync(path: Path, missing_ok: bool, context: Any) -> dict[str, Any]:
    if not path.exists():
        if missing_ok:
            context.log("info", f"file already absent: {path}")
            return {
                "path": str(path),
                "deleted": False,
                "existed": False,
                "missing_ok": True,
                "effects": [],
                "roles": ["verification"],
                "verification_strength": "standard",
                "artifact_kind": "file_delete",
            }
        raise ValueError(f"file not found: {path}")
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")

    size = path.stat().st_size
    if callable(getattr(context, "backup_file", None)):
        context.backup_file(path)
    path.unlink()
    deleted = not path.exists()
    context.log("info", f"deleted file: {path}")
    return {
        "path": str(path),
        "deleted": deleted,
        "existed": True,
        "size": size,
        "effects": ["file_delete", "local_state_change"],
        "roles": ["deliverable", "verification"],
        "verification_strength": "standard",
        "artifact_kind": "file_delete",
    }


def copy_file_sync(
    source: Path,
    destination: Path,
    create_dirs: bool,
    overwrite: bool,
    context: Any,
) -> dict[str, Any]:
    if not source.exists() or not source.is_file():
        raise ValueError(f"source file not found: {source}")
    if destination.exists() and destination.is_dir():
        raise ValueError(f"destination is a directory: {destination}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination already exists: {destination}")
    if create_dirs:
        destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.parent.exists():
        raise FileNotFoundError(f"destination folder not found: {destination.parent}")
    existed = destination.exists()
    if existed and callable(getattr(context, "backup_file", None)):
        context.backup_file(destination)
    shutil.copy2(source, destination)
    source_size = source.stat().st_size
    destination_size = destination.stat().st_size
    valid = source_size == destination_size
    context.log("info", "file copied", {
        "source_path": str(source),
        "destination_path": str(destination),
        "size": destination_size,
        "overwritten": existed,
    })
    return {
        "type": "file_copy",
        "source_path": str(source),
        "path": str(destination),
        "destination_path": str(destination),
        "paths": [str(destination)],
        "source_size": source_size,
        "size": destination_size,
        "destination_size": destination_size,
        "created": not existed,
        "overwritten": existed,
        "integrity": {
            "checked": True,
            "valid": valid,
            "source_size": source_size,
            "destination_size": destination_size,
        },
        "artifacts": ["file"],
        "effects": ["file_write", "local_state_change"],
        "roles": ["deliverable", "verification"],
        "verification_strength": "standard" if valid else "none",
    }


def apply_changes_sync(operations: Any, create_dirs: bool, reason: str, context: Any) -> dict[str, Any]:
    if not isinstance(operations, list) or not operations:
        raise ValueError("operations is required and must be a non-empty list")

    states: dict[Path, dict[str, Any]] = {}
    operation_results: list[dict[str, Any]] = []

    for index, raw in enumerate(operations, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"operation {index} must be an object")
        operation_type = _normalize_change_operation_type(raw.get("type") or raw.get("operation"))
        path = _change_operation_path(raw, context)
        state = states.get(path)
        if state is None:
            state = _load_change_file_state(path)
            states[path] = state

        if operation_type in {"create_file", "overwrite_file"}:
            content = _operation_content(raw, index)
            if (
                operation_type == "create_file"
                and state["final_exists"]
                and not bool(raw.get("overwrite", False))
            ):
                raise ValueError(f"operation {index} cannot create existing file: {path}")
            _validate_text_artifact_integrity(path, content)
            created = not state["final_exists"]
            before_text = state.get("text") or ""
            state.update({
                "text": content,
                "final_exists": True,
                "deleted": False,
                "encoding": state.get("encoding") or "utf-8",
            })
            operation_results.append({
                "index": index,
                "type": operation_type,
                "path": str(path),
                "created": created,
                "changed": created or before_text != content,
                "text_chars": len(content),
            })
            continue

        if operation_type == "replace_text":
            if not state["final_exists"] or state.get("deleted"):
                raise ValueError(f"operation {index} cannot replace text in missing file: {path}")
            old_text = str(raw.get("old_text") or raw.get("oldText") or "")
            if not old_text:
                raise ValueError(f"operation {index} old_text is required")
            if "new_text" in raw:
                new_text = str(raw.get("new_text") or "")
            elif "newText" in raw:
                new_text = str(raw.get("newText") or "")
            else:
                new_text = str(raw.get("replacement") or "")
            replace_all = bool(raw.get("replace_all", False))
            expected = int(raw.get("expected_replacements") or (0 if replace_all else 1))
            current_text = str(state.get("text") or "")
            count = current_text.count(old_text)
            if count == 0:
                raise ValueError(f"operation {index} old_text not found in file: {path}")
            if not replace_all and count != expected:
                raise ValueError(
                    f"operation {index} old_text matches {count} locations in {path}; "
                    "provide a more specific old_text or set replace_all=true"
                )
            limit = count if replace_all else expected
            updated_text = current_text.replace(old_text, new_text, limit)
            _validate_text_artifact_integrity(path, updated_text)
            state.update({"text": updated_text, "final_exists": True, "deleted": False})
            operation_results.append({
                "index": index,
                "type": operation_type,
                "path": str(path),
                "matched": count,
                "replaced": limit,
                "changed": updated_text != current_text,
            })
            continue

        if operation_type == "delete_file":
            missing_ok = bool(raw.get("missing_ok", False))
            if not state["final_exists"]:
                if not missing_ok:
                    raise ValueError(f"operation {index} file not found: {path}")
                operation_results.append({
                    "index": index,
                    "type": operation_type,
                    "path": str(path),
                    "deleted": False,
                    "existed": False,
                    "missing_ok": True,
                    "changed": False,
                })
                continue
            state.update({"text": "", "final_exists": False, "deleted": True})
            operation_results.append({
                "index": index,
                "type": operation_type,
                "path": str(path),
                "deleted": True,
                "existed": True,
                "missing_ok": missing_ok,
                "changed": True,
            })
            continue

        raise ValueError(f"operation {index} has unsupported type: {operation_type}")

    changed_paths: list[str] = []
    created_paths: list[str] = []
    updated_paths: list[str] = []
    deleted_paths: list[str] = []
    encoding_risks: list[dict[str, Any]] = []

    for path, state in states.items():
        original_exists = bool(state["original_exists"])
        original_text = str(state.get("original_text") or "")
        final_exists = bool(state["final_exists"])
        final_text = str(state.get("text") or "")
        if final_exists and (not original_exists or original_text != final_text):
            if callable(getattr(context, "backup_file", None)):
                context.backup_file(path)
            if create_dirs:
                path.parent.mkdir(parents=True, exist_ok=True)
            encoding = _write_text_preserving_encoding(path, final_text, str(state.get("encoding") or "utf-8"))
            risks = text_encoding_risks(path, final_text, encoding)
            if risks:
                encoding_risks.append({"path": str(path), "encoding": encoding, "risks": risks})
            changed_paths.append(str(path))
            if original_exists:
                updated_paths.append(str(path))
                context.log("info", f"updated file through change set: {path}")
            else:
                created_paths.append(str(path))
                context.log("info", f"created file through change set: {path}")
            continue
        if not final_exists and original_exists:
            if callable(getattr(context, "backup_file", None)):
                context.backup_file(path)
            if path.exists():
                if not path.is_file():
                    raise ValueError(f"refusing to delete non-file path: {path}")
                path.unlink()
            changed_paths.append(str(path))
            deleted_paths.append(str(path))
            context.log("info", f"deleted file through change set: {path}")

    return {
        "type": "file_change_set",
        "reason": reason,
        "operation_count": len(operations),
        "changed_file_count": len(changed_paths),
        "paths": changed_paths,
        "changed_paths": changed_paths,
        "created_paths": created_paths,
        "updated_paths": updated_paths,
        "deleted_paths": deleted_paths,
        "operations": operation_results,
        "effects": ["file_write", "file_delete", "local_state_change"],
        "roles": ["deliverable", "verification"],
        "verification_strength": "standard",
        "artifact_kind": "file_change_set",
        "encoding_risks": encoding_risks,
    }


def _normalize_change_operation_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "add": "create_file",
        "create": "create_file",
        "write": "overwrite_file",
        "write_file": "overwrite_file",
        "overwrite": "overwrite_file",
        "update": "overwrite_file",
        "replace": "replace_text",
        "replace_in_file": "replace_text",
        "delete": "delete_file",
        "remove": "delete_file",
    }
    return aliases.get(normalized, normalized)


def _change_operation_path(operation: dict[str, Any], context: Any) -> Path:
    path_value = operation.get("path") or operation.get("output_path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("each operation requires path")
    path = context.path_guard.resolve(path_value)
    if path.exists() and path.is_dir():
        raise ValueError(f"operation path is a directory, not a file: {path}")
    return path


def _operation_content(operation: dict[str, Any], index: int) -> str:
    if "content" not in operation:
        raise ValueError(f"operation {index} content is required")
    return str(operation.get("content") or "")


def _load_change_file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "original_exists": False,
            "final_exists": False,
            "deleted": False,
            "text": "",
            "original_text": "",
            "encoding": "utf-8",
        }
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")
    text, encoding = read_text_with_encoding(path)
    return {
        "original_exists": True,
        "final_exists": True,
        "deleted": False,
        "text": text,
        "original_text": text,
        "encoding": encoding,
    }


def _validate_text_artifact_integrity(path: Path, content: str) -> None:
    integrity = inspect_text_artifact_integrity(path, content)
    if integrity.get("checked") and not integrity.get("valid"):
        issues = ", ".join(str(item) for item in integrity.get("issues") or [])
        raise ValueError(
            f"refusing incomplete {path.suffix.lower() or 'text'} change: {issues}. "
            "Provide complete content or use a narrower edit."
        )


def _write_text_preserving_encoding(path: Path, text: str, encoding: str) -> str:
    return write_text_with_encoding(path, text, encoding)


def inspect_text_artifact_integrity(path: Path, content: str) -> dict[str, Any]:
    """在不判断语义的前提下检测明显被截断的整文档覆盖写入。"""
    suffix = path.suffix.lower()
    text = str(content or "")
    lowered = text.lower()
    issues: list[str] = []
    checked = False

    real_html = "<!doctype html" in lowered or "<html" in lowered
    escaped_html = "&lt;!doctype html" in lowered or "&lt;html" in lowered
    if suffix in {".html", ".htm"} and (real_html or escaped_html):
        checked = True
        if escaped_html and not real_html:
            issues.append("html appears escaped as text")
        if real_html:
            if "</body>" not in lowered:
                issues.append("missing </body>")
            if "</html>" not in lowered:
                issues.append("missing </html>")
            if lowered.count("<script") != lowered.count("</script>"):
                issues.append("unbalanced <script> tags")
            if lowered.count("<style") != lowered.count("</style>"):
                issues.append("unbalanced <style> tags")

    return {
        "checked": checked,
        "valid": not issues,
        "issues": issues,
        "kind": suffix.lstrip(".") or "text",
    }


def _text_artifact_data_dir(context: Any) -> Path:
    settings = getattr(context, "settings", None)
    data_dir = getattr(settings, "data_dir", None)
    if data_dir:
        return Path(data_dir)
    temp_dir = getattr(context, "temp_dir", None)
    if temp_dir:
        return Path(temp_dir) / "runtime-data"
    raise RuntimeError("text artifact draft tools require settings.data_dir or context.temp_dir")


def validate_text_artifact_content(path: Path, content: str, *, validator: str = "auto") -> dict[str, Any]:
    validator = str(validator or "auto").strip().lower() or "auto"
    if validator not in TEXT_DRAFT_VALIDATORS:
        raise ValueError(
            "unsupported validator; supported validators: "
            + ", ".join(sorted(TEXT_DRAFT_VALIDATORS))
        )
    suffix = path.suffix.lower()
    effective = validator
    if effective == "auto":
        if suffix in {".html", ".htm"}:
            effective = "html"
        elif suffix == ".json":
            effective = "json"
        elif suffix == ".py":
            effective = "python"
        else:
            effective = "none"

    issues: list[str] = []
    integrity = inspect_text_artifact_integrity(path, content)
    if effective == "html":
        if integrity.get("checked") and not integrity.get("valid"):
            issues.extend(str(item) for item in integrity.get("issues") or [])
    elif effective == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            issues.append(f"invalid json: line {exc.lineno} column {exc.colno}")
    elif effective == "python":
        try:
            compile(content, str(path), "exec")
        except SyntaxError as exc:
            issues.append(f"invalid python syntax: line {exc.lineno}")

    return {
        "validator": effective,
        "valid": not issues,
        "issues": issues,
        "integrity": integrity,
        "text_chars": len(content),
        "line_count": len(content.splitlines()),
    }


def write_temp_file_sync(path: Path, content: str, create_dirs: bool, temp_dir: Path, context: Any) -> dict[str, Any]:
    created = not path.exists()
    if create_dirs:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    context.log("info", f"temporary file {'created' if created else 'overwritten'}: {path}")
    return {
        "path": str(path),
        "relative_path": str(path.relative_to(temp_dir.resolve())),
        "temp_dir": str(temp_dir.resolve()),
        "size": path.stat().st_size,
        "created": created,
        "artifact_kind": "task_temp_file",
    }


def _resolve_temp_file_path(temp_dir: Path, raw_path: Any) -> Path:
    path_text = str(raw_path or "task.txt").strip()
    if not path_text:
        path_text = "task.txt"
    candidate = Path(path_text)
    if candidate.is_absolute():
        raise ValueError("temporary file path must be relative to the task temp directory")
    resolved_temp = temp_dir.resolve()
    resolved = (resolved_temp / candidate).resolve()
    try:
        resolved.relative_to(resolved_temp)
    except ValueError as exc:
        raise ValueError("temporary file path must stay inside the task temp directory") from exc
    return resolved


def register_filesystem_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="filesystem.scan_folder",
            name="扫描本地目录",
            description="在允许的工作区内扫描目录结构和文件清单。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_depth": {"type": "integer", "default": 2},
                    "include_extensions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path"],
            },
            capability="filesystem.local_files",
            artifacts=["directory_listing"],
            roles=["evidence"],
            verification_strength="weak",
        ),
        scan_folder,
    )
    registry.register(
        ToolSpec(
            id="filesystem.read_text_preview",
            name="读取文本预览",
            description="读取允许工作区内的文本文件前若干字节。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer", "default": 12000},
                    "encoding": {"type": "string", "default": "utf-8"},
                },
                "required": ["path"],
            },
            capability="filesystem.local_files",
            artifacts=["text_preview"],
            roles=["evidence", "verification"],
            verification_strength="weak",
        ),
        read_text_preview,
    )
    registry.register(
        ToolSpec(
            id="filesystem.read_file",
            name="读取文件内容",
            description="读取允许工作区内的文件完整内容，返回带行号的文本。支持 start_line/end_line 分段读取，单次最多返回 500 行。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "start_line": {"type": "integer", "description": "起始行号（从1开始）"},
                    "end_line": {"type": "integer", "description": "结束行号（包含）"},
                },
                "required": ["path"],
            },
            capability="filesystem.local_files",
            artifacts=["text"],
            roles=["evidence", "verification"],
            verification_strength="weak",
        ),
        read_file,
    )
    registry.register(
        ToolSpec(
            id="filesystem.write_file",
            name="写入文件",
            description=(
                "在允许工作区内创建或覆盖很小的完整文本文件。写入前会创建可恢复回退点；"
                "它不适合较大 HTML/CSS/JS/Python/Markdown/JSON 完整产物。"
                "新建或重写非平凡文本/代码产物时，可使用 filesystem.create_text_draft、"
                "filesystem.append_text_chunk、filesystem.finalize_text_file。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {
                        "type": "string",
                        "description": (
                            "Small complete file content only. For non-trivial "
                            "HTML/CSS/JS/Python/Markdown/JSON or any content "
                            "near the model output limit, use the text draft "
                            "chunk protocol instead."
                        ),
                    },
                    "create_dirs": {"type": "boolean", "default": True, "description": "是否自动创建中间目录"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
            capability="code.text_write",
            artifacts=["file"],
            effects=["file_write", "local_state_change"],
            roles=["deliverable"],
        ),
        write_file,
    )
    registry.register(
        ToolSpec(
            id="filesystem.apply_changes",
            name="Apply local file changes",
            description=(
                "Apply a small transaction of local file changes inside the workspace boundary. "
                "This is a structured filesystem write channel for bounded create, overwrite, "
                "literal replace, and delete operations. For complex code edits, use code.edit_file "
                "or code.apply_patch; for large complete artifacts, use the text draft flow."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Short reason for the change set"},
                    "create_dirs": {"type": "boolean", "default": True},
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "create_file",
                                        "overwrite_file",
                                        "replace_text",
                                        "delete_file",
                                    ],
                                },
                                "path": {"type": "string"},
                                "content": {
                                    "type": "string",
                                    "description": (
                                        "Bounded create/overwrite content. For a "
                                        "large complete artifact, create a text "
                                        "draft and append chunks instead."
                                    ),
                                },
                                "old_text": {"type": "string"},
                                "new_text": {
                                    "type": "string",
                                    "description": (
                                        "Bounded replacement content. For large "
                                        "rewrites, use the text draft chunk protocol."
                                    ),
                                },
                                "replace_all": {"type": "boolean", "default": False},
                                "expected_replacements": {"type": "integer"},
                                "missing_ok": {"type": "boolean", "default": False},
                            },
                            "required": ["type", "path"],
                        },
                    },
                },
                "required": ["operations"],
            },
            requires_confirmation=True,
            capability="filesystem.change_set",
            artifacts=["file"],
            effects=["file_write", "file_delete", "local_state_change"],
            roles=["deliverable", "verification"],
            verification_strength="standard",
        ),
        apply_changes,
    )
    registry.register(
        ToolSpec(
            id="filesystem.delete_file",
            name="Delete file",
            description=(
                "Delete one file inside the configured workspace boundary. "
                "Use this for local file removal instead of shell commands so the runtime can "
                "record a structured state-change result and verification evidence."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                    "missing_ok": {
                        "type": "boolean",
                        "default": False,
                        "description": "Treat an already-missing file as verified absence",
                    },
                },
                "required": ["path"],
            },
            requires_confirmation=True,
            capability="filesystem.local_state",
            artifacts=["file"],
            effects=["file_delete", "local_state_change"],
            roles=["deliverable", "verification"],
            verification_strength="standard",
            idempotent=False,
        ),
        delete_file,
    )
    registry.register(
        ToolSpec(
            id="filesystem.copy_file",
            name="Copy file",
            description=(
                "Copy one file inside the configured workspace boundary. "
                "Use this for copying assets, documents, models, images, or other project files "
                "instead of shell commands such as copy, cp, or Copy-Item. The result records "
                "the destination path as a structured local file artifact."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Existing source file path"},
                    "destination_path": {"type": "string", "description": "Destination file path"},
                    "create_dirs": {
                        "type": "boolean",
                        "default": True,
                        "description": "Create destination parent folders when missing",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": True,
                        "description": "Overwrite an existing destination file",
                    },
                },
                "required": ["source_path", "destination_path"],
            },
            requires_confirmation=True,
            capability="filesystem.change_set",
            artifacts=["file"],
            effects=["file_write", "local_state_change"],
            roles=["deliverable", "verification"],
            verification_strength="standard",
            idempotent=False,
        ),
        copy_file,
    )
    registry.register(
        ToolSpec(
            id="filesystem.transform_text",
            name="转换文本文件",
            description=(
                "对工作区内的已有文本文件执行白名单文本变换并写回原文件，写入前会创建可恢复回退点。"
                "适合修复大文件中的整体编码/转义问题，避免让模型重新输出完整文件。"
                "当前支持 transform='html_unescape'，用于把 &lt;html&gt; 这类 HTML 实体恢复为真实标签。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要转换的文本文件路径"},
                    "transform": {
                        "type": "string",
                        "enum": sorted(TEXT_TRANSFORMS),
                        "description": "白名单文本变换名称",
                    },
                },
                "required": ["path", "transform"],
            },
            requires_confirmation=True,
            capability="filesystem.text_transform",
            artifacts=["text_file"],
            effects=["file_write", "local_state_change"],
            roles=["deliverable"],
            retry_safe=True,
            idempotent=True,
        ),
        transform_text,
    )
    registry.register(
        ToolSpec(
            id="filesystem.write_temp_file",
            name="写入任务临时文件",
            description=(
                "在当前任务的受控临时目录中创建或覆盖文件。适合一次性 Python/PowerShell/Node 脚本、"
                "中间数据和不会作为项目产物提交的分析文件。不要用它替代真实项目文件写入。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "临时目录内的相对文件路径，例如 scripts/analyze.py"},
                    "content": {"type": "string", "description": "文件内容"},
                    "create_dirs": {"type": "boolean", "default": True, "description": "是否自动创建中间目录"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=False,
            capability="filesystem.temp_artifact",
            artifacts=["task_temp_file"],
            roles=["temporary"],
            retry_safe=True,
        ),
        write_temp_file,
    )
    registry.register(
        ToolSpec(
            id="filesystem.create_text_draft",
            name="创建文本产物草稿",
            description=(
                "创建一个可分块追加的文本/代码/HTML 产物草稿。适合生成较大的 HTML、JS、Python、Markdown、"
                "JSON 或配置文件，避免模型一次性调用 filesystem.write_file 时被输出截断。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "草稿标题"},
                    "path_hint": {"type": "string", "description": "最终目标文件路径提示"},
                    "language": {"type": "string", "description": "文本类型，例如 html、javascript、python、markdown"},
                    "metadata": {"type": "object"},
                },
            },
            requires_confirmation=False,
            capability="code.text_write",
            artifacts=["text_draft"],
            roles=["draft"],
            retry_safe=True,
        ),
        create_text_draft,
    )
    registry.register(
        ToolSpec(
            id="filesystem.append_text_chunk",
            name="追加文本草稿片段",
            description=(
                "向文本产物草稿追加一个完整、有边界的片段。每次只追加一小段完整代码或文本，"
                "最终用 filesystem.finalize_text_file 写入真实文件。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": (
                            "One complete bounded chunk. Keep each chunk under "
                            f"{TEXT_WRITE_CHUNK_MAX_CHARS} characters and call "
                            "append_text_chunk multiple times for long files."
                        ),
                    },
                    "label": {"type": "string"},
                    "sequence": {"type": "integer"},
                    "metadata": {"type": "object"},
                },
                "required": ["draft_id", "content"],
            },
            requires_confirmation=False,
            capability="code.text_write",
            artifacts=["text_draft"],
            roles=["draft"],
            retry_safe=True,
        ),
        append_text_chunk,
    )
    registry.register(
        ToolSpec(
            id="filesystem.inspect_text_draft",
            name="查看文本产物草稿",
            description="查看文本产物草稿的片段数量、字符数和预览内容。",
            input_schema={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                    "preview_chars": {"type": "integer", "default": 1200},
                },
                "required": ["draft_id"],
            },
            requires_confirmation=False,
            capability="code.text_write",
            artifacts=["text_draft"],
            roles=["draft", "evidence"],
            retry_safe=True,
            idempotent=True,
        ),
        inspect_text_draft,
    )
    registry.register(
        ToolSpec(
            id="filesystem.finalize_text_file",
            name="文本草稿写入文件",
            description=(
                "将文本产物草稿最终写入工作区文件。写入前会执行 PathGuard、确认、备份和轻量校验；"
                "HTML/JSON/Python 会按扩展名自动校验。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                    "output_path": {"type": "string", "description": "最终输出文件路径"},
                    "path": {"type": "string", "description": "output_path 的兼容别名"},
                    "validator": {
                        "type": "string",
                        "enum": sorted(TEXT_DRAFT_VALIDATORS),
                        "default": "auto",
                    },
                    "create_dirs": {"type": "boolean", "default": True},
                },
                "required": ["draft_id"],
            },
            requires_confirmation=True,
            capability="code.text_write",
            artifacts=["text_file", "text_draft"],
            effects=["file_write", "local_state_change"],
            roles=["deliverable"],
            retry_safe=True,
        ),
        finalize_text_file,
    )
