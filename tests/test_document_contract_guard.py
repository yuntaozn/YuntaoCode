from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any


from runtime.api import conversations as conversations_api
from runtime.api.conversations import ConversationMessagesStreamHandler


def _handler_with_contract() -> ConversationMessagesStreamHandler:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._active_task_contract = {
        "intent": "document_export",
        "expected_document_coverage": True,
    }
    return handler


def test_runtime_confirmation_message_describes_file_creation(tmp_path: Path) -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._active_task_contract = {"goal": "重写 HTML 示例页"}
    handler._tool_display_name = lambda _tool_id: "写入文件"
    target = tmp_path / "index.html"

    message = handler._runtime_confirmation_message(
        "filesystem.write_file",
        {"path": str(target), "content": "<!doctype html>"},
    )

    assert "任务目标：重写 HTML 示例页" in message
    assert "操作：创建文件" in message
    assert "工具：写入文件（filesystem.write_file）" in message
    assert f"目标：{target}" in message
    assert "内容大小：15 字符" in message


def test_runtime_confirmation_message_describes_file_overwrite(tmp_path: Path) -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._tool_display_name = lambda _tool_id: "写入文件"
    target = tmp_path / "index.html"
    target.write_text("old", encoding="utf-8")

    message = handler._runtime_confirmation_message(
        "filesystem.write_file",
        {"path": str(target), "content": "new"},
    )

    assert "操作：覆盖/更新文件" in message
    assert f"目标：{target}" in message


def test_runtime_confirmation_message_describes_dependency_install() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._tool_display_name = lambda _tool_id: "执行终端命令"

    message = handler._runtime_confirmation_message(
        "shell.run_command",
        {
            "command": "python",
            "args": ["-m", "playwright", "install", "chromium"],
            "cwd": r"D:\code\demo",
        },
    )

    assert "操作：安装或更新运行依赖" in message
    assert "命令：python" in message
    assert "参数：-m playwright install chromium" in message
    assert r"工作目录：D:\code\demo" in message
    assert "最长运行：600 秒" in message


def test_runtime_confirmation_message_describes_external_mcp_operation() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._tool_display_name = lambda _tool_id: "execute_blender_code"

    operation = handler._runtime_confirmation_operation(
        "mcp_blender.execute_blender_code",
        {"code": "print(1)"},
        "",
    )
    message = handler._runtime_confirmation_message(
        "mcp_blender.execute_blender_code",
        {"code": "print(1)"},
    )

    assert "MCP" in operation
    assert "MCP" in message
    assert "filesystem.write_file" not in message


def test_runtime_confirmation_message_describes_patch_targets() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._tool_display_name = lambda _tool_id: "应用代码补丁"

    message = handler._runtime_confirmation_message(
        "code.apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Update File: src/app.js\n"
                "@@\n"
                "-old\n"
                "+new\n"
                "*** Add File: src/new.js\n"
                "+content\n"
                "*** End Patch"
            ),
        },
    )

    assert "操作：应用代码补丁" in message
    assert "目标：src/app.js, src/new.js" in message


def test_shell_output_preview_includes_timeout_fields() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    preview = handler._tool_output_preview(
        "shell.run_command",
        {"exit_code": 1, "stdout": "", "stderr": "", "timed_out": True, "timeout": 5},
    )

    assert preview["type"] == "shell"
    assert preview["timed_out"] is True
    assert preview["timeout"] == 5


def test_transform_text_output_preview_reports_integrity() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    preview = handler._tool_output_preview(
        "filesystem.transform_text",
        {
            "path": r"D:\ifctool\viewer.html",
            "transform": "html_unescape",
            "changed": True,
            "before_size": 100,
            "after_size": 80,
            "integrity_before": {"checked": True, "valid": False},
            "integrity": {"checked": True, "valid": True},
        },
    )

    assert preview["type"] == "file_transform"
    assert preview["path"] == r"D:\ifctool\viewer.html"
    assert preview["transform"] == "html_unescape"
    assert preview["integrity"]["valid"] is True


