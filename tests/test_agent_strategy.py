"""Behaviour-driven tests for the agent_strategy modules.

Covers context evidence hints, tool classification, tool-call processing, progress
observation, planning policy, profiles, and prompt construction.
"""

from __future__ import annotations

import json

import pytest

# ── classifiers ───────────────────────────────────────────────────────────
from runtime.agent_strategy.classifiers import (
    # Context classifiers
    looks_like_diagnostic_feedback,
    # Tool classification
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
    # Tool-call processing
    complete_tool_calls,
    extract_native_tool_calls,
    merge_tool_call_chunks,
    messages_for_model_round,
    parse_tool_arguments_strict,
    strip_native_tool_call_blocks,
    tool_call_arguments_size,
    tool_signature,
    # Progress observation
    consecutive_repeated_failure_count,
    failure_route_attempt_count_since_progress,
    has_successful_verification,
    has_successful_write,
    is_recoverable_write_failure,
    progress_key,
    repeated_failure_action,
    round_has_only_non_progress,
    finish_reason_indicates_truncation,
    plan_has_pending_write_step,
)

# ── prompts ───────────────────────────────────────────────────────────────
from runtime.agent_strategy.prompts import (
    completion_reentry_prompt,
    completion_review_prompt,
    execute_plan_prompt,
    final_answer_prompt,
    format_execution_plan_for_context,
    max_rounds_message,
    progress_observer_prompt,
    oversized_tool_arguments_prompt,
    repeated_failure_strategy_prompt,
    result_synthesis_prompt,
    verifier_retry_prompt,
    write_repair_prompt,
)

# ── profiles / policy ─────────────────────────────────────────────────────
from runtime.agent_strategy.policy import (
    deterministic_plan_gate,
    heuristic_plan_execution,
    resolve_profile,
)
from runtime.agent_strategy.profiles import (
    get_profile,
    profile_for_task_intent,
)

# ═══════════════════════════════════════════════════════════════════════════
# 5a: Context evidence classifiers
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
# 5a.5: Profiles and planning policy
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
    def test_answer_only_auto_uses_model_plan_judge(self):
        decision = deterministic_plan_gate("你好", "answer_only", "terminal", "auto")
        assert decision.enabled is None
        assert decision.needs_model_judge

    def test_always_plan_respects_user_setting(self):
        decision = deterministic_plan_gate("你好", "answer_only", "terminal", "always")
        assert decision.enabled is True
        assert decision.source == "user"

    def test_off_plan_respects_user_setting(self):
        decision = deterministic_plan_gate("分析当前项目", "read_only_analysis", "terminal", "off")
        assert decision.enabled is False
        assert decision.source == "user"

    def test_project_analysis_does_not_trigger_keyword_plan_rule(self):
        decision = deterministic_plan_gate("分析当前项目架构并输出风险清单", "read_only_analysis", "terminal", "auto")
        assert decision.enabled is None
        assert decision.source == "model"

    def test_document_export_does_not_trigger_scenario_plan_rule(self):
        decision = deterministic_plan_gate("重新将PDF导一个图片加文字的word", "document_export", "terminal", "auto")
        assert decision.enabled is None
        assert decision.source == "model"

    def test_simple_read_only_still_uses_model_plan_judge(self):
        decision = deterministic_plan_gate("解释一下这个函数的作用", "read_only_analysis", "terminal", "auto")
        assert decision.enabled is None

    def test_ambiguous_analysis_can_use_model_judge(self):
        decision = deterministic_plan_gate("看一下这个项目", "read_only_analysis", "terminal", "auto")
        assert decision.enabled is None
        assert decision.needs_model_judge

    def test_resolve_profile_uses_policy_entrypoint(self):
        assert resolve_profile("document_export", "terminal").id == "document"

    def test_neutral_plan_fallback_does_not_route_by_keywords(self):
        assert not heuristic_plan_execution("你好", "terminal")
        assert not heuristic_plan_execution("重构整个项目并生成报告", "paper")


# ═══════════════════════════════════════════════════════════════════════════
# 5b: Tool classification
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
# 5c: Tool-call processing
# ═══════════════════════════════════════════════════════════════════════════

class TestMergeToolCallChunks:
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
        # Tool role should be converted to assistant
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
# Progress observation
# ═══════════════════════════════════════════════════════════════════════════

