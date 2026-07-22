from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import Callable

from runtime.tool_registry import ToolRegistry


ToolRegistrar = Callable[[ToolRegistry], None]


BUILTIN_TOOL_GROUPS: dict[str, tuple[str, str]] = {
    "attachment": (".attachments", "register_attachment_tools"),
    "filesystem": (".filesystem", "register_filesystem_tools"),
    "document": (".document", "register_document_tools"),
    "spreadsheet": (".spreadsheet", "register_spreadsheet_tools"),
    "desktop": (".desktop", "register_desktop_tools"),
    "code": (".code", "register_code_tools"),
    "shell": (".shell", "register_shell_tools"),
    "git": (".git", "register_git_tools"),
    "web": (".web", "register_web_tools"),
    "preview": (".preview", "register_preview_tools"),
    "memory": (".memory", "register_memory_tools"),
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


def _load_registrar(group: str) -> ToolRegistrar:
    try:
        module_name, attribute_name = BUILTIN_TOOL_GROUPS[group]
    except KeyError as exc:
        raise ValueError(f"unknown builtin tool group: {group}") from exc
    module = import_module(module_name, package=__name__)
    registrar = getattr(module, attribute_name)
    if not callable(registrar):
        raise TypeError(f"builtin tool registrar is not callable: {group}")
    return registrar


def register_builtin_tools(
    registry: ToolRegistry,
    groups: Iterable[str] | None = None,
) -> None:
    selected_groups = tuple(groups) if groups is not None else DEFAULT_BUILTIN_TOOL_GROUPS
    registered: set[str] = set()
    for group in selected_groups:
        if group in registered:
            continue
        registrar = _load_registrar(group)
        registrar(registry)
        registered.add(group)
