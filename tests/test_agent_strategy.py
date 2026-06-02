"""Behaviour-driven tests for the agent_strategy modules.

Covers:
- 5a: intent classifiers
- 5b: tool classification
- 5c: tool-call processing
- 5d: stage management
- 5e: plan tracking
"""

from __future__ import annotations

import json

import pytest

# ── classifiers ───────────────────────────────────────────────────────────
from runtime.agent_strategy.classifiers import (
    # Intent classifiers
    classify_task_intent,
    code_change_intent,
    has_explicit_write_instruction,
    has_no_write_instruction,
    looks_like_code_change_request,
    looks_like_dangling_action,
    looks_like_document_export_request,
    looks_like_follow_up_execution,
    looks_like_paper_task,
    looks_like_read_only_request,
    looks_like_simple_code_change,
    user_requests_code_change,
    # Tool classification
    WRITE_TOOL_IDS,
    RECON_TOOL_IDS,
    canonical_tool_id,
    explorer_tool_ids,
    is_recon_tool,
    is_state_changing_tool,
    is_verification_tool,
    is_write_tool,
    verification_tool_ids,
    # Tool-call processing
    complete_tool_calls,
    extract_native_tool_calls,
    merge_tool_call_chunks,
    messages_for_model_round,
    strip_native_tool_call_blocks,
    tool_signature,
    try_fix_json,
    # Progress observation
    has_successful_verification,
    has_successful_write,
    is_recoverable_write_failure,
    progress_key,
    round_has_only_non_progress,
    # Stage management
    execution_stage_sequence,
    plan_has_pending_write_step,
    stage_round_limit,
)

# ── prompts ───────────────────────────────────────────────────────────────
from runtime.agent_strategy.prompts import (
    analysis_first_task_prompt,
    dangling_action_prompt,
    execute_plan_prompt,
    final_answer_prompt,
    format_execution_plan_for_context,
    max_rounds_message,
    post_write_prompt,
    progress_observer_prompt,
    read_only_task_prompt,
    recon_budget_prompt,
    runtime_intervention_prompt,
    stage_prompt,
    stage_status_message,
    tool_contract_correction_prompt,
    verifier_retry_prompt,
    write_only_stage_prompt,
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
    round_limit_for_profile,
    stage_sequence_for_profile,
)

# ── plan_tracker ──────────────────────────────────────────────────────────
from runtime.agent_strategy.plan_tracker import (
    complete_remaining_plan_steps,
    extract_plan_json,
    fallback_execution_plan,
    finish_plan_step,
    interrupt_execution_plan,
    mark_next_plan_step_running,
    normalize_execution_plan,
    normalize_tool_id,
    tool_matches_plan_step,
)


# ═══════════════════════════════════════════════════════════════════════════
# 5a: Intent classifiers
# ═══════════════════════════════════════════════════════════════════════════

class TestHasNoWriteInstruction:
    def test_chinese_no_write(self):
        assert has_no_write_instruction("只分析，不要改代码")

    def test_english_no_write(self):
        assert has_no_write_instruction("read only, no code changes")

    def test_write_requested(self):
        assert not has_no_write_instruction("帮我修改 main.py")

    def test_empty(self):
        assert not has_no_write_instruction("")


class TestHasExplicitWriteInstruction:
    def test_fix(self):
        assert has_explicit_write_instruction("帮我修复这个 bug")

    def test_implement(self):
        assert has_explicit_write_instruction("implement the login page")

    def test_readonly(self):
        assert not has_explicit_write_instruction("分析这段代码")


class TestLooksLikeReadOnlyRequest:
    def test_analyze(self):
        assert looks_like_read_only_request("分析一下这段代码")

    def test_review(self):
        assert looks_like_read_only_request("review the architecture")

    def test_write_request(self):
        assert not looks_like_read_only_request("帮我改 main.py")

    def test_no_write_overrides(self):
        assert looks_like_read_only_request("只分析，不要改代码")


class TestLooksLikeDocumentExportRequest:
    def test_export_pdf(self):
        assert looks_like_document_export_request("帮我导出为 PDF")

    def test_generate_docx(self):
        assert looks_like_document_export_request("生成 docx 文件")

    def test_pdf_text_to_word(self):
        assert looks_like_document_export_request("将pdf文件中文字提取出来转存word")

    def test_pdf_to_docx(self):
        assert looks_like_document_export_request("把 PDF 转成 docx")

    def test_not_export(self):
        assert not looks_like_document_export_request("修改 main.py 的内容")