class TestProgressKey:
    def test_same_events_same_key(self):
        events = [{"tool": "filesystem.read_file", "status": "success", "input": {"path": "a.py"}}]
        assert progress_key(events, None) == progress_key(events, None)

    def test_different_events_different_key(self):
        e1 = [{"tool": "filesystem.read_file", "status": "success", "input": {"path": "a.py"}}]
        e2 = [{"tool": "filesystem.read_file", "status": "success", "input": {"path": "b.py"}}]
        assert progress_key(e1, None) != progress_key(e2, None)

    def test_failure_ignored(self):
        events = [{"tool": "filesystem.read_file", "status": "failure", "input": {"path": "a.py"}}]
        assert progress_key(events, None) == "[]"


class TestRoundHasOnlyNonProgress:
    def test_all_failures(self):
        assert round_has_only_non_progress([{"status": "failure"}, {"status": "skipped"}])

    def test_with_success(self):
        assert not round_has_only_non_progress([{"status": "failure"}, {"status": "success"}])

    def test_empty(self):
        assert not round_has_only_non_progress([])


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


class TestPlanHasPendingWriteStep:
    def test_pending_write(self):
        plan = {"steps": [{"title": "修改代码", "description": "", "tool_hint": "code.edit_file", "status": "pending"}]}
        assert plan_has_pending_write_step(plan)

    def test_completed_write(self):
        plan = {"steps": [{"title": "修改代码", "description": "", "tool_hint": "code.edit_file", "status": "completed"}]}
        assert not plan_has_pending_write_step(plan)

    def test_no_write_step(self):
        plan = {"steps": [{"title": "读取文件", "description": "", "tool_hint": "filesystem.read_file", "status": "pending"}]}
        assert not plan_has_pending_write_step(plan)

    def test_analysis_expansion_space_is_not_write(self):
        plan = {
            "steps": [
                {
                    "title": "\u5206\u6790\u6269\u5199\u7a7a\u95f4\u4e0e\u5efa\u8bae",
                    "description": "\u57fa\u4e8e\u8bba\u6587\u7ed3\u6784\u5206\u6790\u5404\u7ae0\u8282\u7684\u6269\u5199\u6f5c\u529b\uff0c\u7ed9\u51fa\u5177\u4f53\u5efa\u8bae",
                    "tool_hint": "\uff08\u5206\u6790\u5de5\u5177\uff0c\u65e0\u9700\u8c03\u7528\uff09",
                    "status": "pending",
                }
            ]
        }
        assert not plan_has_pending_write_step(plan)

    def test_document_read_plan_is_not_write(self):
        plan = {
            "steps": [
                {
                    "title": "\u8bfb\u53d6\u8bba\u6587\u5185\u5bb9\u5e76\u7edf\u8ba1\u5b57\u6570",
                    "description": "\u8bfb\u53d6\u8bba\u6587\u6587\u4ef6\u5185\u5bb9\uff0c\u7edf\u8ba1\u603b\u5b57\u6570\u3001\u7ae0\u8282\u5206\u5e03\u7b49\u4fe1\u606f",
                    "tool_hint": "document.extract_docx_outline, filesystem.read_text_preview",
                    "status": "pending",
                }
            ]
        }
        assert not plan_has_pending_write_step(plan)

    def test_not_a_dict(self):
        assert not plan_has_pending_write_step(None)


# ═══════════════════════════════════════════════════════════════════════════
# Prompt construction (spot checks)
# ═══════════════════════════════════════════════════════════════════════════

