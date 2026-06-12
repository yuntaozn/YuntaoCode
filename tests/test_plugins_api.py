from __future__ import annotations

import json
from pathlib import Path

from runtime.api.plugins import load_ai_plugin_drafts, plugin_toggle_policy_error


def test_plugin_toggle_policy_allows_registered_plugin() -> None:
    assert plugin_toggle_policy_error("filesystem", {"filesystem"}, set()) is None


def test_plugin_toggle_policy_rejects_ai_draft_plugin() -> None:
    status, reason = plugin_toggle_policy_error("video-generator", {"filesystem"}, {"video-generator"})

    assert status == 403
    assert "read-only" in reason


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


def test_ai_plugin_draft_exposes_source_type(tmp_path: Path) -> None:
    plugin_root = tmp_path / "demo"
    plugin_root.mkdir()
    (plugin_root / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo", "tools": []}),
        encoding="utf-8",
    )

    drafts = load_ai_plugin_drafts(tmp_path)

    assert drafts[0]["source_type"] == "ai_draft"