class TestLooksLikePaperTask:
    def test_chinese_paper(self):
        assert looks_like_paper_task("帮我写一篇文献综述")

    def test_english_paper(self):
        assert looks_like_paper_task("write a literature review")

    def test_not_paper(self):
        assert not looks_like_paper_task("修改登录页面")


class TestLooksLikeFollowUpExecution:
    def test_continue(self):
        assert looks_like_follow_up_execution("继续")

    def test_retry(self):
        assert looks_like_follow_up_execution("重试")

    def test_too_long(self):
        # Messages > 40 chars are NOT follow-ups
        long_msg = "继续执行之前的任务，我需要你帮我完成整个项目的重构和优化工作，包括前端、后端、数据库迁移以及所有单元测试的编写和部署流程的配置更新"
        assert not looks_like_follow_up_execution(long_msg)


class TestLooksLikeCodeChangeRequest:
    def test_fix_bug(self):
        assert looks_like_code_change_request("帮我修复 main.py 的 bug")

    def test_analysis_only(self):
        assert not looks_like_code_change_request("分析代码逻辑")

    def test_analysis_with_fix(self):
        assert looks_like_code_change_request("分析代码并修复问题")

    def test_broad_with_context(self):
        assert looks_like_code_change_request("修改文件中的配置")


class TestLooksLikeSimpleCodeChange:
    def test_font_size(self):
        assert looks_like_simple_code_change("字太大了")

    def test_complex(self):
        assert not looks_like_simple_code_change("重构整个项目的架构")


class TestLooksLikeDanglingAction:
    def test_dangling_with_colon(self):
        assert looks_like_dangling_action("让我先验证一下：")

    def test_completed_statement(self):
        assert not looks_like_dangling_action("修改已完成。")

    def test_empty(self):
        assert not looks_like_dangling_action("")


class TestUserRequestsCodeChange:
    def test_coding_mode_write(self):
        assert user_requests_code_change("帮我修复 bug", "coding")

    def test_non_coding_mode(self):
        assert not user_requests_code_change("帮我修复 bug", "document")

    def test_inquiry_in_coding(self):
        assert not user_requests_code_change("建议怎么优化", "coding")

    def test_broad_write_with_code_context(self):
        assert user_requests_code_change("修改 main.py 文件", "coding")


class TestCodeChangeIntent:
    def test_direct_write(self):
        assert code_change_intent("帮我修复 bug", "coding")

    def test_no_write_instruction(self):
        assert not code_change_intent("只分析，不要改代码", "coding")

    def test_follow_up_with_previous_write(self):
        assert code_change_intent("继续", "coding", has_previous_write=True)

    def test_follow_up_without_previous(self):
        assert not code_change_intent("继续", "coding", has_previous_write=False)


class TestClassifyTaskIntent:
    def test_read_only_analysis(self):
        assert classify_task_intent("分析一下这段代码", None) == "read_only_analysis"

    def test_write_required(self):
        assert classify_task_intent("帮我修复这个 bug", "coding") == "write_required"

    def test_document_export(self):
        assert classify_task_intent("导出为 PDF", None) == "document_export"

    def test_pdf_to_word_is_document_export(self):
        assert classify_task_intent("将pdf文件中文字提取出来转存word", None) == "document_export"

    def test_paper_workflow(self):
        assert classify_task_intent("写文献综述", None) == "paper_workflow"

    def test_answer_only(self):
        assert classify_task_intent("你好", "coding") == "answer_only"

    def test_no_write_overrides_all(self):
        assert classify_task_intent("只分析不要改代码", "coding") == "read_only_analysis"


# ═══════════════════════════════════════════════════════════════════════════
# 5a.5: Profiles and planning policy
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentProfiles:
    def test_write_required_routes_to_coding(self):
        assert profile_for_task_intent("write_required", "terminal", code_change_intent=True).id == "coding"

    def test_document_export_routes_to_document(self):
        assert profile_for_task_intent("document_export", "terminal").id == "document"

    def test_paper_workflow_routes_to_paper(self):
        assert profile_for_task_intent("paper_workflow", "terminal").id == "paper"

    def test_answer_only_routes_to_chat(self):
        assert profile_for_task_intent("answer_only", "terminal").id == "chat"

    def test_answer_only_overrides_legacy_mode(self):
        assert profile_for_task_intent("answer_only", "coding").id == "chat"

    def test_legacy_document_mode_routes_to_document(self):
        assert profile_for_task_intent("", "document").id == "document"

    def test_unknown_profile_falls_back_to_analysis(self):
        assert get_profile("missing").id == "analysis"

    def test_profile_stage_sequence_for_coding(self):
        assert stage_sequence_for_profile("coding", task_intent="write_required") == [
            "explorer", "editor", "verifier", "reviewer",
        ]

    def test_profile_round_limit_for_document_explorer(self):
        assert round_limit_for_profile("document", "explorer") == 4


