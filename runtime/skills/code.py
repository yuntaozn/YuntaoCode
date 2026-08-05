from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from runtime.text_encoding import (
    detect_text_encoding,
    read_text_with_encoding,
    text_encoding_risks,
    write_text_with_encoding,
)
from runtime.tool_registry import ToolRegistry, ToolSpec


CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md",
    ".sql", ".toml", ".yaml", ".yml", ".rs", ".go", ".java", ".cs",
}

DEFAULT_EXCLUDE_DIRS = {
    ".backup",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
}


def _detect_encoding(raw: bytes) -> str:
    return detect_text_encoding(raw)


def _read_text_with_encoding(path: Path) -> tuple[str, str]:
    return read_text_with_encoding(path)


def _write_text_with_encoding(path: Path, text: str, encoding: str) -> None:
    write_text_with_encoding(path, text, encoding)


def normalize_extensions(value: Any) -> set[str]:
    if not value:
        return set(CODE_EXTENSIONS)
    result: set[str] = set()
    for item in value:
        text = str(item or "").strip().lower()
        if not text:
            continue
        result.add(text if text.startswith(".") else f".{text}")
    return result or set(CODE_EXTENSIONS)


def normalize_exclude_dirs(value: Any) -> set[str]:
    if not value:
        return set(DEFAULT_EXCLUDE_DIRS)
    return {str(item).strip() for item in value if str(item).strip()}


def is_in_excluded_dir(path: Path, root: Path, exclude_dirs: set[str]) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part in exclude_dirs for part in parts[:-1])


