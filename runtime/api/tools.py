from __future__ import annotations

from .base import ApiHandler


class ToolsHandler(ApiHandler):
    def get(self) -> None:
        include_disabled = self.get_argument("include_disabled", "0") in {"1", "true", "yes"}
        tools = self.runtime.registry.list_specs()
        if not include_disabled:
            tools = [
                tool for tool in tools
                if self.runtime.settings.is_tool_enabled(tool.get("id", ""))
                and self.runtime.is_tool_available(tool)
            ]
        for tool in tools:
            tool["available"] = self.runtime.is_tool_available(tool)
            metadata_provider = getattr(self.runtime, "tool_runtime_metadata", None)
            if callable(metadata_provider):
                tool.update(metadata_provider(tool))
        self.finish_json({
            "success": True,
            "data": tools,
        })
