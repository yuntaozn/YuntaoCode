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
