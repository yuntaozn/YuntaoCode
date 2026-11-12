"""Agent 策略模块的行为驱动测试。

覆盖上下文证据提示、工具分类、工具调用处理、收敛证据、计划策略、
Profile 和提示构建。"""

from __future__ import annotations

import json

import pytest

# ── 分类器 ───────────────────────────────────────────────────────────────
from runtime.agent_strategy.classifiers import (
    # 上下文分类器
    looks_like_diagnostic_feedback,
    # 工具分类
    WRITE_TOOL_IDS,
    RECON_TOOL_IDS,
    canonical_tool_id,
    explorer_tool_ids,
    has_unresolved_tool_call_markup,
    is_recon_tool,
    is_invalid_verification_method_event,
    is_long_running_service_command,
    is_meaningful_verification_event,
    is_structural_verification_event,
    is_state_changing_tool,
    is_test_verification_event,
    is_verification_tool,
    is_write_tool,
    verification_tool_ids,
    # 工具调用处理
    complete_tool_calls,
    extract_native_tool_calls,
    merge_tool_call_chunks,
    messages_for_model_round,
    parse_tool_arguments_strict,
    strip_native_tool_call_blocks,
    tool_call_arguments_size,
    tool_signature,
    # 进度观察
    consecutive_repeated_failure_count,
    failure_route_attempt_count_since_progress,
    has_successful_verification,
    has_successful_write,
    is_recoverable_write_failure,
    repeated_failure_action,
    finish_reason_indicates_truncation,
)

# ── 提示构建 ─────────────────────────────────────────────────────────────
from runtime.agent_strategy.prompts import (
    max_rounds_message,
)

# ── Profile 与策略 ────────────────────────────────────────────────────────
from runtime.agent_strategy.policy import (
    resolve_profile,
)
from runtime.agent_strategy.profiles import (
    get_profile,
    profile_for_task_intent,
)

# ═══════════════════════════════════════════════════════════════════════════
# 5a：上下文证据分类器
# ═══════════════════════════════════════════════════════════════════════════

class TestLooksLikeDiagnosticFeedback:
    def test_browser_runtime_log(self):
        log = (
            "home.js:1 Uncaught TypeError: Cannot set properties of null "
            "(setting 'onclick')\n"
            "Failed to load resource: the server responded with a status of "
            "405 (Method Not Allowed)\n"
            "SyntaxError: Failed to execute 'json' on 'Response': "
            "Unexpected end of JSON input"
        )

        assert looks_like_diagnostic_feedback(log)

    def test_python_traceback(self):
        log = (
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 12, in <module>\n"
            "ModuleNotFoundError: No module named 'runtime.skills.video'"
        )

        assert looks_like_diagnostic_feedback(log)


# ═══════════════════════════════════════════════════════════════════════════
# 5a.5：Profile 与计划策略
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentProfiles:
    def test_write_required_routes_to_coding(self):
        assert profile_for_task_intent("write_required", "terminal", code_change_intent=True).id == "coding"

    def test_external_state_change_routes_to_execution(self):
        assert profile_for_task_intent(
            "write_required",
            "terminal",
            state_change_intent=True,
        ).id == "execution"

    def test_document_export_routes_to_document(self):
        assert profile_for_task_intent("document_export", "terminal").id == "document"

    def test_paper_workflow_routes_to_paper(self):
        assert profile_for_task_intent("paper_workflow", "terminal").id == "paper"

    def test_answer_only_routes_to_chat(self):
        assert profile_for_task_intent("answer_only", "terminal").id == "chat"

    def test_answer_only_overrides_legacy_mode(self):
        assert profile_for_task_intent("answer_only", "coding").id == "chat"

    def test_answer_deliverable_can_still_use_analysis_profile_for_evidence(self):
        assert profile_for_task_intent(
            "answer_only",
            "terminal",
            first_action="read",
        ).id == "analysis"

    def test_legacy_mode_does_not_route_neutral_contract(self):
        assert profile_for_task_intent("", "document").id == "analysis"

    def test_unknown_profile_falls_back_to_analysis(self):
        assert get_profile("missing").id == "analysis"

class TestPlanningPolicy:


    def test_resolve_profile_uses_policy_entrypoint(self):
        assert resolve_profile("document_export", "terminal").id == "document"

