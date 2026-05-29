from __future__ import annotations

from collections import defaultdict
from typing import Any

from .base import ApiHandler
from .. import i18n


class PluginsHandler(ApiHandler):
    def get(self) -> None:
        lang = self.get_lang()
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for tool in self.runtime.registry.list_specs():
            plugin_id = tool["id"].split(".", 1)[0]
            groups[plugin_id].append(tool)

        plugin_settings = self.runtime.settings.get_plugin_settings()

        plugins = []
        for plugin_id, tools in groups.items():
            dependency_status = self.runtime.registry.check_plugin_dependencies(plugin_id)
            enabled = plugin_settings.get(plugin_id, {}).get("enabled", True)
            plugins.append({
                "id": plugin_id,
                "name": i18n.t(f"plugin.name.{plugin_id}", lang) or plugin_id,
                "description": i18n.t(f"plugin.desc.{plugin_id}", lang) or i18n.t("plugin.desc.default", lang),
                "enabled": enabled,
                "local_only": all(bool(tool.get("local_only", True)) for tool in tools),
                "dependencies": dependency_status,
                "tools": tools,
            })
        self.finish_json({"success": True, "data": plugins})

    def post(self) -> None:
        payload = self.parse_json_body()
        plugin_id = str(payload.get("plugin_id") or "").strip()
        enabled = bool(payload.get("enabled", True))
        self.runtime.settings.update_plugin_setting(plugin_id, enabled)
        self.finish_json({"success": True})


def plugin_id_to_name(plugin_id: str, lang: str = "") -> str:
    """Translate plugin ID to display name. Falls back to ID itself."""
    return i18n.t(f"plugin.name.{plugin_id}", lang) or plugin_id
