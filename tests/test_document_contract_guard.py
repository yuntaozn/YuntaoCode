from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api import conversations as conversations_api
from runtime.api.conversations import ConversationMessagesStreamHandler
from runtime.agent_strategy.document_contract_guard import document_contract_tool_guard_message


def _handler_with_contract() -> ConversationMessagesStreamHandler:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._active_task_contract = {
        "intent": "document_export",
        "expected_document_coverage": True,
    }
    return handler


def test_task_contract_prompt_is_model_declaration_not_fixed_target() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler.get_lang = lambda: "zh-CN"

    prompt = handler._task_contract_prompt({
        "workspace_path": r"D:\ifctool",
        "access_scope": "project_only",
        "planning_policy": "auto",
        "confirmation_policy": "auto",
        "intent": "write_required",
        "goal": "创建模型查看页面",
        "deliverables": [{"kind": "file", "path_hint": "viewer.html"}],
        "routing_strategy": "model_first_task_contract",
        "requires_write": True,
        "requires_verification": True,
        "success_conditions": ["target_deliverable_success"],
    })

    assert "模型声明的任务理解" in prompt
    assert "创建模型查看页面" in prompt
    assert "仅作提示，不固定路径" in prompt
    assert "执行策略由你自行选择" in prompt
    assert "必须遵守以下硬条件" not in prompt


def test_task_contract_prompt_includes_execution_advisories_without_hard_constraint() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler.get_lang = lambda: "zh-CN"

    prompt = handler._task_contract_prompt({
        "workspace_path": r"D:\ifctool",
        "access_scope": "project_only",
        "planning_policy": "auto",
        "confirmation_policy": "auto",
        "intent": "read_only_analysis",
        "goal": "诊断页面访问问题",
        "deliverables": [{"kind": "answer", "description": "诊断结果"}],
        "routing_strategy": "model_first_task_contract",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": False,
        "success_conditions": ["final_answer_with_evidence"],
        "execution_advisories": [
            {
                "code": "evidence_may_require_repair",
                "message": "Read first; repair if evidence shows the local artifact is broken.",
                "suggested_first_action": "read",
            }
        ],
    })

    assert "Runtime execution advisories (not hard constraints)" in prompt
    assert "Read first; repair if evidence shows the local artifact is broken." in prompt
    assert "You may choose a different safe action" in prompt


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


def test_verification_runtime_guard_blocks_long_running_server_after_write() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler._active_task_contract = {"requires_verification": True}
    handler._active_tool_events = [
        {
            "tool": "filesystem.write_file",
            "status": "success",
            "input": {"path": r"D:\ifctool\viewer.html"},
        }
    ]
    handler._active_current_stage = "verifier"
    handler._active_post_deliverable_mode = True

    message = handler._verification_runtime_tool_guard(
        "shell.run_command",
        {"command": "python -m http.server 8080", "timeout": 5},
    )

    assert message
    assert "长驻服务" in message
    assert "不能作为本轮目标产物完成后的自动验证" in message


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

    assert handler._task_contract_failures(contract, events, "document") == []


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

    assert "document_output_too_short" in handler._task_contract_failures(contract, events, "document")


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

    assert handler._task_contract_failures(contract, events, "coding") == []


def test_verifier_retry_prompt_uses_observed_modality_status() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    contract = {
        "requires_write": True,
        "requires_verification": True,
        "workspace_path": r"D:\workspace\site",
        "deliverables": [
            {"kind": "code", "path_hint": r"D:\workspace\site\index.html"}
        ],
        "required_verification_modalities": ["visual", "behavioral", "content"],
    }
    events = [
        {
            "tool": "code.edit_file",
            "status": "success",
            "input": {"path": r"D:\workspace\site\index.html"},
            "output": {"path": r"D:\workspace\site\index.html"},
        },
        {
            "tool": "preview.capture_local_html",
            "status": "success",
            "input": {"path": r"D:\workspace\site\index.html"},
            "output": {
                "screenshot_path": r"C:\Users\demo\AppData\Local\YuntaoCode\task-artifacts\run\preview\index.png",
                "title": "demo",
                "artifacts": ["screenshot", "visual_evidence"],
                "page_errors": [],
                "console_errors": [],
            },
        },
    ]

    prompt = handler._verifier_retry_prompt(
        "coding",
        r"D:\workspace\site",
        task_contract=contract,
        tool_events=events,
        capability_preflight={
            "visual_verification_tool_ids": [
                "preview.capture_local_html",
                "preview.interact_page",
            ],
        },
    )

    assert "observed_modalities=visual" in prompt
    assert "missing_modalities=behavioral, content" in prompt
    assert "preview.interact_page" in prompt


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