# ═══════════════════════════════════════════════════════════════════════════
# 5b：工具分类
# ═══════════════════════════════════════════════════════════════════════════

class TestIsWriteTool:
    def test_apply_patch(self):
        assert is_write_tool("code.apply_patch")

    def test_edit_file(self):
        assert is_write_tool("code.edit_file")

    def test_write_file(self):
        assert is_write_tool("filesystem.write_file")

    def test_copy_file(self):
        assert is_write_tool("filesystem.copy_file")

    def test_delete_file(self):
        assert is_write_tool("filesystem.delete_file")

    def test_transform_text(self):
        assert is_write_tool("filesystem.transform_text")

    def test_finalize_text_file(self):
        assert is_write_tool("filesystem.finalize_text_file")

    def test_read_file_not_write(self):
        assert not is_write_tool("filesystem.read_file")

    def test_document_export(self):
        assert is_write_tool("document.export_pdf")

    def test_pdf_to_docx(self):
        assert is_write_tool("document.extract_pdf_to_docx")

    def test_translate_docx(self):
        assert is_write_tool("document.translate_docx")

    def test_web_artifact_tools(self):
        assert is_write_tool("web.collect_site_assets")
        assert is_write_tool("web.capture_page")

    def test_filesystem_apply_changes(self):
        assert is_write_tool("filesystem.apply_changes")


class TestIsReconTool:
    def test_read_file(self):
        assert is_recon_tool("filesystem.read_file")

    def test_search(self):
        assert is_recon_tool("code.search_text")

    def test_pdf_alias(self):
        assert canonical_tool_id("document.pdf_extract_text") == "document.extract_pdf_text_preview"
        assert is_recon_tool("document.pdf_extract_text")

    def test_shell_not_recon(self):
        assert not is_recon_tool("shell.run_command")


class TestIsStateChangingTool:
    def test_write(self):
        assert is_state_changing_tool("code.edit_file")

    def test_shell(self):
        assert is_state_changing_tool("shell.run_command")

    def test_git_commit(self):
        assert is_state_changing_tool("git.commit")

    def test_read_not_changing(self):
        assert not is_state_changing_tool("filesystem.read_file")


class TestIsVerificationTool:
    def test_shell(self):
        assert is_verification_tool("shell.run_command", None)

    def test_git_status(self):
        assert is_verification_tool("git.status", None)

    def test_read_file_evidence_class_is_mode_neutral(self):
        assert is_verification_tool("filesystem.read_file", "paper")
        assert is_verification_tool("filesystem.read_file", "coding")

    def test_web_capture_page(self):
        assert is_verification_tool("web.capture_page", None)
        assert is_verification_tool("preview.capture_url", None)
        assert is_verification_tool("preview.capture_local_html", None)
        assert is_verification_tool("preview.capture_file", None)


class TestExplorerToolIds:
    def test_base_tools(self):
        ids = explorer_tool_ids(None)
        assert "filesystem.read_file" in ids
        assert "code.search_text" in ids

    def test_coding_adds_git(self):
        ids = explorer_tool_ids("coding")
        assert "git.status" in ids
        assert "git.log" in ids

    def test_document_uses_same_evidence_tool_pool(self):
        ids = explorer_tool_ids("document")
        assert "git.status" in ids


class TestVerificationToolIds:
    def test_base(self):
        ids = verification_tool_ids(None)
        assert "shell.run_command" in ids
        assert "web.capture_page" in ids
        assert "preview.capture_local_html" in ids
        assert "preview.capture_file" in ids

    def test_verification_tool_pool_is_mode_neutral(self):
        assert verification_tool_ids("paper") == verification_tool_ids("coding")
        assert "filesystem.read_file" in verification_tool_ids("paper")


# ═══════════════════════════════════════════════════════════════════════════
# 5c：工具调用处理
# ═══════════════════════════════════════════════════════════════════════════

