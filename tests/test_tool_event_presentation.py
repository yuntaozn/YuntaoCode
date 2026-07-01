from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.tool_event_presentation import (
    compact_tool_payload,
    summarize_tool_payload,
    tool_output_preview,
    tool_progress_message,
    tool_progress_snapshot,
)


@dataclass
class FakeTask:
    id: str = "task-1"
    status: str = "running"
    logs: list[dict[str, Any]] = field(default_factory=list)


def test_shell_output_preview_includes_timeout_fields() -> None:
    preview = tool_output_preview(
        "shell.run_command",
        {"exit_code": 1, "stdout": "", "stderr": "", "timed_out": True, "timeout": 5},
    )

    assert preview is not None
    assert preview["type"] == "shell"
    assert preview["timed_out"] is True
    assert preview["timeout"] == 5
    assert preview["debug_session"]["timed_out"] is True
    assert preview["debug_session"]["status"] == "timed_out"


def test_shell_output_preview_includes_diagnostics() -> None:
    preview = tool_output_preview(
        "shell.run_command",
        {
            "exit_code": 1,
            "stdout": "",
            "stderr": "Error: Cannot find module",
            "timed_out": False,
            "timeout": 30,
            "failure_message": "Node -c/--check expects a JavaScript file path.",
            "diagnostics": [{"code": "node_check_inline_script"}],
        },
    )

    assert preview is not None
    assert preview["failure_message"].startswith("Node -c")
    assert preview["diagnostics"][0]["code"] == "node_check_inline_script"
    assert preview["debug_session"]["diagnostic_count"] == 1


def test_web_capture_preview_keeps_visual_artifact_fields() -> None:
    preview = tool_output_preview(
        "web.capture_page",
        {
            "url": "https://example.com",
            "status_code": 200,
            "title": "Example",
            "path": "D:/workspace/capture.png",
            "format": "png",
            "artifact_kind": "screenshot",
        },
    )

    assert preview is not None
    assert preview["type"] == "web"
    assert preview["path"] == "D:/workspace/capture.png"
    assert preview["format"] == "png"
    assert preview["artifact_kind"] == "screenshot"
    assert preview["visual_evidence"]["path"] == "D:/workspace/capture.png"


def test_capability_preview_keeps_nested_visual_evidence() -> None:
    preview = tool_output_preview(
        "mcp_demo.get_viewport_screenshot",
        {
            "content": "saved screenshot",
            "roles": ["verification"],
            "artifacts": ["image", "visual_evidence"],
            "visual_evidence": {
                "kind": "visual_evidence",
                "source": {"type": "mcp"},
                "artifact": {
                    "kind": "image",
                    "path": "D:/workspace/scene.png",
                    "format": "png",
                },
                "runtime": {"has_errors": False},
                "model_context": {"eligible": True, "modality": "image"},
            },
        },
    )

    assert preview is not None
    assert preview["type"] == "capability_result"
    assert preview["visual_evidence"]["path"] == "D:/workspace/scene.png"
    assert preview["visual_evidence"]["model_context_eligible"] is True


def test_preview_capture_preview_keeps_visual_debug_evidence() -> None:
    preview = tool_output_preview(
        "preview.capture_local_html",
        {
            "source_type": "local_html",
            "source_path": "D:/workspace/viewer.html",
            "served_via": "localhost",
            "served_root": "D:/workspace",
            "url": "http://127.0.0.1:51234/viewer.html",
            "title": "Viewer",
            "path": "D:/workspace/.yuntaocode/tmp/preview/viewer.png",
            "format": "png",
            "size": 1234,
            "width": 1440,
            "height": 1000,
            "full_page": True,
            "artifact_kind": "screenshot",
            "roles": ["verification"],
            "artifacts": ["screenshot", "visual_evidence"],
            "verification_strength": "standard",
            "console_errors": [{"type": "error", "text": "boom"}],
            "console_warnings": [{"type": "warning", "text": "careful"}],
            "page_errors": ["ReferenceError"],
            "failed_requests": [{"url": "missing.glb", "method": "GET"}],
            "has_runtime_errors": True,
        },
    )

    assert preview is not None
    assert preview["type"] == "preview"
    assert preview["source_type"] == "local_html"
    assert preview["served_via"] == "localhost"
    assert preview["path"].endswith("viewer.png")
    assert preview["artifact_kind"] == "screenshot"
    assert preview["roles"] == ["verification"]
    assert preview["artifacts"] == ["screenshot", "visual_evidence"]
    assert preview["has_runtime_errors"] is True
    assert preview["console_errors"][0]["text"] == "boom"
    assert preview["failed_requests"][0]["url"] == "missing.glb"
    assert preview["visual_evidence"]["kind"] == "visual_evidence"
    assert preview["visual_evidence"]["path"].endswith("viewer.png")
    assert preview["visual_evidence"]["has_runtime_errors"] is True
    assert preview["visual_evidence"]["console_error_count"] == 1
    assert preview["debug_session"] is None


def test_preview_payload_summary_keeps_visual_evidence_summary() -> None:
    summary = summarize_tool_payload({
        "tool": "preview.capture_url",
        "status": "success",
        "output": {
            "type": "preview_capture",
            "source_type": "url",
            "url": "https://example.com",
            "path": "D:/workspace/preview.png",
            "format": "png",
            "artifact_kind": "screenshot",
            "width": 1200,
            "height": 800,
            "console_errors": [{"type": "error", "text": "boom"}],
            "has_runtime_errors": True,
        },
    })

    output = summary["output"]
    assert output["visual_evidence"]["path"] == "D:/workspace/preview.png"
    assert output["visual_evidence"]["source_type"] == "url"
    assert output["visual_evidence"]["has_runtime_errors"] is True
    assert output["console_errors"][0]["text"] == "boom"
    assert output["debug_session"] is None