class TestPrompts:
    def test_progress_observer_prompt(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        prompt = progress_observer_prompt("/tmp", events, True, "stagnation")
        assert "stagnation" in prompt
        assert "observed_write_evidence=missing" in prompt
        assert "not choosing a strategy" in prompt

    def test_progress_observer_prompt_can_report_target_deliverable_facts(self):
        events = [{"tool": "document.extract_docx_outline", "status": "success"}]
        prompt = progress_observer_prompt(
            "/tmp",
            events,
            False,
            "missing_target_evidence",
            target_deliverable_observed=False,
        )
        assert "observed_target_deliverable=missing" in prompt
        assert "observed_write_evidence" not in prompt

    def test_progress_observer_prompt_exposes_verification_gap_facts(self):
        events = [{"tool": "preview.capture_local_html", "status": "success"}]
        prompt = progress_observer_prompt(
            "/tmp",
            events,
            True,
            "target_verification_still_missing",
            required_modalities=["visual", "content", "behavioral"],
            observed_modalities=["visual"],
            missing_modalities=["content", "behavioral"],
            visual_verification_tool_ids=["preview.interact_page"],
            runtime_diagnostics=[{
                "code": "verification_script_resource_facts",
                "severity": "info",
                "message": "Script resources observed",
            }],
        )

        assert "missing_modalities=content, behavioral" in prompt
        assert "preview.interact_page" in prompt
        assert "runtime_diagnostic=verification_script_resource_facts" in prompt
        assert "choose whether to verify, revise, try a different route" in prompt

    def test_repeated_failure_strategy_prompt_requires_different_route(self):
        events = [
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {},
                "error": "missing required: path, content",
            },
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {},
                "error": "missing required: path, content",
            },
        ]

        prompt = repeated_failure_strategy_prompt("/tmp", events)

        assert "Repeated failure recovery advisory" in prompt
        assert "runtime is not choosing the next strategy" in prompt
        assert "filesystem.write_file" in prompt
        assert "missing required" in prompt

    def test_write_repair_prompt(self):
        prompt = write_repair_prompt(
            "code.edit_file",
            {"path": "main.py"},
            {"error": "old_text not found"},
            "/tmp",
        )
        assert "old_text" in prompt

    def test_oversized_tool_arguments_prompt_keeps_strategy_model_directed(self):
        prompt = oversized_tool_arguments_prompt("/tmp/project", 25000, 24000)

        assert "not a permission denial" in prompt
        assert "Choose the next execution strategy yourself" in prompt
        assert "Do not repeat one oversized tool call" in prompt

    def test_format_execution_plan(self):
        plan = {
            "title": "Test Plan",
            "steps": [
                {"title": "Step 1", "description": "Do something", "tool_hint": "code.edit_file"},
            ],
        }
        result = format_execution_plan_for_context(plan)
        assert "Test Plan" in result
        assert "code.edit_file" in result

    def test_execute_plan_prompt_does_not_create_user_confirmation_gate(self):
        prompt = execute_plan_prompt({"title": "Test Plan", "steps": []}, "terminal")

        assert "权限和高风险确认由运行时呈现" in prompt
        assert "可以直接调用" in prompt
        assert "可以明确向用户提问" in prompt

    def test_max_rounds_message(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        msg = max_rounds_message(10, events)
        assert "10" in msg
        assert "执行预算" in msg
        assert "系统已停止" not in msg
        assert "后续可" in msg

    def test_verifier_retry_prompt_coding(self):
        prompt = verifier_retry_prompt("coding", "/tmp")
        assert "model-declared verification modalities" in prompt
        assert "model decides" in prompt

    def test_verifier_retry_prompt_paper(self):
        prompt = verifier_retry_prompt("paper", "/tmp")
        assert "not a hard tool constraint" in prompt
        assert "model decides" in prompt

    def test_verifier_retry_prompt_exposes_missing_modalities(self):
        prompt = verifier_retry_prompt(
            "coding",
            "/tmp",
            required_modalities=["visual", "content", "behavioral"],
            observed_modalities=["visual"],
            missing_modalities=["content", "behavioral"],
            visual_verification_tool_ids=[
                "preview.capture_local_html",
                "preview.interact_page",
            ],
            runtime_diagnostics=[
                {
                    "code": "browser_page_error",
                    "severity": "error",
                    "message": "Unexpected end of input",
                },
                {
                    "code": "script_parse_error_resource_candidates",
                    "severity": "info",
                    "message": "Script candidates",
                    "resources": [
                        {
                            "url": "https://cdn.example/app.js",
                            "status": 200,
                            "content_type": "application/javascript",
                        }
                    ],
                },
            ],
        )

        assert "required_modalities=visual, content, behavioral" in prompt
        assert "observed_modalities=visual" in prompt
        assert "missing_modalities=content, behavioral" in prompt
        assert "preview.interact_page" in prompt
        assert "runtime_diagnostic=browser_page_error" in prompt
        assert "Unexpected end of input" in prompt
        assert "https://cdn.example/app.js" in prompt
        assert "bounded page actions and assertions" in prompt

    def test_completion_review_prompt_exposes_facts_without_forcing_strategy(self):
        prompt = completion_review_prompt(
            "/tmp",
            {"goal": "create an interactive viewer"},
            {
                "status": "partial",
                "target_written_paths": ["viewer/index.html"],
                "verification_evidence": [
                    {"tool": "filesystem.read_file", "modalities": ["content"]},
                ],
                "failures": [{"tool": "filesystem.create_text_draft", "error": "truncated"}],
                "risks": ["test_not_observed", "recovered_tool_failure"],
                "counts": {
                    "deliverable_successes": 1,
                    "verification_successes": 1,
                    "failures": 1,
                },
            },
            task_route_evidence={
                "schema_version": "task_route_evidence.v1",
                "kind": "task_route_evidence",
                "boundary": "evidence_only",
                "strategy_owner": "model",
                "safety_owner": "runtime",
                "proposal_count": 1,
                "valid_proposal_count": 1,
                "target_capability_ids": ["code.text_write"],
                "flags": {"has_model_route": True, "all_routes_valid": True},
                "model_facts": ["route_proposals=code.text_write/filesystem.write_file"],
            },
        )

        assert "Completion self-review from runtime facts" in prompt
        assert "Runtime fact package" in prompt
        assert "viewer/index.html" in prompt
        assert "test_not_observed" in prompt
        assert "task route evidence" in prompt
        assert "route_proposals=code.text_write/filesystem.write_file" in prompt
        assert "Decide whether the task is actually complete" in prompt
        assert "Do not claim completion beyond the observed deliverables" in prompt
        assert "completion_self_assessment.v1" in prompt
        assert '"goal_closed":true' in prompt
        assert '"remaining_work":[]' in prompt
        assert "ordinary user-facing Markdown answer below it" in prompt

    def test_completion_reentry_prompt_is_evidence_only(self):
        prompt = completion_reentry_prompt(
            "/tmp",
            {"goal": "create an interactive viewer"},
            {
                "status": "partial",
                "target_written_paths": ["viewer/index.html"],
                "missing_verification_modalities": ["behavioral"],
                "risks": ["test_not_observed"],
            },
            {"action": "final_answer_candidate", "content_chars": 120},
        )

        assert "Completion candidate re-entry from runtime facts" in prompt
        assert "final answer" in prompt
        assert "missing verification modalities" in prompt
        assert "behavioral" in prompt
        assert "not a forced route" in prompt
        assert "Choose the next step yourself" in prompt

    def test_result_synthesis_prompt_uses_runtime_facts_instead_of_fixed_template(self):
        prompt = result_synthesis_prompt(
            "/tmp",
            {"goal": "create an interactive viewer"},
            {
                "status": "partial",
                "changed_paths": ["viewer/index.html"],
                "risks": ["test_not_observed"],
                "counts": {"tool_events": 2, "failures": 1},
            },
            previous_answer="Done.",
        )

        assert "Write the final user-facing answer for this run from runtime facts" in prompt
        assert "Completion evidence pack" in prompt
        assert "viewer/index.html" in prompt
        assert "test_not_observed" in prompt
        assert "Previous assistant draft" in prompt

    def test_repeated_failure_strategy_prompt_stays_strategy_neutral_after_truncation(self):
        prompt = repeated_failure_strategy_prompt(
            "/tmp/project",
            [
                {
                    "tool": "filesystem.write_file",
                    "status": "failure",
                    "error": "The model response stopped at its output limit.",
                    "output": {"reason": "truncated_tool_call"},
                }
            ],
        )

        assert "Repeated failure recovery advisory" in prompt
        assert "runtime is not choosing the next strategy" in prompt
        assert "truncated_tool_call" in prompt
        assert "draft route is available" not in prompt
        assert "filesystem.create_text_draft" not in prompt

    def test_write_repair_prompt_stays_strategy_neutral_after_truncation(self):
        prompt = write_repair_prompt(
            "filesystem.write_file",
            {"path": "viewer/index.html"},
            {
                "status": "failure",
                "error": "The runtime did not execute incomplete arguments.",
                "output": {"reason": "truncated_tool_call"},
            },
            "/tmp/project",
        )

        assert "Write failure recovery advisory" in prompt
        assert "runtime is not choosing the repair strategy" in prompt
        assert "truncated_tool_call" in prompt
        assert "draft route" not in prompt
        assert "filesystem.create_text_draft" not in prompt