def test_short_follow_up_uses_model_contract_when_conversation_has_task_context() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    conversation = SimpleNamespace(messages=[
        SimpleNamespace(role="user", content="重写一个 3D 模型查看器", metadata={}),
        SimpleNamespace(
            role="assistant",
            content="已创建 viewer.html",
            metadata={"task_contract": {"intent": "write_required", "goal": "创建模型查看器"}},
        ),
        SimpleNamespace(role="user", content="现在想加能选构件的能力", metadata={}),
    ])

    assert handler._should_use_model_task_contract(
        "现在想加能选构件的能力",
        "answer_only",
        False,
        conversation,
    )


def test_short_action_request_uses_model_contract_without_task_context() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    conversation = SimpleNamespace(messages=[
        SimpleNamespace(role="user", content="在 Blender 中建个二层小楼", metadata={}),
    ])

    assert handler._should_use_model_task_contract(
        "在 Blender 中建个二层小楼",
        "answer_only",
        False,
        conversation,
    )


def test_short_greeting_without_task_context_skips_model_contract() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    conversation = SimpleNamespace(messages=[
        SimpleNamespace(role="user", content="你好", metadata={}),
    ])

    assert not handler._should_use_model_task_contract(
        "你好",
        "answer_only",
        False,
        conversation,
    )


def test_previous_task_contract_context_finds_external_state_contract() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    previous_contract = {
        "intent": "write_required",
        "goal": "在 Blender 中创建一个二层小楼的 3D 模型",
        "requires_write": False,
        "requires_state_change": True,
        "deliverables": [{"kind": "external_state"}],
    }
    conversation = SimpleNamespace(messages=[
        SimpleNamespace(role="user", content="在blender中建个二层小楼", metadata={}),
        SimpleNamespace(
            role="assistant",
            content="确认: 立即执行以上计划？[Y/n]",
            metadata={"task_contract": previous_contract},
        ),
        SimpleNamespace(role="user", content="立即执行", metadata={}),
    ])

    assert (
        handler._previous_task_contract_context(conversation, "立即执行")
        == previous_contract
    )


def test_previous_task_contract_context_skips_unanchored_retry_contract() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    external_contract = {
        "intent": "write_required",
        "goal": "Create the model in Blender",
        "requires_write": False,
        "requires_state_change": True,
        "deliverables": [{"kind": "external_state"}],
    }
    fallback_script_contract = {
        "intent": "write_required",
        "goal": "Write a Blender script",
        "requires_write": True,
        "requires_state_change": True,
        "deliverables": [{"kind": "code", "path_hint": "house.py"}],
    }
    conversation = SimpleNamespace(messages=[
        SimpleNamespace(role="user", content="Create a house in Blender", metadata={}),
        SimpleNamespace(role="assistant", content="done", metadata={"task_contract": external_contract}),
        SimpleNamespace(role="user", content="not good enough, try again", metadata={}),
        SimpleNamespace(role="assistant", content="wrote a script", metadata={"task_contract": fallback_script_contract}),
        SimpleNamespace(role="user", content="try again", metadata={}),
    ])

    assert (
        handler._previous_task_contract_context(conversation, "try again")
        == external_contract
    )


def test_previous_task_contract_context_keeps_model_declared_replacement() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    original_contract = {
        "intent": "write_required",
        "goal": "Create the model in Blender",
        "requires_write": False,
        "requires_state_change": True,
        "deliverables": [{"kind": "external_state"}],
    }
    replacement_contract = {
        "intent": "write_required",
        "goal": "Write a reusable script instead",
        "requires_write": True,
        "requires_state_change": True,
        "deliverables": [{"kind": "code", "path_hint": "house.py"}],
        "scope_relation": "replace",
        "scope_relation_source": "model",
    }
    conversation = SimpleNamespace(messages=[
        SimpleNamespace(role="user", content="Create a house in Blender", metadata={}),
        SimpleNamespace(role="assistant", content="done", metadata={"task_contract": original_contract}),
        SimpleNamespace(role="user", content="not good enough, write a script instead", metadata={}),
        SimpleNamespace(role="assistant", content="script ready", metadata={"task_contract": replacement_contract}),
        SimpleNamespace(role="user", content="try again", metadata={}),
    ])

    assert (
        handler._previous_task_contract_context(conversation, "try again")
        == replacement_contract
    )