def test_preview_interaction_preview_keeps_trace_and_dom_text() -> None:
    output = {
        "type": "preview_interaction",
        "source_type": "local_html",
        "source_path": "D:/workspace/viewer.html",
        "url": "http://127.0.0.1:51234/viewer.html",
        "path": "D:/workspace/after.png",
        "format": "png",
        "artifact_kind": "screenshot",
        "artifacts": ["screenshot", "visual_evidence", "interaction_trace", "dom_text"],
        "roles": ["verification"],
        "verification_strength": "standard",
        "interaction": {
            "action_count": 2,
            "assertion_failed_count": 0,
            "actions": [{"action": "click", "ok": True}],
        },
        "text": "开始学习\n答题完成后显示反馈",
        "text_chars": 16,
        "has_runtime_errors": False,
    }

    preview = tool_output_preview("preview.interact_page", output)
    summary = summarize_tool_payload({
        "tool": "preview.interact_page",
        "status": "success",
        "output": output,
    })

    assert preview is not None
    assert preview["interaction"]["action_count"] == 2
    assert "答题完成后" in preview["text"]
    assert preview["text_chars"] == 16
    assert summary["output"]["interaction"]["assertion_failed_count"] == 0
    assert "开始学习" in summary["output"]["text"]
    assert summary["output"]["truncated_for_context"] is False


def test_shell_payload_summary_keeps_debug_session_summary() -> None:
    summary = summarize_tool_payload({
        "tool": "shell.run_command",
        "status": "success",
        "output": {
            "command": "node --check app.js",
            "executable": "node",
            "args": ["--check", "app.js"],
            "cwd": "D:/workspace",
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "timed_out": False,
            "timeout": 30,
        },
    })

    output = summary["output"]
    assert output["debug_session"]["command"] == "node --check app.js"
    assert output["debug_session"]["exit_code"] == 0
    assert output["debug_session"]["status"] == "success"


def test_filesystem_apply_changes_preview_lists_changed_paths() -> None:
    preview = tool_output_preview(
        "filesystem.apply_changes",
        {
            "paths": ["D:/workspace/a.txt", "D:/workspace/b.txt"],
            "changed_paths": ["D:/workspace/a.txt", "D:/workspace/b.txt"],
            "created_paths": ["D:/workspace/a.txt"],
            "updated_paths": [],
            "deleted_paths": ["D:/workspace/b.txt"],
            "operation_count": 2,
            "changed_file_count": 2,
            "effects": ["file_write", "file_delete", "local_state_change"],
            "roles": ["deliverable", "verification"],
            "verification_strength": "standard",
        },
    )

    assert preview is not None
    assert preview["type"] == "file_change_set"
    assert preview["operation_count"] == 2
    assert preview["changed_file_count"] == 2
    assert preview["created_paths"] == ["D:/workspace/a.txt"]
    assert preview["deleted_paths"] == ["D:/workspace/b.txt"]


def test_document_translation_progress_message_includes_counts() -> None:
    task = FakeTask(logs=[
        {
            "level": "info",
            "message": "translation progress 10/911",
            "time": "2026-06-02T14:04:36+00:00",
            "data": {
                "translated": 10,
                "failed": 0,
                "engine": "model",
                "source_chars_done": 24000,
                "source_chars_total": 240000,
            },
        }
    ])

    progress = tool_progress_snapshot("document.translate_docx", task)
    message = tool_progress_message(
        "document.translate_docx",
        task,
        420,
        180,
        progress,
        display_name="翻译 Word 文档",
    )

    assert progress["done"] == 10
    assert progress["total"] == 911
    assert progress["percent"] == 1.1
    assert "10/911" in message
    assert "字符进度 10.0%" in message
    assert "最近 180s 没有新进度" in message


def test_summarize_tool_payload_compacts_large_scan_results() -> None:
    payload = {
        "tool": "filesystem.scan_folder",
        "output": {
            "root": r"D:\demo",
            "folder_count": 1,
            "file_count": 300,
            "folders": ["src"],
            "files": [f"file_{index}.txt" for index in range(300)],
        },
    }

    compact = summarize_tool_payload(payload)
    text = compact_tool_payload(payload)

    assert compact["output"]["truncated_for_context"] is True
    assert len(compact["output"]["files"]) == 260
    assert "file_299.txt" not in text


def test_summarize_read_file_payload_uses_bounded_text_budgets() -> None:
    payload = {
        "tool": "filesystem.read_file",
        "output": {
            "path": "large.py",
            "content": "c" * 60000,
            "raw_content": "r" * 60000,
            "total_lines": 4000,
            "next_start_line": 201,
            "suggested_next_call": {
                "tool": "filesystem.read_file",
                "input": {"path": "large.py", "start_line": 201},
            },
            "integrity": {"checked": True, "valid": True, "issues": []},
        },
    }

    compact = summarize_tool_payload(payload)
    output = compact["output"]

    assert output["path"] == "large.py"
    assert output["integrity"]["valid"] is True
    assert output["next_start_line"] == 201
    assert output["truncated_for_context"] is True
    assert output["raw_content_truncated_for_context"] is True
    assert len(output["content"]) < 22000
    assert len(output["raw_content"]) < 14000
