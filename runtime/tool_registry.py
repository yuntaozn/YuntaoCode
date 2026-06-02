from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .tool_aliases import TOOL_ID_ALIASES, normalize_tool_id, normalize_tool_syntax


ToolHandler = Callable[[dict[str, Any], Any], Awaitable[dict[str, Any]]]


DEFAULT_TOOL_ID_ALIASES: dict[str, str] = TOOL_ID_ALIASES


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_confirmation: bool = False
    local_only: bool = True
    optional_dependencies: list[str] | None = None

    def check_dependencies(self) -> dict[str, bool]:
        if not self.optional_dependencies:
            return {}
        result = {}
        for dep in self.optional_dependencies:
            try:
                # 静默导入，抑制第三方库自身打印的警告（如 weasyprint 的 GTK 缺失警告）
                with contextlib.redirect_stderr(io.StringIO()):
                    __import__(dep)
                result[dep] = True
            except Exception:
                result[dep] = False
        return result

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "requires_confirmation": self.requires_confirmation,
            "local_only": self.local_only,
            "dependencies": self.check_dependencies(),
        }


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = dict(DEFAULT_TOOL_ID_ALIASES)

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.id in self._tools:
            raise ValueError(f"tool already registered: {spec.id}")
        self._tools[spec.id] = Tool(spec=spec, handler=handler)

    def register_alias(self, alias: str, tool_id: str) -> None:
        self._aliases[normalize_tool_syntax(alias)] = normalize_tool_syntax(tool_id)

    def resolve_id(self, tool_id: str) -> str:
        value = normalize_tool_syntax(tool_id)
        if self._aliases == DEFAULT_TOOL_ID_ALIASES:
            return normalize_tool_id(value)
        return self._aliases.get(value, value)

    def get(self, tool_id: str) -> Tool:
        resolved_id = self.resolve_id(tool_id)
        try:
            return self._tools[resolved_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc

    def list_specs(self) -> list[dict[str, Any]]:
        return [tool.spec.to_public_dict() for tool in self._tools.values()]

    def check_plugin_dependencies(self, plugin_id: str) -> dict[str, bool]:
        result = {}
        for tool in self._tools.values():
            if tool.spec.id.startswith(f"{plugin_id}.") and tool.spec.optional_dependencies:
                deps = tool.spec.check_dependencies()
                for dep, available in deps.items():
                    if dep not in result:
                        result[dep] = available
                    else:
                        result[dep] = result[dep] and available
        return result
