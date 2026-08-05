from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_tool_input(tool_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    """在不改变用户意图的前提下返回规范工具输入。

    即使语义载荷清晰，模型 Provider 也不总能完全遵循工具 Schema。确认和执行前
    先规范化常见等价结构，避免 Schema Guard 拒绝可恢复的调用。"""
    if not isinstance(input_data, dict):
        return {}
    normalized = deepcopy(input_data)
    if tool_id == "code.edit_file":
        _normalize_code_edit_file_input(normalized)
    elif tool_id == "filesystem.apply_changes":
        _normalize_apply_changes_input(normalized)
    return normalized


def _normalize_code_edit_file_input(input_data: dict[str, Any]) -> None:
    if _has_meaningful_value(input_data.get("edits")):
        return
    start_line = _first_present(input_data, ("start_line", "startLine", "line_start", "lineStart"))
    end_line = _first_present(input_data, ("end_line", "endLine", "line_end", "lineEnd"))
    line_new_text = _first_present(
        input_data,
        ("new_text", "newText", "new_string", "newString", "replacement", "new"),
    )
    if start_line is not None and end_line is not None and line_new_text is not None:
        input_data["edits"] = [{
            "start_line": start_line,
            "end_line": end_line,
            "new_text": line_new_text,
        }]
        return

    old_text = _first_non_empty(
        input_data,
        ("old_text", "oldText", "old_string", "oldString", "original"),
    )
    new_text = _first_present(
        input_data,
        ("new_text", "newText", "new_string", "newString", "replacement"),
    )
    if old_text is None or new_text is None:
        return
    input_data["edits"] = [{"old_text": old_text, "new_text": new_text}]


def _normalize_apply_changes_input(input_data: dict[str, Any]) -> None:
    if _has_meaningful_value(input_data.get("operations")):
        return
    operations = _first_present(
        input_data,
        ("operation", "changes", "change_set", "changeSet"),
    )
    if isinstance(operations, dict):
        input_data["operations"] = [operations]
        return
    if isinstance(operations, list):
        input_data["operations"] = operations
        return

    path = _first_non_empty(input_data, ("path", "file_path", "filePath"))
    old_text = _first_non_empty(
        input_data,
        ("old_text", "oldText", "old_string", "oldString", "original"),
    )
    new_text = _first_present(
        input_data,
        ("new_text", "newText", "new_string", "newString", "replacement"),
    )
    if path is not None and old_text is not None and new_text is not None:
        input_data["operations"] = [{
            "type": "replace_text",
            "path": path,
            "old_text": old_text,
            "new_text": new_text,
        }]


def _first_present(input_data: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        if key in input_data and input_data[key] is not None:
            return input_data[key]
    return None


def _first_non_empty(input_data: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    value = _first_present(input_data, keys)
    if isinstance(value, str) and not value:
        return None
    return value


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True