class TestMergeToolCallChunks:
    def test_invalid_batch_is_atomic(self):
        calls = []
        with pytest.raises(ValueError, match="invalid_tool_call_index"):
            merge_tool_call_chunks(calls, [
                {"index": 0, "function": {"name": "read", "arguments": "{}"}},
                {"index": -1},
            ])
        assert calls == []

    def test_single_chunk(self):
        calls: list = []
        merge_tool_call_chunks(calls, [
            {"index": 0, "id": "call_1", "function": {"name": "filesystem__read_file", "arguments": '{"path": "main.py"}'}},
        ])
        assert len(calls) == 1
        assert calls[0]["id"] == "call_1"
        assert calls[0]["function"]["name"] == "filesystem__read_file"

    def test_streaming_chunks(self):
        calls: list = []
        merge_tool_call_chunks(calls, [
            {"index": 0, "id": "call_1", "function": {"name": "filesystem__read_file", "arguments": '{"pa'}},
            {"index": 0, "function": {"name": "", "arguments": 'th": "main.py"}'}},
        ])
        assert calls[0]["function"]["arguments"] == '{"path": "main.py"}'

    def test_multiple_calls(self):
        calls: list = []
        merge_tool_call_chunks(calls, [
            {"index": 0, "id": "call_0", "function": {"name": "tool_a", "arguments": "{}"}},
            {"index": 1, "id": "call_1", "function": {"name": "tool_b", "arguments": "{}"}},
        ])
        assert len(calls) == 2

    def test_tool_call_argument_size_counts_accumulated_arguments(self):
        calls: list = []
        merge_tool_call_chunks(calls, [
            {"index": 0, "function": {"name": "filesystem__write_file", "arguments": '{"path":"a",'}},
            {"index": 0, "function": {"arguments": '"content":"abc"}'}},
            {"index": 1, "function": {"name": "tool_b", "arguments": "{}"}},
        ])
        assert tool_call_arguments_size(calls) == len('{"path":"a","content":"abc"}{}')


class TestCompleteToolCalls:
    def test_normal(self):
        calls = [
            {"id": "call_1", "type": "function", "function": {"name": "filesystem__read_file", "arguments": '{"path": "a.py"}'}},
        ]
        result = complete_tool_calls(calls, 0)
        assert len(result) == 1
        assert result[0]["id"] == "call_1"

    def test_empty_name_skipped(self):
        calls = [{"id": "", "type": "function", "function": {"name": "", "arguments": ""}}]
        assert complete_tool_calls(calls, 0) == []

    def test_generated_id(self):
        calls = [{"id": "", "type": "function", "function": {"name": "tool_x", "arguments": "{}"}}]
        result = complete_tool_calls(calls, 3)
        assert result[0]["id"] == "call_3_0"