class TestPlanningPolicy:
    def test_answer_only_skips_model_plan_judge(self):
        decision = deterministic_plan_gate("你好", "answer_only", "terminal", "auto")
        assert decision.enabled is False
        assert not decision.needs_model_judge

    def test_always_plan_respects_user_setting(self):
        decision = deterministic_plan_gate("你好", "answer_only", "terminal", "always")
        assert decision.enabled is True
        assert decision.source == "user"

    def test_off_plan_respects_user_setting(self):
        decision = deterministic_plan_gate("分析当前项目", "read_only_analysis", "terminal", "off")
        assert decision.enabled is False
        assert decision.source == "user"

    def test_project_analysis_uses_plan_without_model_judge(self):
        decision = deterministic_plan_gate("分析当前项目架构并输出风险清单", "read_only_analysis", "terminal", "auto")
        assert decision.enabled is True
        assert decision.source == "policy"

    def test_simple_read_only_skips_plan(self):
        decision = deterministic_plan_gate("解释一下这个函数的作用", "read_only_analysis", "terminal", "auto")
        assert decision.enabled is False

    def test_ambiguous_analysis_can_use_model_judge(self):
        decision = deterministic_plan_gate("看一下这个项目", "read_only_analysis", "terminal", "auto")
        assert decision.enabled is None
        assert decision.needs_model_judge

    def test_resolve_profile_uses_policy_entrypoint(self):
        assert resolve_profile("document_export", "terminal").id == "document"

    def test_heuristic_plan_execution_skips_greeting(self):
        assert not heuristic_plan_execution("你好", "terminal")


# ═══════════════════════════════════════════════════════════════════════════
# 5b: Tool classification
# ═══════════════════════════════════════════════════════════════════════════

class TestIsWriteTool:
    def test_edit_file(self):
        assert is_write_tool("code.edit_file")

    def test_write_file(self):
        assert is_write_tool("filesystem.write_file")

    def test_read_file_not_write(self):
        assert not is_write_tool("filesystem.read_file")

    def test_document_export(self):
        assert is_write_tool("document.export_pdf")

    def test_pdf_to_docx(self):
        assert is_write_tool("document.extract_pdf_to_docx")


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

    def test_read_file_in_paper_mode(self):
        assert is_verification_tool("filesystem.read_file", "paper")

    def test_read_file_in_coding_mode(self):
        assert not is_verification_tool("filesystem.read_file", "coding")


class TestExplorerToolIds:
    def test_base_tools(self):
        ids = explorer_tool_ids(None)
        assert "filesystem.read_file" in ids
        assert "code.search_text" in ids

    def test_coding_adds_git(self):
        ids = explorer_tool_ids("coding")
        assert "git.status" in ids
        assert "git.log" in ids

    def test_document_no_git(self):
        ids = explorer_tool_ids("document")
        assert "git.status" not in ids


class TestVerificationToolIds:
    def test_base(self):
        ids = verification_tool_ids(None)
        assert "shell.run_command" in ids

    def test_paper_adds_read(self):
        ids = verification_tool_ids("paper")
        assert "filesystem.read_file" in ids


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


