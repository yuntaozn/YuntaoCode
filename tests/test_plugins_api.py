from __future__ import annotations

import json
from pathlib import Path

from runtime.api.plugins import (
    capability_pack_to_public_dict,
    load_ai_plugin_drafts,
    plugin_provider_kind,
    plugin_toggle_policy_error,
)
from runtime.core.capability_pack import CapabilityPack


def test_plugin_toggle_policy_allows_registered_plugin() -> None:
    assert plugin_toggle_policy_error("filesystem", {"filesystem"}, set()) is None


def test_plugin_toggle_policy_rejects_ai_draft_plugin() -> None:
    status, reason = plugin_toggle_policy_error("video-generator", {"filesystem"}, {"video-generator"})

    assert status == 403
    assert "read-only" in reason


def test_plugin_toggle_policy_rejects_capability_pack() -> None:
    status, reason = plugin_toggle_policy_error(
        "doc-method",
        {"filesystem"},
        set(),
        capability_pack_ids={"doc-method"},
    )

    assert status == 403
    assert "Capability packs" in reason


def test_plugin_toggle_policy_rejects_unknown_plugin() -> None:
    status, reason = plugin_toggle_policy_error("missing", {"filesystem"}, set())

    assert status == 404
    assert "unknown plugin" in reason


def test_plugin_toggle_policy_rejects_mcp_managed_capability() -> None:
    status, reason = plugin_toggle_policy_error(
        "demo",
        {"demo"},
        set(),
        {"demo"},
    )

    assert status == 403
    assert "MCP" in reason


def test_plugin_toggle_policy_rejects_runtime_managed_capability() -> None:
    status, reason = plugin_toggle_policy_error(
        "memory",
        {"memory"},
        set(),
        set(),
        {"memory"},
    )

    assert status == 403
    assert "Runtime capabilities" in reason


def test_plugin_provider_kind_classifies_builtin_boundaries() -> None:
    assert plugin_provider_kind("memory") == "runtime_capability"
    assert plugin_provider_kind("attachment") == "runtime_capability"
    assert plugin_provider_kind("filesystem") == "builtin_foundation"
    assert plugin_provider_kind("document") == "builtin_optional"
    assert plugin_provider_kind("blender", "mcp") == "mcp_capability"
    assert plugin_provider_kind("doc-method", "capability_pack") == "capability_pack"
    assert plugin_provider_kind("demo", "ai_draft") == "ai_draft"


def test_capability_pack_exposes_read_only_provider() -> None:
    public = capability_pack_to_public_dict(CapabilityPack(id="doc-method", name="Doc Method"))

    assert public["source_type"] == "capability_pack"
    assert public["provider_kind"] == "capability_pack"
    assert public["toggle_locked"] is True
    assert public["tools"][0]["id"] == "capability_pack.doc-method"


def test_ai_plugin_draft_exposes_source_type(tmp_path: Path) -> None:
    plugin_root = tmp_path / "demo"
    plugin_root.mkdir()
    (plugin_root / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo", "tools": []}),
        encoding="utf-8",
    )

    drafts = load_ai_plugin_drafts(tmp_path)

    assert drafts[0]["source_type"] == "ai_draft"
    assert drafts[0]["provider_kind"] == "ai_draft"
    assert drafts[0]["toggle_locked"] is True