class TestNativeToolCalls:
    def test_extract_qwen_style_function_call_block(self):
        text = (
            "思考过程\n"
            '<|FunctionCallBegin|>[{"name":"filesystem.read_file",'
            '"parameters":{"file_path":"D:\\\\code\\\\YuntaoCode\\\\desktop-shell\\\\index.html"}}]'
            "<|FunctionCallEnd|>"
        )

        result = extract_native_tool_calls(text, 2)

        assert result == [
            {
                "id": "native_2_0",
                "type": "function",
                "function": {
                    "name": "filesystem.read_file",
                    "arguments": (
                        '{"file_path": "D:\\\\code\\\\YuntaoCode\\\\desktop-shell\\\\index.html", '
                        '"path": "D:\\\\code\\\\YuntaoCode\\\\desktop-shell\\\\index.html"}'
                    ),
                },
            }
        ]

    def test_strip_native_function_call_block(self):
        text = "before <|FunctionCallBegin|>[]<|FunctionCallEnd|> after"

        assert strip_native_tool_call_blocks(text) == "before  after"

    def test_extract_xml_style_function_call_block(self):
        text = (
            "让我先查看当前目录。"
            "<filesystem.scan_folder>"
            "<arg-key>path</arg-key>"
            "<arg-value>D:\\365接箍管料切断机\\365接箍管料切断机</arg-value>"
            "<arg-key>max_depth</arg-key>"
            "<arg-value>3</arg-value>"
            "</filesystem.scan_folder>"
        )

        result = extract_native_tool_calls(text, 4)

        assert result == [
            {
                "id": "native_4_0",
                "type": "function",
                "function": {
                    "name": "filesystem.scan_folder",
                    "arguments": (
                        '{"path": "D:\\\\365接箍管料切断机\\\\365接箍管料切断机", '
                        '"max_depth": "3"}'
                    ),
                },
            }
        ]

    def test_strip_xml_style_function_call_block(self):
        text = (
            "before "
            "<filesystem.scan_folder>"
            "<arg-key>path</arg-key><arg-value>.</arg-value>"
            "</filesystem.scan_folder>"
            " after"
        )

        assert strip_native_tool_call_blocks(text) == "before  after"

    def test_extract_mcreference_toolcall_block(self):
        text = (
            "我来查看目录。"
            '<mcreference><toolcall>{"name":"filesystem.list_directory",'
            '"query_language":"Chinese",'
            '"params":{"dir_path":"D:\\\\365接箍管料切断机\\\\365接箍管料切断机","max_depth":3}}'
            "</toolcall></mcreference>"
        )

        result = extract_native_tool_calls(text, 5)

        assert result == [
            {
                "id": "native_5_0",
                "type": "function",
                "function": {
                    "name": "filesystem.list_directory",
                    "arguments": (
                        '{"dir_path": "D:\\\\365接箍管料切断机\\\\365接箍管料切断机", '
                        '"max_depth": 3, '
                        '"path": "D:\\\\365接箍管料切断机\\\\365接箍管料切断机"}'
                    ),
                },
            }
        ]

    def test_strip_mcreference_toolcall_block(self):
        text = (
            "before "
            '<mcreference><toolcall>{"name":"filesystem.scan_folder","params":{"path":"."}}</toolcall></mcreference>'
            " after"
        )

        assert strip_native_tool_call_blocks(text) == "before  after"

    def test_strip_function_like_tagged_toolcall_block(self):
        text = (
            "before "
            '<toolcall>filesystem__write_file({"path":"demo.html","content":"x"})</toolcall>'
            " after"
        )

        assert strip_native_tool_call_blocks(text) == "before  after"


    def test_extract_bare_tagged_tool_name_block(self):
        text = "先看看项目文件。<toolcall>filesystem.list_project_files</toolcall>"

        result = extract_native_tool_calls(text, 6)

        assert result == [
            {
                "id": "native_6_0",
                "type": "function",
                "function": {
                    "name": "filesystem.list_project_files",
                    "arguments": "{}",
                },
            }
        ]

    def test_ignores_bare_tagged_write_tool_name_block(self):
        text = "我来写文件。<toolcall>filesystem.write_file</toolcall>"

        assert extract_native_tool_calls(text, 7) == []

    def test_bare_read_tool_without_arguments_requires_correction(self):
        text = "让我先读取当前文件。<toolcall>filesystem.read_file</toolcall>"

        assert extract_native_tool_calls(text, 8) == []
        assert has_unresolved_tool_call_markup(text)
        assert strip_native_tool_call_blocks(text) == "让我先读取当前文件。"

    def test_valid_tagged_tool_call_is_not_unresolved(self):
        text = '<toolcall>{"name":"filesystem.read_file","parameters":{"path":"viewer.html"}}</toolcall>'

        assert extract_native_tool_calls(text, 9)
        assert not has_unresolved_tool_call_markup(text)

    def test_xml_tool_call_without_arguments_requires_correction(self):
        text = "让我先读取文件。<filesystem.read_file></filesystem.read_file>"

        assert extract_native_tool_calls(text, 10) == []
        assert has_unresolved_tool_call_markup(text)
        assert strip_native_tool_call_blocks(text) == "让我先读取文件。"

    def test_unclosed_tagged_tool_call_is_removed_from_display_text(self):
        text = "让我先读取文件。<toolcall>filesystem.read_file"

        assert has_unresolved_tool_call_markup(text)
        assert strip_native_tool_call_blocks(text) == "让我先读取文件。"


class TestToolSignature:
    def test_deterministic(self):
        sig1 = tool_signature("filesystem.read_file", {"path": "a.py", "start_line": 1})
        sig2 = tool_signature("filesystem.read_file", {"path": "a.py", "start_line": 1})
        assert sig1 == sig2

    def test_search_normalizes(self):
        sig = tool_signature("code.search_text", {"path": "src", "query": "TODO"})
        parsed = json.loads(sig)
        assert parsed["tool"] == "code.search_text"
        assert "include_extensions" in parsed["input"]