@pytest.mark.asyncio
async def test_model_task_contract_receives_current_request_not_raw_history(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    async def fake_generate_chat_completion(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        captured["messages"] = kwargs["messages"]
        return (
            '{"intent":"write_required","requires_write":true,"goal":"添加构件选择功能"}',
            {},
        )

    monkeypatch.setattr(conversations_api, "generate_chat_completion", fake_generate_chat_completion)
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler.runtime = SimpleNamespace(
        settings=SimpleNamespace(get_access_scope=lambda: "project_only"),
    )

    contract = await handler._decide_task_contract(
        model="fake-model",
        messages=[
            {"role": "system", "content": "large tool catalog"},
            {"role": "user", "content": "重写一个 3D 模型查看器"},
            {"role": "assistant", "content": "已创建 viewer.html"},
            {"role": "user", "content": "现在想加能选构件的能力"},
        ],
        workspace_path=r"D:\ifctool",
        user_content="现在想加能选构件的能力",
        fallback_contract=handler._build_task_contract(
            task_intent="answer_only",
            mode="terminal",
            planning_policy="auto",
            confirmation_policy="auto",
            workspace_path=r"D:\ifctool",
        ),
        user_no_write_hint=False,
        expected_document_coverage=False,
        expected_min_output_chars=0,
    )

    assert contract["intent"] == "write_required"
    assert [item["role"] for item in captured["messages"]] == ["system", "user"]
    assert captured["messages"][-1]["content"] == "现在想加能选构件的能力"
    contents = "\n".join(item["content"] for item in captured["messages"])
    assert "重写一个 3D 模型查看器" not in contents
    assert "已创建 viewer.html" not in contents
    assert all(item["content"] != "large tool catalog" for item in captured["messages"])


@pytest.mark.asyncio
async def test_model_task_contract_revision_keeps_previous_semantic_target(
    monkeypatch: Any,
) -> None:
    async def fake_generate_chat_completion(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        return (
            '{"intent":"write_required","requires_write":true,'
            '"goal":"Improve the generated script",'
            '"deliverables":[{"kind":"code","path_hint":"house_v2.py"}]}',
            {},
        )

    monkeypatch.setattr(conversations_api, "generate_chat_completion", fake_generate_chat_completion)
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler.runtime = SimpleNamespace(
        settings=SimpleNamespace(get_access_scope=lambda: "project_only"),
    )
    previous = {
        "intent": "write_required",
        "goal": "Create the house in Blender",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Blender scene"}],
    }

    contract = await handler._decide_task_contract(
        model="fake-model",
        messages=[
            {"role": "user", "content": "Create the house in Blender"},
            {"role": "assistant", "content": "I wrote a script"},
            {"role": "user", "content": "not good enough, try again"},
        ],
        workspace_path=r"D:\blender",
        user_content="not good enough, try again",
        fallback_contract=handler._build_task_contract(
            task_intent="answer_only",
            mode="terminal",
            planning_policy="auto",
            confirmation_policy="auto",
            workspace_path=r"D:\blender",
        ),
        user_no_write_hint=False,
        expected_document_coverage=False,
        expected_min_output_chars=0,
        previous_contract=previous,
    )

    assert contract["scope_relation"] == "revise"
    assert contract["goal"] == previous["goal"]
    assert contract["requires_write"] is False
    assert contract["deliverables"][0]["kind"] == "external_state"


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


def test_document_contract_guard_pure_helper_requires_document_coverage() -> None:
    message = document_contract_tool_guard_message(
        "filesystem.write_file",
        {
            "path": r"D:\code\demo\translate_to_chinese.py",
            "content": "from deep_translator import GoogleTranslator\n",
        },
        {
            "intent": "document_export",
            "expected_document_coverage": True,
        },
    )
    skipped = document_contract_tool_guard_message(
        "filesystem.write_file",
        {
            "path": r"D:\code\demo\translate_to_chinese.py",
            "content": "from deep_translator import GoogleTranslator\n",
        },
        {
            "intent": "document_export",
            "expected_document_coverage": False,
        },
    )

    assert "document.translate_docx" in message
    assert skipped == ""


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


def test_tool_task_poll_interval_is_fast_for_short_local_tools() -> None:
    assert conversations_api._tool_task_poll_interval(0) < 1
    assert conversations_api._tool_task_poll_interval(2.9) < 1
    assert conversations_api._tool_task_poll_interval(3.0) == 1.0
