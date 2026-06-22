from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .base import ApiHandler
from .. import i18n


RUNTIME_CAPABILITY_GROUPS = {"attachment", "memory"}
FOUNDATION_CAPABILITY_GROUPS = {"filesystem", "code", "shell", "git"}
OPTIONAL_CAPABILITY_GROUPS = {"document", "web"}
CAPABILITY_PACK_SOURCE_TYPE = "capability_pack"


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
            source_type = next(iter(source_types)) if len(source_types) == 1 else "mixed"
            provider_kind = plugin_provider_kind(plugin_id, source_type)
            plugins.append({
                "id": plugin_id,
                "name": i18n.t(f"plugin.name.{plugin_id}", lang) or plugin_id,
                "description": i18n.t(f"plugin.desc.{plugin_id}", lang) or i18n.t("plugin.desc.default", lang),
                "source_type": source_type,
                "source_id": next(iter(source_ids)) if len(source_ids) == 1 else None,
                "provider_kind": provider_kind,
                "provider_label": i18n.t(f"plugins.kind.{provider_kind}", lang) or provider_kind,
                "toggle_locked": provider_kind in {"runtime_capability", "mcp_capability"},
                "enabled": enabled,
                "local_only": all(bool(tool.get("local_only", True)) for tool in tools),
                "dependencies": dependency_status,
                "tools": tools,
            })
        capability_pack_root = self.runtime.settings.data_dir / "capability-packs"
        if hasattr(self.runtime, "capability_packs"):
            capability_pack_root = self.runtime.capability_packs.root_path
            plugins.extend(load_capability_pack_plugins(self.runtime.capability_packs.list(), lang))
        legacy_ai_plugin_root = self.runtime.settings.data_dir / "ai-plugins"
        plugins.extend(load_ai_plugin_drafts(legacy_ai_plugin_root, lang))
        self.finish_json({
            "success": True,
            "data": plugins,
            "meta": {
                "capability_pack_root": str(capability_pack_root),
                "ai_plugin_draft_root": str(legacy_ai_plugin_root),
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
        runtime_managed_ids = {
            tool["id"].split(".", 1)[0]
            for tool in self.runtime.registry.list_specs()
            if tool["id"].split(".", 1)[0] in RUNTIME_CAPABILITY_GROUPS
        }
        legacy_ai_plugin_root = self.runtime.settings.data_dir / "ai-plugins"
        draft_ids = {draft["id"] for draft in load_ai_plugin_drafts(legacy_ai_plugin_root, lang)}
        capability_pack_ids = {
            pack.id
            for pack in self.runtime.capability_packs.list(include_archived=True)
        } if hasattr(self.runtime, "capability_packs") else set()
        policy_error = plugin_toggle_policy_error(
            plugin_id,
            registered_plugin_ids,
            draft_ids,
            managed_plugin_ids,
            runtime_managed_ids,
            capability_pack_ids,
        )
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


def plugin_provider_kind(plugin_id: str, source_type: str = "builtin") -> str:
    if source_type == "mcp":
        return "mcp_capability"
    if source_type == CAPABILITY_PACK_SOURCE_TYPE:
        return "capability_pack"
    if source_type == "ai_draft":
        return "ai_draft"
    if source_type not in {"builtin", "mixed"}:
        return "external_plugin"
    if plugin_id in RUNTIME_CAPABILITY_GROUPS:
        return "runtime_capability"
    if plugin_id in FOUNDATION_CAPABILITY_GROUPS:
        return "builtin_foundation"
    if plugin_id in OPTIONAL_CAPABILITY_GROUPS:
        return "builtin_optional"
    if source_type == "mixed":
        return "mixed"
    return "builtin_other"


def plugin_toggle_policy_error(
    plugin_id: str,
    registered_plugin_ids: set[str],
    draft_plugin_ids: set[str],
    managed_plugin_ids: set[str] | None = None,
    runtime_managed_ids: set[str] | None = None,
    capability_pack_ids: set[str] | None = None,
) -> tuple[int, str] | None:
    if not plugin_id:
        return 400, "plugin_id is required"
    if plugin_id in draft_plugin_ids:
        return 403, "AI plugin drafts are read-only and cannot be enabled from the plugin settings API"
    if plugin_id in (managed_plugin_ids or set()):
        return 403, "MCP capabilities are managed from the MCP services API"
    if plugin_id in (runtime_managed_ids or set()):
        return 403, "Runtime capabilities are managed by their own runtime settings"
    if plugin_id in (capability_pack_ids or set()):
        return 403, "Capability packs are managed from the capability pack API"
    if plugin_id not in registered_plugin_ids:
        return 404, f"unknown plugin: {plugin_id}"
    return None


def load_capability_pack_plugins(packs: list[Any], lang: str = "") -> list[dict[str, Any]]:
    return [capability_pack_to_public_dict(pack, lang) for pack in packs]


def capability_pack_to_public_dict(pack: Any, lang: str = "") -> dict[str, Any]:
    zh = lang.lower().startswith("zh")
    kind_label_key = f"plugins.capability_pack_kind.{getattr(pack, 'kind', 'method_skill')}"
    tools = [{
        "id": f"capability_pack.{pack.id}",
        "name": pack.name,
        "description": pack.summary or pack.description,
        "requires_confirmation": False,
        "local_only": True,
    }]
    permissions = pack.permissions.to_dict() if hasattr(pack.permissions, "to_dict") else {}
    return {
        "id": pack.id,
        "name": pack.name,
        "description": pack.description or pack.summary or (
            "本机能力包" if zh else "Local capability pack"
        ),
        "source_type": CAPABILITY_PACK_SOURCE_TYPE,
        "provider_kind": "capability_pack",
        "provider_label": i18n.t("plugins.kind.capability_pack", lang) or "Capability Packs",
        "enabled": pack.state == "enabled",
        "toggle_locked": True,
        "capability_pack": True,
        "pack_kind": pack.kind,
        "pack_kind_label": i18n.t(kind_label_key, lang) or pack.kind,
        "stage": pack.state,
        "version": pack.version,
        "local_only": True,
        "dependencies": {},
        "dependency_requirements": {},
        "permissions": permissions,
        "tools": tools,
    }


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
        "provider_kind": "ai_draft",
        "provider_label": i18n.t("plugins.kind.ai_draft", lang) or "AI Draft",
        "enabled": False,
        "toggle_locked": True,
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
