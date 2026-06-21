from __future__ import annotations

from runtime.tool_registry import ToolRegistry

from .attachments import register_attachment_tools
from .code import register_code_tools
from .document import register_document_tools
from .filesystem import register_filesystem_tools
from .git import register_git_tools
from .memory import register_memory_tools
from .shell import register_shell_tools
from .spreadsheet import register_spreadsheet_tools
from .web import register_web_tools


def register_builtin_tools(registry: ToolRegistry) -> None:
    register_attachment_tools(registry)
    register_filesystem_tools(registry)
    register_document_tools(registry)
    register_spreadsheet_tools(registry)
    register_code_tools(registry)
    register_shell_tools(registry)
    register_git_tools(registry)
    register_web_tools(registry)
    register_memory_tools(registry)