async def search_text(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    root = context.path_guard.resolve(input_data.get("path") or ".")
    if not root.exists():
        raise ValueError(f"path not found: {root}")
    if not root.is_dir() and not root.is_file():
        raise ValueError(f"path is not searchable: {root}")

    query = input_data.get("query")
    if not query:
        raise ValueError("query is required")

    max_matches = int(input_data.get("max_matches", 100))
    include_extensions = normalize_extensions(input_data.get("include_extensions"))
    exclude_dirs = normalize_exclude_dirs(input_data.get("exclude_dirs"))
    return await asyncio.to_thread(
        search_text_sync,
        root,
        query,
        max_matches,
        include_extensions,
        exclude_dirs,
    )


def search_text_sync(
    root: Path,
    query: str,
    max_matches: int,
    include_extensions: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    include_extensions = include_extensions or set(CODE_EXTENSIONS)
    exclude_dirs = exclude_dirs or set(DEFAULT_EXCLUDE_DIRS)
    if root.is_file():
        candidates = [root]
        base = root.parent
    else:
        candidates = root.rglob("*")
        base = root

    for path in candidates:
        if len(matches) >= max_matches:
            break
        if (
            not path.is_file()
            or path.suffix.lower() not in include_extensions
            or is_in_excluded_dir(path, base, exclude_dirs)
        ):
            continue
        try:
            text, _encoding = _read_text_with_encoding(path)
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if query in line:
                matches.append({
                    "path": str(path.relative_to(base)),
                    "line": line_number,
                    "preview": line.strip()[:240],
                })
                if len(matches) >= max_matches:
                    break

    return {
        "root": str(root),
        "query": query,
        "matches": matches,
        "match_count": len(matches),
        "truncated": len(matches) >= max_matches,
    }


async def list_project_files(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    root = context.path_guard.resolve(input_data.get("path") or ".")
    if not root.exists() or not root.is_dir():
        raise ValueError(f"folder not found: {root}")

    max_files = int(input_data.get("max_files", 500))
    include_extensions = normalize_extensions(input_data.get("include_extensions"))
    exclude_dirs = normalize_exclude_dirs(input_data.get("exclude_dirs"))
    return await asyncio.to_thread(
        list_project_files_sync,
        root,
        max_files,
        include_extensions,
        exclude_dirs,
    )


def list_project_files_sync(
    root: Path,
    max_files: int,
    include_extensions: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    include_extensions = include_extensions or set(CODE_EXTENSIONS)
    exclude_dirs = exclude_dirs or set(DEFAULT_EXCLUDE_DIRS)
    for path in root.rglob("*"):
        if len(files) >= max_files:
            break
        if (
            path.is_file()
            and path.suffix.lower() in include_extensions
            and not is_in_excluded_dir(path, root, exclude_dirs)
        ):
            files.append({
                "path": str(path.relative_to(root)),
                "extension": path.suffix.lower(),
                "size": path.stat().st_size,
            })

    return {
        "root": str(root),
        "files": files,
        "file_count": len(files),
        "truncated": len(files) >= max_files,
    }


# ---------------------------------------------------------------------------
# replace_text：跨项目文件批量按字面量替换
# ---------------------------------------------------------------------------

async def replace_text(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    root = context.path_guard.resolve(input_data.get("path") or ".")
    if not root.exists():
        raise ValueError(f"path not found: {root}")

    old_text = input_data.get("old_text")
    new_text = input_data.get("new_text")
    if old_text is None or str(old_text) == "":
        raise ValueError("old_text is required")
    if new_text is None:
        raise ValueError("new_text is required")

    include_extensions = normalize_extensions(input_data.get("include_extensions"))
    exclude_dirs = normalize_exclude_dirs(input_data.get("exclude_dirs"))
    max_files = max(1, min(int(input_data.get("max_files", 200)), 1000))
    dry_run = bool(input_data.get("dry_run", False))
    result = await asyncio.to_thread(
        replace_text_sync,
        root,
        str(old_text),
        str(new_text),
        include_extensions,
        exclude_dirs,
        max_files,
        dry_run,
        getattr(context, "backup_file", None),
    )
    action = "matched" if dry_run else "changed"
    context.log("info", f"bulk replace {action} {result['changed_file_count']} files", {
        "replacement_count": result["replacement_count"],
        "truncated": result["truncated"],
    })
    return result


def replace_text_sync(
    root: Path,
    old_text: str,
    new_text: str,
    include_extensions: set[str],
    exclude_dirs: set[str],
    max_files: int,
    dry_run: bool,
    backup_file: Any | None = None,
) -> dict[str, Any]:
    if root.is_file():
        candidates = [root]
        base = root.parent
    elif root.is_dir():
        candidates = root.rglob("*")
        base = root
    else:
        raise ValueError(f"path not found: {root}")

    matched_files: list[dict[str, Any]] = []
    changed_files: list[dict[str, Any]] = []
    replacement_count = 0
    truncated = False

    for path in candidates:
        if len(changed_files) >= max_files:
            truncated = True
            break
        if (
            not path.is_file()
            or path.suffix.lower() not in include_extensions
            or is_in_excluded_dir(path, base, exclude_dirs)
        ):
            continue
        try:
            text, encoding = _read_text_with_encoding(path)
        except OSError:
            continue
        count = text.count(old_text)
        if count <= 0:
            continue

        rel_path = str(path.relative_to(base))
        record = {"path": rel_path, "occurrences": count}
        matched_files.append(record)
        replacement_count += count
        if dry_run:
            changed_files.append(record)
            continue

        if callable(backup_file):
            backup_file(path)
        _write_text_with_encoding(path, text.replace(old_text, new_text), encoding)
        changed_files.append(record)

    return {
        "root": str(root),
        "old_text": old_text,
        "new_text": new_text,
        "dry_run": dry_run,
        "matched_files": matched_files[:200],
        "changed_files": changed_files[:200],
        "matched_file_count": len(matched_files),
        "changed_file_count": len(changed_files),
        "replacement_count": replacement_count,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# edit_file：精确搜索替换编辑
# ---------------------------------------------------------------------------

async def edit_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    if not path.exists() or not path.is_file():
        raise ValueError(f"file not found: {path}")
    edits = _normalize_edits(input_data)
    if not edits:
        # 详细诊断信息：记录实际收到的参数键
        received_keys = list(input_data.keys())
        raw_edits = input_data.get("edits")
        edits_type = type(raw_edits).__name__ if raw_edits is not None else "None"
        edits_preview = repr(raw_edits)[:200] if raw_edits is not None else "(missing)"
        context.log(
            "warning",
            f"edit_file edits 解析失败: keys={received_keys}, edits_type={edits_type}, preview={edits_preview}",
        )
        raise ValueError(
            f"edits is required and must be a list of {{old_text, new_text}}. "
            f"Received keys: {received_keys}. "
            "Hint: for a tiny new file use filesystem.write_file; for a non-trivial "
            "complete text/code artifact use filesystem.create_text_draft, "
            "filesystem.append_text_chunk, then filesystem.finalize_text_file."
        )
    return await asyncio.to_thread(edit_file_sync, path, edits, context)


def _normalize_edits(input_data: dict[str, Any]) -> list[dict[str, Any]]:
    """灵活解析模型多种输出格式中的编辑项。"""
    import json as _json
    # 尝试多种常见别名获取 edits 数组
    edits = (
        input_data.get("edits")
        or input_data.get("replace_blocks")
        or input_data.get("replaceBlocks")
        or input_data.get("changes")
        or input_data.get("modifications")
        or input_data.get("replacements")
    )
    # 情况 1：edits 是 JSON 字符串（模型重复序列化）
    if isinstance(edits, str):
        try:
            edits = _json.loads(edits)
        except (ValueError, TypeError):
            return []
    # 情况 2：edits 是单个字典（模型忘记包装成数组）
    if isinstance(edits, dict):
        edits = [edits]
    if not isinstance(edits, list):
        line_edit = _normalize_line_range_edit(input_data)
        if line_edit is not None:
            return [line_edit]
        # 情况 3：没有 edits 键，但顶层存在多种命名形式的 old/new
        old_text = (
            input_data.get("old_text")
            or input_data.get("oldText")
            or input_data.get("old_string")
            or input_data.get("oldString")
            or input_data.get("original")
        )
        new_text = (
            input_data.get("new_text")
            or input_data.get("newText")
            or input_data.get("new_string")
            or input_data.get("newString")
            or input_data.get("replacement")
        )
        if old_text and new_text is not None:
            return [{"old_text": old_text, "new_text": new_text}]
        return []
    # 规范化每个编辑项中的多种键名
    normalized: list[dict[str, Any]] = []
    for item in edits:
        if not isinstance(item, dict):
            continue
        line_edit = _normalize_line_range_edit(item)
        if line_edit is not None:
            normalized.append(line_edit)
            continue
        old = (
            item.get("old_text") or item.get("oldText")
            or item.get("old_string") or item.get("oldString")
            or item.get("original") or ""
        )
        new = (
            item.get("new_text") or item.get("newText")
            or item.get("new_string") or item.get("newString")
            or item.get("replacement")
        )
        if new is None:
            new = item.get("new") or ""
        if old:
            normalized.append({"old_text": old, "new_text": new})
    return normalized


def _first_present_value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item:
            return item.get(key)
    return None


def _coerce_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 1:
        return None
    return parsed


def _normalize_line_range_edit(item: dict[str, Any]) -> dict[str, Any] | None:
    start_line = _coerce_positive_int(
        _first_present_value(item, "start_line", "startLine", "line_start", "lineStart")
    )
    end_line = _coerce_positive_int(
        _first_present_value(item, "end_line", "endLine", "line_end", "lineEnd")
    )
    new_text = _first_present_value(
        item,
        "new_text",
        "newText",
        "new_string",
        "newString",
        "replacement",
        "new",
    )
    if start_line is None or end_line is None or new_text is None:
        return None
    return {"start_line": start_line, "end_line": end_line, "new_text": str(new_text)}


def _normalize_text_for_match(text: str) -> str:
    """用于模糊匹配的轻量规范化：统一换行并去除行尾空白。

    保留缩进，因为缩进对于正确匹配代码块非常关键。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _normalize_text_aggressive(text: str) -> str:
    """激进规范化：把全部空白折叠为单个空格并移除缩进。

    当模型输出与实际文件缩进不同时，作为模糊匹配的回退方式。"""
    import re
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line.strip()) for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _is_comment_or_blank_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return stripped.startswith((
        "#",
        "//",
        "/*",
        "*",
        "*/",
        "<!--",
        "-->",
    ))


def _find_unique_stable_match(text: str, old_text: str) -> str | None:
    """通过匹配稳定的非注释行查找一个原始文本块。"""
    file_lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    old_lines = old_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    file_stable = [
        (_normalize_text_aggressive(line), index)
        for index, line in enumerate(file_lines)
        if not _is_comment_or_blank_line(line)
    ]
    old_stable = [
        _normalize_text_aggressive(line)
        for line in old_lines
        if not _is_comment_or_blank_line(line)
    ]
    file_stable = [(line, index) for line, index in file_stable if line]
    old_stable = [line for line in old_stable if line]
    if len(file_stable) < 1 or len(old_stable) < 1:
        return None

    max_window = min(8, len(old_stable))
    for window_size in range(max_window, 1, -1):
        for old_start in range(0, len(old_stable) - window_size + 1):
            candidate = old_stable[old_start:old_start + window_size]
            candidate_text = "\n".join(candidate)
            if window_size < 3 and len(candidate_text) < 120:
                continue
            matches: list[tuple[int, int]] = []
            for file_start in range(0, len(file_stable) - window_size + 1):
                file_candidate = [
                    line for line, _ in file_stable[file_start:file_start + window_size]
                ]
                if file_candidate == candidate:
                    raw_start = file_stable[file_start][1]
                    raw_end = file_stable[file_start + window_size - 1][1]
                    matches.append((raw_start, raw_end))
            unique_matches = sorted(set(matches))
            if len(unique_matches) == 1:
                raw_start, raw_end = unique_matches[0]
                return "\n".join(file_lines[raw_start:raw_end + 1])
    return None


def _locate_in_original(
    text: str,
    norm_old: str,
    normalizer: Any,
) -> str | None:
    """使用指定规范化器在文本中定位 norm_old，并返回原始文本。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    old_lines = norm_old.splitlines()
    if not old_lines or not lines:
        return None
    for i in range(len(lines) - len(old_lines) + 1):
        window = "\n".join(lines[i:i + len(old_lines)])
        if normalizer(window) == norm_old:
            return "\n".join(lines[i:i + len(old_lines)])
    return None


def _fuzzy_match(text: str, old_text: str) -> tuple[int, str | None]:
    """精确匹配失败时尝试模糊匹配。

    按以下顺序执行：
    1. 精确匹配。
    2. 轻量规范化：统一换行并去除行尾空白，保留缩进。
    3. 激进规范化：折叠全部空白，用于缩进不同的情况。
    4. 稳定行匹配：查找唯一的非注释行，用于子集匹配。

    返回 ``(count, matched_text)``：count 为 0 表示无匹配，1 表示唯一匹配，
    大于等于 2 表示存在多个匹配。"""
    # 策略 1：精确匹配
    exact_count = text.count(old_text)
    if exact_count >= 1:
        return exact_count, old_text

    # 策略 2：轻量规范化（保留缩进）
    norm_text_light = _normalize_text_for_match(text)
    norm_old_light = _normalize_text_for_match(old_text)
    if norm_old_light:
        light_count = norm_text_light.count(norm_old_light)
        if light_count == 1:
            result = _locate_in_original(text, norm_old_light, _normalize_text_for_match)
            if result:
                return 1, result
        if light_count > 1:
            # 轻量规范化得到多个匹配时，尝试稳定匹配以确定唯一项
            stable = _find_unique_stable_match(text, old_text)
            if stable:
                return 1, stable
            return light_count, None

    # 策略 3：激进规范化（折叠空白）
    norm_text_full = _normalize_text_aggressive(text)
    norm_old_full = _normalize_text_aggressive(old_text)
    if norm_old_full:
        full_count = norm_text_full.count(norm_old_full)
        if full_count == 1:
            result = _locate_in_original(text, norm_old_full, _normalize_text_aggressive)
            if result:
                return 1, result
        if full_count > 1:
            return full_count, None

    # 策略 4：稳定行匹配（非注释行）
    stable_match = _find_unique_stable_match(text, old_text)
    if stable_match:
        return 1, stable_match

    return 0, None


def _split_logical_lines(text: str) -> tuple[list[str], bool]:
    had_final_newline = text.endswith("\n")
    lines = text.split("\n")
    if had_final_newline:
        lines = lines[:-1]
    return lines, had_final_newline


def _apply_line_range_edit(text: str, edit: dict[str, Any]) -> tuple[str, list[str]]:
    start_line = edit.get("start_line")
    end_line = edit.get("end_line")
    new_text = edit.get("new_text")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        raise ValueError("line range edit requires integer start_line and end_line")
    if new_text is None:
        raise ValueError("line range edit requires new_text")
    if end_line < start_line:
        raise ValueError("line range edit requires end_line >= start_line")

    lines, had_final_newline = _split_logical_lines(text)
    if start_line > len(lines) or end_line > len(lines):
        raise ValueError(
            f"line range {start_line}-{end_line} is outside file with {len(lines)} lines"
        )

    replacement_text = str(new_text).replace("\r\n", "\n").replace("\r", "\n")
    replacement_lines = replacement_text.split("\n")
    if replacement_lines and replacement_lines[-1] == "":
        replacement_lines = replacement_lines[:-1]

    old_lines = lines[start_line - 1 : end_line]
    lines[start_line - 1 : end_line] = replacement_lines
    updated = "\n".join(lines)
    if had_final_newline:
        updated += "\n"

    diff_parts: list[str] = [f"@@ lines {start_line}-{end_line} @@"]
    for line in old_lines[:3]:
        diff_parts.append(f"- {line[:120]}")
    for line in replacement_lines[:3]:
        diff_parts.append(f"+ {line[:120]}")
    return updated, diff_parts


def edit_file_sync(path: Path, edits: list[dict[str, Any]], context: Any) -> dict[str, Any]:
    text, encoding = _read_text_with_encoding(path)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    applied = 0
    diff_parts: list[str] = []

    for edit_index, edit in enumerate(edits, start=1):
        if "start_line" in edit or "end_line" in edit:
            updated_text, line_diff = _apply_line_range_edit(text, edit)
            if updated_text == text:
                raise ValueError(
                    f"edit {edit_index} makes no content change; provide a different replacement"
                )
            text = updated_text
            applied += 1
            diff_parts.extend(line_diff)
            if applied < len(edits):
                diff_parts.append("---")
            continue

        old_text = edit.get("old_text") or ""
        new_text = edit.get("new_text")
        if new_text is None:
            raise ValueError("each edit must have old_text and new_text")
        if not old_text:
            raise ValueError("old_text must not be empty")

        # 先尝试精确匹配，失败后尝试模糊匹配
        count, matched_text = _fuzzy_match(text, old_text)

        if count == 0:
            raise ValueError(f"old_text not found in file: {repr(old_text[:120])}")
        if count > 1:
            raise ValueError(
                f"old_text matches {count} locations. Provide more surrounding context to make it unique: {repr(old_text[:120])}"
            )

        # 使用匹配到的原始文本替换（保留原始换行和缩进）
        replacement_source = matched_text or old_text
        updated_text = text.replace(replacement_source, new_text, 1)
        if updated_text == text:
            raise ValueError(
                f"edit {edit_index} makes no content change; old_text and new_text resolve to the same content"
            )
        text = updated_text
        applied += 1

        # 构建简短 diff 预览
        old_preview = old_text.strip().splitlines()[:3]
        new_preview = new_text.strip().splitlines()[:3]
        for line in old_preview:
            diff_parts.append(f"- {line[:120]}")
        for line in new_preview:
            diff_parts.append(f"+ {line[:120]}")
        if applied < len(edits):
            diff_parts.append("---")

    if callable(getattr(context, "backup_file", None)):
        context.backup_file(path)
    _write_text_with_encoding(path, text, encoding)
    context.log("info", f"edited {applied} locations in {path}")
    return {
        "path": str(path),
        "edit_count": applied,
        "encoding": encoding,
        "encoding_risks": text_encoding_risks(path, text, encoding),
        "diff_preview": "\n".join(diff_parts),
    }


# ---------------------------------------------------------------------------
# apply_patch：小型事务性代码变更
# ---------------------------------------------------------------------------

async def apply_patch(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    patch = input_data.get("patch")
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("patch is required")
    return await asyncio.to_thread(apply_patch_sync, patch, context)


def apply_patch_sync(patch: str, context: Any) -> dict[str, Any]:
    """校验每项操作后应用小型 Codex 风格补丁。"""
    operations = _parse_apply_patch(patch)
    planned: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    for operation in operations:
        path = context.path_guard.resolve(operation["path"])
        if path in seen_paths:
            raise ValueError(f"patch contains multiple operations for the same file: {path}")
        seen_paths.add(path)
        kind = operation["kind"]
        if kind == "add":
            if path.exists():
                raise ValueError(f"cannot add existing file: {path}")
            text = _apply_add_file_patch(operation["body"])
            if path.suffix.lower() in {".html", ".htm"}:
                from runtime.skills.filesystem import inspect_text_artifact_integrity

                integrity = inspect_text_artifact_integrity(path, text)
                if integrity.get("checked") and not integrity.get("valid"):
                    issues = ", ".join(str(item) for item in integrity.get("issues") or [])
                    raise ValueError(f"refusing incomplete added HTML file: {issues}")
            planned.append({"kind": kind, "path": path, "text": text, "encoding": "utf-8"})
            continue
        if kind == "update":
            if not path.exists() or not path.is_file():
                raise ValueError(f"file not found: {path}")
            original, encoding = _read_text_with_encoding(path)
            text, hunk_count = _apply_update_file_patch(original, operation["body"])
            planned.append({
                "kind": kind,
                "path": path,
                "text": text,
                "encoding": encoding,
                "hunk_count": hunk_count,
            })
            continue
        raise ValueError(f"unsupported patch operation: {kind}")

    for item in planned:
        path = item["path"]
        if callable(getattr(context, "backup_file", None)):
            context.backup_file(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_with_encoding(path, item["text"], item["encoding"])
        context.log("info", f"patch {item['kind']}: {path}")

    encoding_risks = [
        {
            "path": str(item["path"]),
            "encoding": str(item["encoding"]),
            "risks": text_encoding_risks(item["path"], str(item["text"]), str(item["encoding"])),
        }
        for item in planned
    ]

    return {
        "path": str(planned[0]["path"]) if len(planned) == 1 else "",
        "paths": [str(item["path"]) for item in planned],
        "file_count": len(planned),
        "operation_count": len(operations),
        "hunk_count": sum(int(item.get("hunk_count") or 0) for item in planned),
        "encoding_risks": encoding_risks,
    }


def _parse_apply_patch(patch: str) -> list[dict[str, Any]]:
    text = patch.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = text.splitlines()
    if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise ValueError("patch must start with '*** Begin Patch' and end with '*** End Patch'")

    operations: list[dict[str, Any]] = []
    index = 1
    end_index = len(lines) - 1
    headers = {
        "*** Add File: ": "add",
        "*** Add File ": "add",
        "*** Update File: ": "update",
        "*** Update File ": "update",
    }
    while index < end_index:
        if not lines[index].strip():
            index += 1
            continue
        header = lines[index]
        kind = ""
        path = ""
        for prefix, candidate_kind in headers.items():
            if header.startswith(prefix):
                kind = candidate_kind
                path = header[len(prefix):].strip()
                break
        if not kind or not path:
            raise ValueError(f"unsupported or malformed patch header: {header[:160]}")
        index += 1
        body: list[str] = []
        while index < end_index and not any(lines[index].startswith(prefix) for prefix in headers):
            body.append(lines[index])
            index += 1
        if not body:
            raise ValueError(f"patch operation has no body: {path}")
        operations.append({"kind": kind, "path": path, "body": body})
    if not operations:
        raise ValueError("patch contains no file operations")
    return operations


def _apply_add_file_patch(body: list[str]) -> str:
    content: list[str] = []
    for line in body:
        if line == "*** End of File":
            continue
        if not line.startswith("+"):
            raise ValueError("every added-file line must start with '+'")
        content.append(line[1:])
    return "\n".join(content) + ("\n" if content else "")


def _apply_update_file_patch(original: str, body: list[str]) -> tuple[str, int]:
    text = original.replace("\r\n", "\n").replace("\r", "\n")
    hunks: list[list[str]] = []
    current: list[str] = []
    for line in body:
        if line.startswith("@@"):
            if current:
                hunks.append(current)
                current = []
            continue
        if line == "*** End of File":
            continue
        current.append(line)
    if current:
        hunks.append(current)
    if not hunks:
        raise ValueError("update patch contains no hunks")

    for hunk in hunks:
        old_lines: list[str] = []
        new_lines: list[str] = []
        for line in hunk:
            if not line or line[0] not in {" ", "+", "-"}:
                raise ValueError("update hunk lines must start with space, '+', or '-'")
            value = line[1:]
            if line[0] in {" ", "-"}:
                old_lines.append(value)
            if line[0] in {" ", "+"}:
                new_lines.append(value)
        old_text = "\n".join(old_lines)
        new_text = "\n".join(new_lines)
        if not old_text:
            raise ValueError("update hunk must include context or removed lines")
        count, matched_text = _fuzzy_match(text, old_text)
        if count == 0:
            raise ValueError(f"patch context not found: {old_text[:160]!r}")
        if count > 1:
            raise ValueError(f"patch context matches {count} locations: {old_text[:160]!r}")
        text = text.replace(matched_text or old_text, new_text, 1)
    return text, len(hunks)


def register_code_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="code.search_text",
            name="搜索代码文本",
            description="在允许工作区内搜索代码和配置文件文本。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                    "max_matches": {"type": "integer", "default": 100},
                    "include_extensions": {"type": "array", "items": {"type": "string"}},
                    "exclude_dirs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path", "query"],
            },
            capability="code.local_project",
            artifacts=["search_results"],
            roles=["evidence", "verification"],
            verification_strength="weak",
        ),
        search_text,
    )
    registry.register(
        ToolSpec(
            id="code.list_project_files",
            name="列出代码文件",
            description="列出项目中的常见代码和配置文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_files": {"type": "integer", "default": 500},
                    "include_extensions": {"type": "array", "items": {"type": "string"}},
                    "exclude_dirs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path"],
            },
            capability="code.local_project",
            artifacts=["file_list"],
            roles=["evidence"],
            verification_strength="weak",
        ),
        list_project_files,
    )
    registry.register(
        ToolSpec(
            id="code.apply_patch",
            name="应用代码补丁",
            description=(
                "使用 Codex 风格的 *** Begin Patch / "
                "*** Update File / *** Add File 小块补丁修改一个或多个文件。"
                "运行时会先完整解析全部补丁，再应用写入；不要用它一次传输超大完整文件。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": (
                            "完整补丁文本。更新文件时每个 hunk 使用 @@，上下文行以空格开头，"
                            "删除行以 - 开头，新增行以 + 开头。"
                        ),
                    },
                },
                "required": ["patch"],
            },
            requires_confirmation=True,
            capability="code.text_write",
            artifacts=["file", "diff"],
            effects=["file_write", "local_state_change"],
            roles=["deliverable"],
        ),
        apply_patch,
    )
    registry.register(
        ToolSpec(
            id="code.replace_text",
            name="批量替换文本",
            description="在允许工作区内对多个代码/配置文件执行同一文本替换，适合端口、URL、常量批量修改。会跳过 node_modules、.git、.backup、build、dist 等目录，并在本地终端备份区创建可恢复回退点。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件或文件夹路径"},
                    "old_text": {"type": "string", "description": "要替换的原文本"},
                    "new_text": {"type": "string", "description": "替换后的新文本"},
                    "include_extensions": {"type": "array", "items": {"type": "string"}},
                    "exclude_dirs": {"type": "array", "items": {"type": "string"}},
                    "max_files": {"type": "integer", "default": 200},
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["path", "old_text", "new_text"],
            },
            requires_confirmation=True,
            capability="code.text_write",
            artifacts=["file", "diff"],
            effects=["file_write", "local_state_change"],
            roles=["deliverable"],
        ),
        replace_text,
    )
    registry.register(
        ToolSpec(
            id="code.edit_file",
            name="精确编辑文件",
            description=(
                "精确编辑文件。每个 edit 可使用 old_text/new_text 唯一文本替换，"
                "也可使用 start_line/end_line/new_text 做有界行号替换。"
                "编辑前会在本地终端备份区创建可恢复回退点。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "edits": {
                        "type": "array",
                        "description": "编辑操作列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {"type": "string", "description": "要替换的原文本（必须唯一匹配）"},
                                "start_line": {"type": "integer", "description": "有界替换的起始行号，1-based，包含该行"},
                                "end_line": {"type": "integer", "description": "有界替换的结束行号，1-based，包含该行"},
                                "new_text": {"type": "string", "description": "替换后的新文本"},
                            },
                            "oneOf": [
                                {"required": ["old_text", "new_text"]},
                                {"required": ["start_line", "end_line", "new_text"]},
                            ],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
            requires_confirmation=True,
            capability="code.text_write",
            artifacts=["file", "diff"],
            effects=["file_write", "local_state_change"],
            roles=["deliverable"],
        ),
        edit_file,
    )