class TestTryFixJson:
    def test_valid_json(self):
        assert try_fix_json('{"a": 1}') == {"a": 1}

    def test_unclosed_brace(self):
        assert try_fix_json('{"path": "test.py"') == {"path": "test.py"}

    def test_unclosed_bracket(self):
        result = try_fix_json('{"items": [1, 2')
        assert result == {"items": [1, 2]}

    def test_unclosed_string_with_brace(self):
        # When both a quote and a brace are unclosed, the fix produces {"key": "val}"}
        result = try_fix_json('{"key": "val')
        # The repair appends " then }, producing valid JSON with value "val}"
        assert result == {"key": "val}"}

    def test_empty(self):
        assert try_fix_json("") == {}

    def test_unfixable(self):
        assert try_fix_json("not json at all {{{") == {}


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
        events = [{"tool": "shell.run_command", "status": "success"}]
        assert has_successful_verification(events, None)

    def test_no_verification_tool(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        assert not has_successful_verification(events, "coding")


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


# ═══════════════════════════════════════════════════════════════════════════
# 5d: Stage management
# ═══════════════════════════════════════════════════════════════════════════

class TestExecutionStageSequence:
    def test_code_change(self):
        assert execution_stage_sequence("coding", True) == ["explorer", "editor", "verifier", "reviewer"]

    def test_terminal_code_change(self):
        assert execution_stage_sequence("terminal", True) == ["explorer", "editor", "verifier", "reviewer"]

    def test_paper_analysis(self):
        assert execution_stage_sequence("paper", False, "read_only_analysis") == ["explorer", "reviewer"]

    def test_paper_write(self):
        assert execution_stage_sequence("paper", False, "write_required") == ["explorer", "writer", "integrity_gate", "reviewer"]

    def test_document_export(self):
        assert execution_stage_sequence("document", False, "document_export") == ["explorer", "creator", "verifier", "reviewer"]

    def test_default(self):
        assert execution_stage_sequence(None, False) == ["explorer", "reviewer"]


class TestStageRoundLimit:
    def test_explorer_coding(self):
        assert stage_round_limit("explorer", "coding", True) == 5

    def test_editor(self):
        assert stage_round_limit("editor", None, False) == 5

    def test_verifier(self):
        assert stage_round_limit("verifier", None, False) == 2

    def test_writer(self):
        assert stage_round_limit("writer", "paper", False) == 3

    def test_integrity_gate(self):
        assert stage_round_limit("integrity_gate", "paper", False) == 1

    def test_document_explorer(self):
        assert stage_round_limit("explorer", "document", False) == 4


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

    def test_not_a_dict(self):
        assert not plan_has_pending_write_step(None)


# ═══════════════════════════════════════════════════════════════════════════
# 5e: Plan tracking
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeToolId:
    def test_double_underscore(self):
        assert normalize_tool_id("filesystem__read_file") == "filesystem.read_file"

    def test_already_dot(self):
        assert normalize_tool_id("code.edit_file") == "code.edit_file"

    def test_legacy_code_search_alias(self):
        assert normalize_tool_id("code.search") == "code.search_text"

    def test_legacy_filesystem_list_dir_alias(self):
        assert normalize_tool_id("filesystem.list_dir") == "filesystem.scan_folder"

    def test_legacy_shell_execute_alias(self):
        assert normalize_tool_id("shell.execute") == "shell.run_command"

    def test_legacy_pdf_extract_alias(self):
        assert normalize_tool_id("document.pdf_extract_text") == "document.extract_pdf_text_preview"

    def test_none(self):
        assert normalize_tool_id(None) == ""


class TestExtractPlanJson:
    def test_plain_json(self):
        result = extract_plan_json('{"title": "test", "steps": []}')
        assert result == {"title": "test", "steps": []}

    def test_fenced_json(self):
        result = extract_plan_json('```json\n{"title": "test"}\n```')
        assert result == {"title": "test"}

    def test_invalid(self):
        assert extract_plan_json("not json") is None


class TestNormalizeExecutionPlan:
    def test_valid_plan(self):
        raw = json.dumps({
            "title": "修改登录",
            "steps": [
                {"title": "读取文件", "description": "读取 login.py", "tool_hint": "filesystem.read_file"},
            ]
        })
        plan = normalize_execution_plan(raw, "coding")
        assert plan["title"] == "修改登录"
        assert len(plan["steps"]) == 1
        assert plan["steps"][0]["status"] == "pending"

    def test_invalid_falls_back(self):
        plan = normalize_execution_plan("garbage", "coding")
        assert plan["title"] == "计划执行"
        assert len(plan["steps"]) > 0


class TestFallbackExecutionPlan:
    def test_coding(self):
        plan = fallback_execution_plan("coding")
        assert len(plan["steps"]) == 5

    def test_paper(self):
        plan = fallback_execution_plan("paper")
        assert len(plan["steps"]) == 5

    def test_default(self):
        plan = fallback_execution_plan(None)
        assert len(plan["steps"]) == 5


class TestToolMatchesPlanStep:
    def test_exact_match(self):
        step = {"title": "读取文件", "tool_hint": "filesystem.read_file"}
        assert tool_matches_plan_step("filesystem.read_file", step)

    def test_write_semantic_match(self):
        step = {"title": "修改代码", "description": "编辑文件", "tool_hint": ""}
        assert tool_matches_plan_step("code.edit_file", step)

    def test_no_match(self):
        step = {"title": "读取文件", "tool_hint": "filesystem.read_file", "description": ""}
        assert not tool_matches_plan_step("code.edit_file", step)


class TestMarkNextPlanStepRunning:
    def test_marks_matching_step(self):
        plan = {
            "steps": [
                {"title": "读取文件", "tool_hint": "filesystem.read_file", "status": "pending"},
                {"title": "修改代码", "tool_hint": "code.edit_file", "status": "pending"},
            ]
        }
        tool_call = {"function": {"name": "filesystem__read_file"}}
        index = mark_next_plan_step_running(plan, tool_call)
        assert index == 0
        assert plan["steps"][0]["status"] == "running"

    def test_no_match_returns_none(self):
        plan = {
            "steps": [
                {"title": "读取文件", "tool_hint": "filesystem.read_file", "status": "pending"},
            ]
        }
        tool_call = {"function": {"name": "code__edit_file"}}
        assert mark_next_plan_step_running(plan, tool_call) is None

    def test_none_plan(self):
        assert mark_next_plan_step_running(None, {}) is None


class TestFinishPlanStep:
    def test_success(self):
        plan = {"steps": [{"title": "read", "status": "running"}]}
        finish_plan_step(plan, 0, {"status": "success", "name": "filesystem.read_file"})
        assert plan["steps"][0]["status"] == "completed"

    def test_failure(self):
        plan = {"steps": [{"title": "edit", "status": "running"}]}
        finish_plan_step(plan, 0, {"status": "failure", "error": "not found"})
        assert plan["steps"][0]["status"] == "failed"
        assert plan["steps"][0]["error"] == "not found"

    def test_out_of_range(self):
        plan = {"steps": []}
        finish_plan_step(plan, 5, {"status": "success"})  # should not raise


class TestCompleteRemainingPlanSteps:
    def test_marks_pending_as_skipped(self):
        plan = {
            "steps": [
                {"title": "a", "status": "completed"},
                {"title": "b", "status": "pending"},
                {"title": "c", "status": "running"},
            ]
        }
        complete_remaining_plan_steps(plan, failed=False, had_tool_events=True)
        assert plan["steps"][0]["status"] == "completed"
        assert plan["steps"][1]["status"] == "skipped"
        assert plan["steps"][2]["status"] == "skipped"

    def test_failed_marks_all(self):
        plan = {"steps": [{"title": "x", "status": "pending"}]}
        complete_remaining_plan_steps(plan, failed=True)
        assert plan["steps"][0]["status"] == "skipped"


class TestInterruptExecutionPlan:
    def test_resets_running_to_pending(self):
        plan = {
            "steps": [
                {"title": "a", "status": "completed"},
                {"title": "b", "status": "running", "note": ""},
            ]
        }
        interrupt_execution_plan(plan)
        assert plan["steps"][1]["status"] == "pending"
        assert "插话" in plan["steps"][1]["note"]


# ═══════════════════════════════════════════════════════════════════════════
# Prompt construction (spot checks)
# ═══════════════════════════════════════════════════════════════════════════

class TestPrompts:
    def test_stage_status_message(self):
        assert "侦察者" in stage_status_message("explorer")
        assert "执行" in stage_status_message("unknown_stage")

    def test_stage_prompt_explorer(self):
        prompt = stage_prompt("explorer", "/tmp/project", "coding", True)
        assert "/tmp/project" in prompt
        assert "Explorer" in prompt

    def test_stage_prompt_editor(self):
        prompt = stage_prompt("editor", "/tmp", None, True)
        assert "Editor" in prompt
        assert "filesystem.read_file" in prompt

    def test_progress_observer_prompt(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        prompt = progress_observer_prompt("/tmp", "explorer", events, True, "stagnation")
        assert "stagnation" in prompt
        assert "尚未写入" in prompt  # code_change_intent=True, no write yet

    def test_recon_budget_prompt(self):
        prompt = recon_budget_prompt(5, "/tmp")
        assert "5" in prompt

    def test_write_repair_prompt(self):
        prompt = write_repair_prompt(
            "code.edit_file",
            {"path": "main.py"},
            {"error": "old_text not found"},
            "/tmp",
        )
        assert "old_text" in prompt

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

    def test_max_rounds_message(self):
        events = [{"tool": "filesystem.read_file", "status": "success"}]
        msg = max_rounds_message(10, events)
        assert "10" in msg

    def test_verifier_retry_prompt_coding(self):
        prompt = verifier_retry_prompt("coding", "/tmp")
        assert "shell.run_command" in prompt

    def test_verifier_retry_prompt_paper(self):
        prompt = verifier_retry_prompt("paper", "/tmp")
        assert "document.extract_docx_outline" in prompt
