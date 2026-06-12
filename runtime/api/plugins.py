from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
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
            source_types = {str(tool.get("source_type") or "builtin") for tool in tools}
            source_ids = {str(tool.get("source_id") or plugin_id) for tool in tools}
            plugins.append({
                "id": plugin_id,
                "name": i18n.t(f"plugin.name.{plugin_id}", lang) or plugin_id,
                "description": i18n.t(f"plugin.desc.{plugin_id}", lang) or i18n.t("plugin.desc.default", lang),
                "source_type": next(iter(source_types)) if len(source_types) == 1 else "mixed",
                "source_id": next(iter(source_ids)) if len(source_ids) == 1 else None,
                "enabled": enabled,
                "local_only": all(bool(tool.get("local_only", True)) for tool in tools),
                "dependencies": dependency_status,
                "tools": tools,
            })
        ai_plugin_root = self.runtime.settings.data_dir / "ai-plugins"
        plugins.extend(load_ai_plugin_drafts(ai_plugin_root, lang))
        self.finish_json({
            "success": True,
            "data": plugins,
            "meta": {
                "ai_plugin_draft_root": str(ai_plugin_root),
            },
        })

    def post(self) -> None:
        lang = self.get_lang()
        payload = self.parse_json_body()
        plugin_id = str(payload.get("plugin_id") or "").strip()
        enabled = bool(payload.get("enabled", True))
        registered_plugin_ids = {tool["id"].split(".", 1)[0] for tool in self.runtime.registry.list_specs()}
        managed_plugin_ids = {
            tool["id"].split(".", 1)[0]
            for tool in self.runtime.registry.list_specs()
            if tool.get("source_type") == "mcp"
        }
        ai_plugin_root = self.runtime.settings.data_dir / "ai-plugins"
        draft_ids = {draft["id"] for draft in load_ai_plugin_drafts(ai_plugin_root, lang)}
        policy_error = plugin_toggle_policy_error(plugin_id, registered_plugin_ids, draft_ids, managed_plugin_ids)
        if policy_error:
            status, reason = policy_error
            self.set_status(status)
            self.finish_json({"success": False, "error": reason})
            return
        self.runtime.settings.update_plugin_setting(plugin_id, enabled)
        self.finish_json({"success": True})


def plugin_id_to_name(plugin_id: str, lang: str = "") -> str:
    """Translate plugin ID to display name. Falls back to ID itself."""
    return i18n.t(f"plugin.name.{plugin_id}", lang) or plugin_id


def plugin_toggle_policy_error(
    plugin_id: str,
    registered_plugin_ids: set[str],
    draft_plugin_ids: set[str],
    managed_plugin_ids: set[str] | None = None,
) -> tuple[int, str] | None:
    if not plugin_id:
        return 400, "plugin_id is required"
    if plugin_id in draft_plugin_ids:
        return 403, "AI plugin drafts are read-only and cannot be enabled from the plugin settings API"
    if plugin_id in (managed_plugin_ids or set()):
        return 403, "MCP capabilities are managed from the MCP services API"
    if plugin_id not in registered_plugin_ids:
        return 404, f"unknown plugin: {plugin_id}"
    return None


def load_ai_plugin_drafts(root: Path, lang: str = "") -> list[dict[str, Any]]:
    if not root.exists():
        return []

    drafts: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/plugin.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        draft = ai_plugin_draft_to_public_dict(manifest, manifest_path, lang)
        if draft:
            drafts.append(draft)
    return drafts


def ai_plugin_draft_to_public_dict(
    manifest: dict[str, Any],
    manifest_path: Path,
    lang: str = "",
) -> dict[str, Any] | None:
    plugin_id = str(manifest.get("id") or "").strip()
    if not plugin_id:
        return None

    zh = lang.lower().startswith("zh")
    tools = []
    for tool in manifest.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        tool_id = str(tool.get("id") or "").strip()
        if not tool_id:
            continue
        tools.append({
            "id": tool_id,
            "name": tool.get("name_zh" if zh else "name") or tool.get("name") or tool_id,
            "description": tool.get("description_zh" if zh else "description") or tool.get("description") or "",
            "requires_confirmation": bool(tool.get("requires_confirmation", False)),
            "local_only": bool(tool.get("local_only", True)),
        })

    runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
    return {
        "id": plugin_id,
        "name": manifest.get("name_zh" if zh else "name") or manifest.get("name") or plugin_id,
        "description": manifest.get("description_zh" if zh else "description") or manifest.get("description") or "",
        "source_type": "ai_draft",
        "enabled": False,
        "loadable": bool(runtime.get("loadable", False)),
        "ai_draft": True,
        "stage": runtime.get("stage") or "draft",
        "manifest_path": str(manifest_path),
        "local_only": True,
        "dependencies": {},
        "dependency_requirements": manifest.get("dependencies") or {},
        "permissions": manifest.get("permissions") or {},
        "tools": tools,
    }
