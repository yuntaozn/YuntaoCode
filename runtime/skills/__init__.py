from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

from runtime.tool_registry import ToolRegistry

from .attachments import register_attachment_tools
from .code import register_code_tools
from .desktop import register_desktop_tools
from .document import register_document_tools
from .filesystem import register_filesystem_tools
from .git import register_git_tools
from .memory import register_memory_tools
from .preview import register_preview_tools
from .shell import register_shell_tools
from .spreadsheet import register_spreadsheet_tools
from .web import register_web_tools


ToolRegistrar = Callable[[ToolRegistry], None]


BUILTIN_TOOL_GROUPS: dict[str, ToolRegistrar] = {
    "attachment": register_attachment_tools,
    "filesystem": register_filesystem_tools,
    "document": register_document_tools,
    "spreadsheet": register_spreadsheet_tools,
    "desktop": register_desktop_tools,
    "code": register_code_tools,
    "shell": register_shell_tools,
    "git": register_git_tools,
    "web": register_web_tools,
    "preview": register_preview_tools,
    "memory": register_memory_tools,
}

DEFAULT_BUILTIN_TOOL_GROUPS: tuple[str, ...] = tuple(BUILTIN_TOOL_GROUPS)
CORE_BUILTIN_TOOL_GROUPS: tuple[str, ...] = (
    "attachment",
    "filesystem",
    "code",
    "shell",
    "git",
    "memory",
)


def register_builtin_tools(
    registry: ToolRegistry,
    groups: Iterable[str] | None = None,
) -> None:
    selected_groups = tuple(groups) if groups is not None else DEFAULT_BUILTIN_TOOL_GROUPS
    registered: set[str] = set()
    for group in selected_groups:
        if group in registered:
            continue
        try:
            registrar = BUILTIN_TOOL_GROUPS[group]
        except KeyError as exc:
            raise ValueError(f"unknown builtin tool group: {group}") from exc
        registrar(registry)
        registered.add(group)
