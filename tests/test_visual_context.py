from __future__ import annotations

from pathlib import Path

from runtime.visual_context import (
    build_visual_context_messages,
    model_supports_visual_context,
)
from runtime.visual_evidence import build_visual_evidence


def test_model_supports_visual_context_defaults_to_enabled_for_model_configs() -> None:
    assert model_supports_visual_context({}) is True
    assert model_supports_visual_context({"supports_vision": True}) is True
    assert model_supports_visual_context({"supports_vision": False}) is False
    assert model_supports_visual_context({"supports_multimodal": True}) is True
    assert model_supports_visual_context({"image_input": True}) is True


def test_visual_context_builds_multimodal_message_for_allowed_visual_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    data_dir.mkdir()
    image_path = data_dir / "task-artifacts" / "run-1" / "preview.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    event = {
        "tool": "preview.capture_file",
        "status": "success",
        "output": {
            "visual_evidence": build_visual_evidence(
                source_type="local_html",
                source_path=str(workspace / "index.html"),
                screenshot_path=str(image_path),
                artifact_kind="screenshot",
                format="png",
                width=800,
                height=600,
                has_runtime_errors=True,
            ),
        },
    }

    result = build_visual_context_messages(
        [event],
        model_config={"supports_vision": True},
        workspace_path=str(workspace),
        data_dir=data_dir,
    )

    assert len(result.messages) == 1
    message = result.messages[0]
    assert message["role"] == "user"
    assert message["content"][0]["type"] == "text"
    assert "Runtime visual evidence" in message["content"][0]["text"]
    assert message["content"][1]["type"] == "image_url"
    assert message["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert len(result.records) == 1
    assert result.records[0]["tool"] == "preview.capture_file"
    assert result.records[0]["path"] == str(image_path.resolve())
    assert result.records[0]["has_runtime_errors"] is True


def test_visual_context_skips_when_model_is_not_visual(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    image_path = workspace / "preview.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    event = {
        "tool": "preview.capture_file",
        "status": "success",
        "output": {
            "path": str(image_path),
            "artifact_kind": "image",
            "format": "png",
        },
    }

    result = build_visual_context_messages(
        [event],
        model_config={"supports_vision": False},
        workspace_path=str(workspace),
        data_dir=tmp_path / "data",
    )

    assert result.messages == []
    assert result.records == []


def test_visual_context_does_not_read_paths_outside_runtime_boundaries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = tmp_path / "data"
    outside = tmp_path / "outside"
    workspace.mkdir()
    data_dir.mkdir()
    outside.mkdir()
    image_path = outside / "preview.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    event = {
        "tool": "mcp_blender.get_viewport_screenshot",
        "status": "success",
        "output": {
            "visual_evidence": build_visual_evidence(
                source_type="mcp",
                screenshot_path=str(image_path),
                artifact_kind="screenshot",
                format="png",
            ),
        },
    }

    result = build_visual_context_messages(
        [event],
        model_config={"supports_vision": True},
        workspace_path=str(workspace),
        data_dir=data_dir,
    )

    assert result.messages == []
    assert result.records == []
