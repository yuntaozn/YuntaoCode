from __future__ import annotations

import json

from runtime.run_result import build_run_result
from runtime.tool_event_presentation import tool_output_preview
from runtime.tool_result_evidence import tool_output_evidence
from runtime.tool_event_presentation import compact_tool_payload
from tests.fakes.image_output import image_output


def test_preview_budget_does_not_cut_result_paths_or_diagnostics(tmp_path):
    paths = [str(tmp_path / f"file_{i}.txt") for i in range(41)]
    output = {"paths": paths, "file_count": 41, "diagnostics": [{"message": str(i)} for i in range(30)]}
    evidence = tool_output_evidence(output)
    preview = tool_output_preview("code.apply_patch", output)
    result = build_run_result(
        workspace_path=str(tmp_path), mode="terminal", change_summary=None,
        tool_events=[{"tool": "code.apply_patch", "status": "success", "output": evidence}],
    )

    assert len(preview["paths"]) == 40
    assert len(result["written_paths"]) == 41
    assert len(evidence["diagnostics"]) == 30
    evidence["paths"].clear()
    assert len(output["paths"]) == 41


def test_inline_media_is_referenced_without_removing_result_metadata():
    media = [{"type": "image", "mimeType": "image/png", "data": "base64-pixels"}]
    output = {
        "mcp_content": media, "content": json.dumps(media, ensure_ascii=False),
        "path": "preview.png", "effects": ["file_write"], "roles": ["evidence"],
        "structured_content": {"objects": ["model"], "text": "full result"},
    }
    evidence = tool_output_evidence(output)

    assert "base64-pixels" not in json.dumps(evidence)
    assert evidence["path"] == "preview.png"
    assert evidence["effects"] == ["file_write"]
    assert evidence["structured_content"] == output["structured_content"]
    assert output["mcp_content"][0]["data"] == "base64-pixels"


def test_model_tool_text_has_media_metadata_without_base64():
    raw = image_output()
    raw["content"] = json.dumps(raw["mcp_content"], ensure_ascii=False)
    raw["structured_content"] = {"capture_status": "ok"}
    text = compact_tool_payload({"tool": "mcp_demo.capture", "output": tool_output_evidence(raw)})
    assert raw["mcp_content"][0]["data"] not in text
    assert "inline_images" in text
    assert "capture_status" in text
