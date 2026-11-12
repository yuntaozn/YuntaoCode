from __future__ import annotations

from pathlib import Path

from runtime.visual_context import (
    build_visual_context_messages,
    model_supports_visual_context,
)
from runtime.visual_evidence import build_visual_evidence
from types import SimpleNamespace
from runtime.tool_result_evidence import tool_output_evidence
from runtime.visual_context import apply_visual_context_delivery
from tests.fakes.image_output import image_output


def test_model_supports_visual_context_defaults_to_enabled_for_model_configs() -> None:
    assert model_supports_visual_context({}) is True
    assert model_supports_visual_context({"supports_vision": True}) is True
    assert model_supports_visual_context({"supports_vision": False}) is False
    assert model_supports_visual_context({"supports_multimodal": True}) is True
    assert model_supports_visual_context({"image_input": True}) is True


def test_mcp_inline_image_uses_matching_tool_task_without_new_file_access(tmp_path):
    raw = image_output()
    task = SimpleNamespace(id="image-1", tool="mcp_demo.capture", status="success", output=raw)
    event = {
        "task_id": task.id, "tool": task.tool, "status": "success", "output": tool_output_evidence(raw),
        "output_source": {"kind": "tool_task_output", "task_id": task.id},
    }
    build = build_visual_context_messages(
        [event], model_config={"supports_vision": True}, workspace_path=str(tmp_path), data_dir=None,
        tool_task_lookup=lambda task_id: task if task_id == task.id else None,
    )
    assert len(build.messages) == 1
    assert build.messages[0]["content"][1]["type"] == "image_url"
    assert build.records[0]["source_ref"] == "tool_task:image-1:mcp_content:0"
    assert build.records[0]["path"] == ""
    assert build.records[0]["inspection_status"] in {"observed", "inspector_unavailable"}
    assert build.records[0]["injected_into_model_context"] is False
    accepted = apply_visual_context_delivery(build.records, {build.records[0]["image_ref"]: "accepted"})
    assert accepted[0]["injected_into_model_context"] is True
    task.tool = "mcp_other.capture"
    assert not build_visual_context_messages(
        [event], model_config={}, workspace_path=str(tmp_path), data_dir=None, tool_task_lookup=lambda _id: task,
    ).messages


def test_vision_disabled_reports_omission_without_attaching_pixels(tmp_path):
    task = SimpleNamespace(id="image-1", tool="mcp_demo.capture", status="success", output=image_output())
    event = {"tool": task.tool, "status": "success", "task_id": task.id,
             "output_source": {"kind": "tool_task_output", "task_id": task.id}}
    result = build_visual_context_messages(
        [event], model_config={"supports_vision": False}, workspace_path=str(tmp_path), data_dir=None,
        tool_task_lookup=lambda _id: task,
    )
    assert len(result.messages[0]["content"]) == 1
    assert result.records[0]["omission_reason"] == "model_vision_disabled"
    assert result.records[0]["injected_into_model_context"] is False


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
