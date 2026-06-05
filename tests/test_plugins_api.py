from __future__ import annotations

from runtime.api.plugins import plugin_toggle_policy_error


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