class TestMessagesForModelRound:
    def test_with_tools_passthrough(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert messages_for_model_round(msgs, [{"function": {"name": "tool"}}]) is msgs

    def test_without_tools_sanitizes(self):
        msgs = [
            {"role": "user", "content": "fix it"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "edit", "arguments": "{}"}}]},
            {"role": "tool", "name": "edit", "content": "done"},
        ]
        result = messages_for_model_round(msgs, None)
        assert all(item["role"] in {"system", "user", "assistant"} for item in result)
        # 工具角色应转换为助手角色
        assert result[-1]["role"] == "assistant"


class TestStrictToolArguments:
    def test_rejects_truncated_json(self):
        arguments, error = parse_tool_arguments_strict(
            '{"path":"demo.html","content":"partial',
        )

        assert arguments == {}
        assert error == "malformed_tool_arguments"

    def test_accepts_complete_object(self):
        arguments, error = parse_tool_arguments_strict(
            '{"path":"demo.html","content":"complete"}',
        )

        assert arguments == {"path": "demo.html", "content": "complete"}
        assert error is None

    def test_rejects_non_object_json(self):
        arguments, error = parse_tool_arguments_strict('["demo.html"]')

        assert arguments == {}
        assert error == "non_object_tool_arguments"

    def test_detects_provider_length_finish_reasons(self):
        assert finish_reason_indicates_truncation("length") is True
        assert finish_reason_indicates_truncation("max_output_tokens") is True
        assert finish_reason_indicates_truncation("tool_calls") is False


# ═══════════════════════════════════════════════════════════════════════════
# 收敛证据
# ═══════════════════════════════════════════════════════════════════════════


class TestConsecutiveRepeatedFailureCount:
    def test_counts_identical_trailing_failures(self):
        event = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {},
            "error": "missing required: path, content",
            "output": {"reason": "invalid_tool_input"},
        }

        assert consecutive_repeated_failure_count([event, event, event]) == 3

    def test_success_resets_failure_count(self):
        failure = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {},
            "error": "missing required: path, content",
            "output": {"reason": "invalid_tool_input"},
        }
        success = {"tool": "filesystem.read_file", "status": "success", "input": {"path": "a.py"}}

        assert consecutive_repeated_failure_count([failure, failure, success]) == 0

    def test_different_failure_does_not_share_budget(self):
        events = [
            {"tool": "filesystem.write_file", "status": "failure", "error": "missing path"},
            {"tool": "filesystem.write_file", "status": "failure", "error": "missing content"},
        ]

        assert consecutive_repeated_failure_count(events) == 1

    def test_route_attempt_count_detects_non_consecutive_same_route_without_progress(self):
        write_failure = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "viewer/index.html", "content": "<html>..."},
            "error": "The model response stopped at its output limit.",
            "output": {"reason": "truncated_tool_call"},
        }
        other_failure = {
            "tool": "filesystem.append_text_chunk",
            "status": "failure",
            "input": {"draft_id": "", "content": ""},
            "error": "draft_id is required",
            "output": {"reason": "invalid_tool_input"},
        }

        assert failure_route_attempt_count_since_progress([write_failure, other_failure, write_failure]) == 2

    def test_route_attempt_count_resets_after_real_progress(self):
        failure = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "viewer/index.html", "content": "<html>..."},
            "error": "The model response stopped at its output limit.",
            "output": {"reason": "truncated_tool_call"},
        }
        progress = {
            "tool": "filesystem.create_text_draft",
            "status": "success",
            "input": {"path_hint": "viewer/index.html"},
        }

        assert failure_route_attempt_count_since_progress([failure, progress, failure]) == 1

    def test_route_attempt_count_treats_different_arguments_as_new_route(self):
        first = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "viewer/index.html"},
            "error": "missing content",
            "output": {"reason": "invalid_tool_input"},
        }
        second = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "viewer/style.css"},
            "error": "missing content",
            "output": {"reason": "invalid_tool_input"},
        }

        assert failure_route_attempt_count_since_progress([first, second]) == 1

    def test_repeated_failure_reports_route_repetition(self):
        event = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {},
            "error": "missing required: path, content",
            "output": {"reason": "invalid_tool_input"},
        }
        events = [event, event]

        assert repeated_failure_action(events) == "report_repetition"

    def test_repeated_failure_escalates_after_larger_no_progress_route_budget(self):
        event = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {},
            "error": "missing required: path, content",
            "output": {"reason": "invalid_tool_input"},
        }

        assert repeated_failure_action([event] * 8) == "report_repetition"
        assert repeated_failure_action([event] * 9) == "escalate_no_progress"

    def test_repeated_failure_action_counts_same_route_across_failed_detours(self):
        write_failure = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "viewer/index.html", "content": "<html>..."},
            "error": "The model response stopped at its output limit.",
            "output": {"reason": "truncated_tool_call"},
        }
        detour_failure = {
            "tool": "filesystem.append_text_chunk",
            "status": "failure",
            "input": {"draft_id": "", "content": ""},
            "error": "draft_id is required",
            "output": {"reason": "invalid_tool_input"},
        }

        assert repeated_failure_action(
            [write_failure, detour_failure, write_failure],
        ) == "report_repetition"

    def test_repeated_failure_action_resets_after_progress(self):
        failure = {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "viewer/index.html", "content": "<html>..."},
            "error": "The model response stopped at its output limit.",
            "output": {"reason": "truncated_tool_call"},
        }
        progress = {
            "tool": "filesystem.create_text_draft",
            "status": "success",
            "input": {"path_hint": "viewer/index.html"},
        }

        assert repeated_failure_action([failure, progress, failure]) == "none"

    def test_progress_resets_repetition_window(self):
        events = [
            {"tool": "filesystem.write_file", "status": "failure", "error": "missing path"},
            {"tool": "filesystem.read_file", "status": "success", "input": {"path": "viewer.html"}},
        ]

        assert repeated_failure_action(events) == "none"


