from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.api.conversations import ConversationMessagesStreamHandler


def _handler_with_contract() -> ConversationMessagesStreamHandler:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._active_task_contract = {
        "intent": "document_export",
        "expected_document_coverage": True,
    }
    return handler


def test_document_contract_guard_blocks_translation_script_write() -> None:
    handler = _handler_with_contract()

    message = handler._document_contract_tool_guard(
        "filesystem.write_file",
        {
            "path": r"D:\code\测试项目\象棋\translate_to_chinese.py",
            "content": "from deep_translator import GoogleTranslator\n",
        },
    )

    assert message
    assert "document.translate_docx" in message


def test_document_contract_guard_blocks_translation_shell_fallback() -> None:
    handler = _handler_with_contract()

    message = handler._document_contract_tool_guard(
        "shell.run_command",
        {
            "command": "python",
            "args": ["translate_to_chinese.py"],
        },
    )

    assert message
    assert "document.translate_docx" in message


def test_document_contract_guard_blocks_pdf_to_word_script_write() -> None:
    handler = _handler_with_contract()

    message = handler._document_contract_tool_guard(
        "filesystem.write_file",
        {
            "path": r"D:\code\测试项目\象棋\pdf_to_word.py",
            "content": "from pdf2docx import Converter\nConverter(src).convert(dst)\n",
        },
    )

    assert message
    assert "document.extract_pdf_to_docx" in message
    assert "mode=text_with_images" in message


def test_document_contract_guard_blocks_pdf_to_word_shell_fallback() -> None:
    handler = _handler_with_contract()

    message = handler._document_contract_tool_guard(
        "shell.run_command",
        {
            "command": "python",
            "args": ["-m", "pdf2docx", "convert", "a.pdf", "a.docx"],
        },
    )

    assert message
    assert "document.extract_pdf_to_docx" in message


def test_document_contract_guard_allows_builtin_translation_tool() -> None:
    handler = _handler_with_contract()

    message = handler._document_contract_tool_guard(
        "document.translate_docx",
        {
            "path": r"D:\code\测试项目\象棋\国际象棋历史_提取结果.docx",
            "output_path": r"D:\code\测试项目\象棋\国际象棋历史_中文版.docx",
            "engine": "model",
        },
    )

    assert message == ""


@dataclass
class FakeTask:
    id: str = "task-1"
    status: str = "running"
    logs: list[dict[str, Any]] = field(default_factory=list)


def test_document_translation_progress_message_includes_counts() -> None:
    handler = _handler_with_contract()
    handler._tool_display_name = lambda _tool_id: "翻译 Word 文档"
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

    progress = handler._tool_progress_snapshot("document.translate_docx", task)
    message = handler._tool_progress_message("document.translate_docx", task, 420, 180, progress)

    assert progress["done"] == 10
    assert progress["total"] == 911
    assert progress["percent"] == 1.1
    assert "10/911" in message
    assert "字符进度 10.0%" in message
    assert "最近 180s 没有新进度" in message


def test_pdf_to_docx_progress_message_includes_page_counts() -> None:
    handler = _handler_with_contract()
    handler._tool_display_name = lambda _tool_id: "PDF 文本转存 Word"
    task = FakeTask(logs=[
        {
            "level": "info",
            "message": "pdf page converted 10/100",
            "time": "2026-06-03T02:25:36+00:00",
            "data": {
                "kind": "pdf_to_docx",
                "phase": "progress",
                "pages_done": 10,
                "pages_total": 100,
                "source_pages": 100,
                "text_block_count": 88,
                "image_count": 4,
                "skipped_image_count": 1,
            },
        }
    ])

    progress = handler._tool_progress_snapshot("document.extract_pdf_to_docx", task)
    message = handler._tool_progress_message("document.extract_pdf_to_docx", task, 174, 90, progress)

    assert progress["kind"] == "pdf_to_docx"
    assert progress["done"] == 10
    assert progress["total"] == 100
    assert progress["percent"] == 10.0
    assert "10/100" in message
    assert "文字块 88" in message
    assert "图片 4" in message
    assert "跳过图片 1" in message
    assert "最近 90s 没有新页面进度" in message