def test_task_contract_accepts_structured_artifact_facts_as_verification() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    contract = {
        "requires_write": True,
        "requires_verification": True,
    }
    events = [
        {
            "tool": "document.export_draft_docx",
            "status": "success",
            "input": {"path": r"D:\workspace\report.docx"},
            "output": {
                "path": r"D:\workspace\report.docx",
                "file_size": 25000,
                "content_chars": 30000,
                "draft_stats": {"text_chars": 29000},
            },
        },
    ]

    assert _contract_result(contract, events, "document")["status"] == "success"


def test_task_contract_rejects_short_finalized_text_for_long_document() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    contract = {
        "requires_write": True,
        "requires_verification": True,
        "expected_min_output_chars": 12000,
        "deliverables": [
            {"kind": "document", "path_hint": r"D:\workspace\story.docx"}
        ],
    }
    events = [
        {
            "tool": "filesystem.finalize_text_file",
            "status": "success",
            "input": {"output_path": r"D:\workspace\story.txt"},
            "output": {
                "path": r"D:\workspace\story.txt",
                "draft_stats": {"text_chars": 5000},
                "validation": {"valid": True, "text_chars": 5000},
            },
        },
    ]

    assert "document_output_too_short" in _contract_result(contract, events, "document")["risks"]


def test_task_contract_uses_declared_deliverable_role_for_write_and_verification() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    contract = {
        "requires_write": True,
        "requires_verification": True,
        "workspace_path": r"D:\workspace\site",
        "deliverables": [
            {
                "kind": "code",
                "path_hint": r"D:\workspace\site\index.html",
                "description": "Homepage",
            }
        ],
    }
    events = [
        {
            "tool": "web.collect_site_assets",
            "status": "success",
            "input": {"output_dir": r"D:\workspace\site\site_assets"},
            "output": {"index_path": r"D:\workspace\site\site_assets\site-index.json"},
        },
        {
            "tool": "filesystem.finalize_text_file",
            "status": "success",
            "input": {"output_path": r"D:\workspace\site\index.html"},
            "output": {
                "path": r"D:\workspace\site\index.html",
                "draft_stats": {"text_chars": 12000},
                "validation": {"valid": True, "text_chars": 12000},
            },
        },
        {
            "tool": "filesystem.read_text_preview",
            "status": "success",
            "input": {"path": r"D:\workspace\site\index.html"},
            "output": {
                "path": r"D:\workspace\site\index.html",
                "truncated": False,
                "integrity": {"checked": True, "valid": True},
            },
        },
    ]

    assert _contract_result(contract, events, "coding")["status"] == "success"


def test_execution_notice_reports_invalid_verification_method() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    notice = handler._build_execution_notice(
        "terminal",
        "已修复 viewer.html",
        [
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": r"D:\ifctool\viewer.html"},
            },
            {
                "tool": "shell.run_command",
                "status": "failure",
                "input": {"command": "python -m http.server 8080", "timeout": 5},
                "output": {"exit_code": 1, "timed_out": True, "timeout": 5},
                "error": "command timed out after 5s",
            },
        ],
        requires_code_write=True,
    )

    assert notice["reason"] == "invalid_verification_method"
    assert "长驻服务" in notice["message"]


def test_execution_notice_reports_optional_write_without_verification() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    notice = handler._build_execution_notice(
        "terminal",
        "已修改 viewer.html",
        [
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": r"D:\ifctool\viewer.html"},
            },
        ],
        run_result={
            "risks": ["optional_write_not_verified"],
            "observed_written_paths": ["viewer.html"],
        },
    )

    assert notice["reason"] == "optional_write_not_verified"
    assert "未验证" in notice["message"]
    assert notice["written_paths"] == ["viewer.html"]


def test_execution_notice_reports_contract_gap_as_observed_fact() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    notice = handler._build_execution_notice(
        "terminal",
        "已修改 viewer.html",
        [
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": r"D:\ifctool\viewer.html"},
            },
        ],
        requires_code_write=True,
        contract_failed=True,
    )

    assert notice["reason"] == "tool_contract_gap"
    assert "未观察到成功的本地写入工具记录" in notice["message"]
    assert "系统已判定" not in notice["message"]