class TestHasSuccessfulWrite:
    def test_yes(self):
        events = [{"tool": "code.edit_file", "status": "success"}]
        assert has_successful_write(events)

    def test_failure_not_counted(self):
        events = [{"tool": "code.edit_file", "status": "failure"}]
        assert not has_successful_write(events)

    def test_non_write_tool(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        assert not has_successful_write(events)


class TestHasSuccessfulVerification:
    def test_shell_success(self):
        events = [
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "pytest"},
                "output": {"exit_code": 0},
            }
        ]
        assert has_successful_verification(events, None)

    def test_no_verification_tool(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        assert not has_successful_verification(events, "coding")

    def test_directory_listing_is_not_meaningful_code_verification(self):
        events = [
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {
                    "command": "python",
                    "args": ["-c", "import os; print(os.listdir('.'))"],
                },
                "output": {"exit_code": 0},
            },
        ]

        assert not has_successful_verification(events, "terminal")

    def test_reading_written_file_counts_as_content_verification(self):
        events = [
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
            {"tool": "filesystem.read_file", "status": "success", "input": {"path": "demo.html"}},
        ]

        assert has_successful_verification(events, "terminal")

    def test_read_before_write_does_not_count_as_deliverable_verification(self):
        events = [
            {"tool": "filesystem.read_file", "status": "success", "input": {"path": "demo.html"}},
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
        ]

        assert not has_successful_verification(events, "terminal")

    def test_new_write_invalidates_earlier_verification(self):
        events = [
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
            {"tool": "filesystem.read_file", "status": "success", "input": {"path": "demo.html"}},
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
        ]

        assert not has_successful_verification(events, "terminal")

    def test_write_artifact_with_content_facts_counts_as_verification(self):
        events = [
            {
                "tool": "document.export_draft_docx",
                "status": "success",
                "input": {"path": "report.docx"},
                "output": {
                    "path": "report.docx",
                    "file_size": 12000,
                    "content_chars": 24000,
                    "draft_stats": {"text_chars": 23000},
                },
            },
        ]

        assert has_successful_verification(events, "document")

    def test_write_artifact_without_content_facts_is_not_self_verifying(self):
        events = [
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "report.txt"},
                "output": {"path": "report.txt", "file_size": 12000},
            },
        ]

        assert not has_successful_verification(events, "document")

    def test_reading_incomplete_html_does_not_count_as_verification(self):
        events = [
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "demo.html"},
                "output": {
                    "integrity": {
                        "checked": True,
                        "valid": False,
                        "issues": ["missing </html>"],
                    },
                },
            },
        ]

        assert not has_successful_verification(events, "terminal")

    def test_truncated_preview_does_not_count_as_code_verification(self):
        events = [
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
            {
                "tool": "filesystem.read_text_preview",
                "status": "success",
                "input": {"path": "demo.html", "max_bytes": 5000},
                "output": {"path": "demo.html", "truncated": True},
            },
        ]

        assert not has_successful_verification(events, "terminal")

    def test_preview_with_invalid_html_integrity_does_not_count_as_verification(self):
        events = [
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "demo.html"}},
            {
                "tool": "filesystem.read_text_preview",
                "status": "success",
                "input": {"path": "demo.html"},
                "output": {
                    "path": "demo.html",
                    "truncated": False,
                    "integrity": {
                        "checked": True,
                        "valid": False,
                        "issues": ["html appears escaped as text"],
                    },
                },
            },
        ]

        assert not has_successful_verification(events, "terminal")

    def test_pytest_counts_as_test_verification(self):
        event = {
            "tool": "shell.run_command",
            "status": "success",
            "input": {"command": "pytest"},
            "output": {"exit_code": 0},
        }

        assert is_meaningful_verification_event(event, "terminal")
        assert is_test_verification_event(event)
        assert not is_structural_verification_event(event)

    def test_py_compile_counts_as_structural_not_behavioral_verification(self):
        event = {
            "tool": "shell.run_command",
            "status": "success",
            "input": {"command": "python -m py_compile main.py"},
            "output": {"exit_code": 0},
        }

        assert is_meaningful_verification_event(event, "terminal")
        assert is_structural_verification_event(event)
        assert not is_test_verification_event(event)

    def test_timed_out_shell_command_is_not_verification(self):
        event = {
            "tool": "shell.run_command",
            "status": "success",
            "input": {"command": "pytest"},
            "output": {"exit_code": 0, "timed_out": True, "timeout": 10},
        }

        assert not is_meaningful_verification_event(event, "terminal")
        assert not is_test_verification_event(event)

    def test_long_running_service_command_is_not_verification(self):
        event = {
            "tool": "shell.run_command",
            "status": "success",
            "input": {"command": "python -m http.server 8080"},
            "output": {"exit_code": 0},
        }

        assert is_long_running_service_command(event["input"])
        assert not is_meaningful_verification_event(event, "terminal")
        assert not is_test_verification_event(event)

    def test_timed_out_long_running_service_is_invalid_verification_method(self):
        event = {
            "tool": "shell.run_command",
            "status": "failure",
            "input": {"command": r"cd D:\ifctool ; python -m http.server 8080"},
            "output": {"exit_code": 1, "timed_out": True, "timeout": 5},
        }

        assert is_invalid_verification_method_event(event)


