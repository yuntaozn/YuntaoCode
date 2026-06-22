from __future__ import annotations

import pytest

from runtime.capability_pack_store import CapabilityPackStore


def test_capability_pack_store_persists_method_skill_and_files(tmp_path) -> None:
    store = CapabilityPackStore(tmp_path / "capability-packs")

    pack = store.create({
        "id": "long-doc-method",
        "name": "Long Document Method",
        "description": "Reusable long document writing method.",
        "instructions": "Write in chunks and verify evidence.",
        "files": {
            "SKILL.md": "# Long Document Method\n",
            "examples/success.md": "Verified long document task.",
        },
    })

    reloaded = CapabilityPackStore(tmp_path / "capability-packs")
    loaded = reloaded.get(pack.id)

    assert loaded is not None
    assert loaded.kind == "method_skill"
    assert loaded.entry.kind == "instructions"
    assert loaded.permissions.filesystem == "none"
    assert (tmp_path / "capability-packs" / "items" / pack.id / "SKILL.md").exists()


def test_capability_pack_export_includes_manifest_and_files(tmp_path) -> None:
    store = CapabilityPackStore(tmp_path / "capability-packs")
    pack = store.create({
        "id": "web-review-method",
        "name": "Web Review Method",
        "files": {"SKILL.md": "# Web Review\nUse web tools before claiming no access.\n"},
    })

    bundle = store.export_bundle(pack.id)

    assert bundle["schema_version"] == "capability_pack_export.v1"
    assert bundle["pack"]["id"] == "web-review-method"
    assert bundle["files"][0]["path"] == "SKILL.md"
    assert "Use web tools" in bundle["files"][0]["content"]


def test_tool_adapter_pack_stays_as_draft_descriptor(tmp_path) -> None:
    store = CapabilityPackStore(tmp_path / "capability-packs")

    pack = store.create({
        "id": "video-adapter",
        "name": "Video Adapter",
        "kind": "tool_adapter",
        "entry": {
            "kind": "command",
            "main": "src/render.py",
            "command": "python",
            "args": ["src/render.py"],
        },
        "permissions": {"filesystem": "workspace", "shell": "confirm_each"},
    })

    assert pack.kind == "tool_adapter"
    assert pack.state == "draft"
    assert pack.entry.command == "python"
    assert pack.permissions.shell == "confirm_each"


def test_capability_pack_rejects_unsafe_file_path(tmp_path) -> None:
    store = CapabilityPackStore(tmp_path / "capability-packs")

    with pytest.raises(ValueError):
        store.create({
            "id": "bad-path",
            "name": "Bad Path",
            "files": {"../outside.md": "bad"},
        })

    assert store.get("bad-path") is None