def test_task_contract_failures_accept_answer_evidence_for_read_only_analysis() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    failures = _contract_result(
        {
            "intent": "read_only_analysis",
            "workspace_path": "D:/workspace",
            "requires_write": False,
            "requires_state_change": False,
            "requires_verification": True,
            "deliverables": [{"kind": "answer"}],
        },
        [
            {
                "tool": "filesystem.scan_folder",
                "status": "success",
                "input": {"path": "D:/workspace"},
                "output": {"path": "D:/workspace"},
            },
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/README.md"},
                "output": {"path": "D:/workspace/README.md", "content": "# Demo"},
            },
        ],
        "terminal",
    )

    assert failures["status"] == "success"


def test_task_contract_failures_use_final_answer_length_for_answer_deliverable() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    failures = _contract_result(
        {
            "intent": "read_only_analysis",
            "workspace_path": "D:/workspace",
            "requires_write": False,
            "requires_state_change": False,
            "requires_verification": False,
            "expected_min_output_chars": 2000,
            "deliverables": [{"kind": "answer"}],
        },
        [],
        "terminal",
        answer_text="a" * 1751,
    )

    assert "answer_output_too_short" in failures["risks"]
    assert failures["status"] == "partial"


def test_ai_plugin_draft_guard_blocks_workspace_ai_plugins_write() -> None:
    handler = _handler_with_contract()
    handler.runtime = SimpleNamespace(settings=SimpleNamespace(data_dir=Path(r"C:\Users\wutao\AppData\Local\YuntaoCode")))

    message = handler._ai_plugin_draft_workspace_guard(
        "filesystem.write_file",
        {
            "path": r"D:\code\YuntaoCode\ai-plugins\video-generator\plugin.json",
            "content": "{}",
        },
        r"D:\code\YuntaoCode",
    )

    assert message
    assert "不能写入当前工作区的 ai-plugins/ 或 capability-packs/" in message
    assert r"C:\Users\wutao\AppData\Local\YuntaoCode\capability-packs\items\<pack-id>" in message


def test_ai_plugin_draft_guard_blocks_apply_patch_to_workspace_ai_plugins() -> None:
    handler = _handler_with_contract()
    handler.runtime = SimpleNamespace(settings=SimpleNamespace(data_dir=Path(r"C:\Users\wutao\AppData\Local\YuntaoCode")))

    message = handler._ai_plugin_draft_workspace_guard(
        "code.apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: ai-plugins/video-generator/plugin.json\n"
                "+{}\n"
                "*** End Patch"
            ),
        },
        r"D:\code\YuntaoCode",
    )

    assert message
    assert "不能写入当前工作区的 ai-plugins/ 或 capability-packs/" in message


def test_capability_pack_guard_blocks_workspace_capability_packs_write() -> None:
    handler = _handler_with_contract()
    handler.runtime = SimpleNamespace(settings=SimpleNamespace(data_dir=Path(r"C:\Users\wutao\AppData\Local\YuntaoCode")))

    message = handler._ai_plugin_draft_workspace_guard(
        "filesystem.write_file",
        {
            "path": r"D:\code\YuntaoCode\capability-packs\items\doc-method\SKILL.md",
            "content": "# Method",
        },
        r"D:\code\YuntaoCode",
    )

    assert message
    assert r"C:\Users\wutao\AppData\Local\YuntaoCode\capability-packs\items\<pack-id>" in message


def test_ai_plugin_draft_guard_allows_normal_workspace_write() -> None:
    handler = _handler_with_contract()
    handler.runtime = SimpleNamespace(settings=SimpleNamespace(data_dir=Path(r"C:\Users\wutao\AppData\Local\YuntaoCode")))

    message = handler._ai_plugin_draft_workspace_guard(
        "filesystem.write_file",
        {
            "path": r"D:\code\YuntaoCode\docs\plugin-system.md",
            "content": "ok",
        },
        r"D:\code\YuntaoCode",
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


def test_tool_task_poll_interval_is_fast_for_short_local_tools() -> None:
    assert conversations_api._tool_task_poll_interval(0) < 1
    assert conversations_api._tool_task_poll_interval(2.9) < 1
    assert conversations_api._tool_task_poll_interval(3.0) == 1.0


def _contract_result(contract, events, mode, *, answer_text=None):
    from runtime.run_result import build_run_result

    return build_run_result(
        workspace_path=str(contract.get("workspace_path") or ""), tool_events=events,
        mode=mode, change_summary=None, task_contract=contract, answer_text=answer_text,
    )