class TestIsRecoverableWriteFailure:
    def test_old_text_not_found(self):
        event = {"status": "failure", "error": "old_text not found in file"}
        assert is_recoverable_write_failure("code.edit_file", event)

    def test_success_not_recoverable(self):
        event = {"status": "success"}
        assert not is_recoverable_write_failure("code.edit_file", event)

    def test_non_write_tool(self):
        event = {"status": "failure", "error": "old_text not found"}
        assert not is_recoverable_write_failure("filesystem.read_file", event)

    def test_missing_required_input_is_protocol_failure_not_write_repair(self):
        event = {"status": "failure", "error": "missing required: path, content"}
        assert not is_recoverable_write_failure("filesystem.write_file", event)

    def test_truncated_write_call_is_recoverable(self):
        event = {
            "status": "failure",
            "error": "The model response stopped at its output limit.",
            "output": {"reason": "truncated_tool_call"},
        }

        assert is_recoverable_write_failure("filesystem.write_file", event)
        assert is_recoverable_write_failure("filesystem.append_text_chunk", event)


# ═══════════════════════════════════════════════════════════════════════════
# 提示构建（抽样检查）
# ═══════════════════════════════════════════════════════════════════════════

class TestPrompts:


    def test_max_rounds_message(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        msg = max_rounds_message(10, events)
        assert "10" in msg
        assert "执行预算" in msg
        assert "系统已停止" not in msg
        assert "后续可" in msg
