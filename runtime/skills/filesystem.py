from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from runtime.tool_registry import ToolRegistry, ToolSpec

MAX_READ_LINES = 500


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
    return await asyncio.to_thread(
        read_text_preview_sync,
        path,
        max_bytes,
        input_data.get("encoding") or "utf-8",
    )


def read_text_preview_sync(path: Path, max_bytes: int, encoding: str) -> dict[str, Any]:
    raw = path.read_bytes()[:max_bytes]
    text = raw.decode(encoding, errors="replace")
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "truncated": path.stat().st_size > max_bytes,
        "text": text,
    }


# ---------------------------------------------------------------------------
# read_file -- full file read with line numbers
# ---------------------------------------------------------------------------

async def read_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    if not path.exists() or not path.is_file():
        raise ValueError(f"file not found: {path}")
    start_line = input_data.get("start_line")
    end_line = input_data.get("end_line")
    return await asyncio.to_thread(read_file_sync, path, start_line, end_line)


def _detect_encoding(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, ValueError):
            continue
    return "utf-8"


def read_file_sync(
    path: Path,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    raw = path.read_bytes()
    encoding = _detect_encoding(raw[:8192])
    text = raw.decode(encoding, errors="replace")
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
    # Raw content without line numbers – model must use this when constructing old_text for edit_file
    raw_content = "".join(selected)

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
        "usage_hint": (
            "content 字段带行号前缀，仅用于显示参考。"
            "构造 code.edit_file 的 old_text / new_text 时，请基于 raw_content（不含行号前缀）的文本。"
        ),
    }
    return result


# ---------------------------------------------------------------------------
# write_file -- create or overwrite a file
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
    create_dirs = input_data.get("create_dirs", True)
    return await asyncio.to_thread(write_file_sync, path, str(content), bool(create_dirs), context)


def write_file_sync(path: Path, content: str, create_dirs: bool, context: Any) -> dict[str, Any]:
    created = not path.exists()

    if callable(getattr(context, "backup_file", None)):
        context.backup_file(path)

    if create_dirs:
        path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(content, encoding="utf-8")
    context.log("info", f"{'created' if created else 'overwritten'}: {path}")
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "created": created,
    }


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
        ),
        read_file,
    )
    registry.register(
        ToolSpec(
            id="filesystem.write_file",
            name="写入文件",
            description="在允许工作区内创建或覆盖文件。写入前会在本地终端备份区创建可恢复回退点。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                    "create_dirs": {"type": "boolean", "default": True, "description": "是否自动创建中间目录"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
        ),
        write_file,
    )
