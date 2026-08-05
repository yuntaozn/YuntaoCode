from __future__ import annotations

import json

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
            ],
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

    def test_fallback_is_neutral_across_modes(self):
        coding = fallback_execution_plan("coding")
        paper = fallback_execution_plan("paper")
        general = fallback_execution_plan(None)

        assert coding["steps"] == paper["steps"] == general["steps"]
        assert all(not step["tool_hint"] for step in coding["steps"])


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

    def test_explicit_write_hint_does_not_match_read_tool(self):
        step = {"title": "重写HTML页面", "tool_hint": "filesystem.write_file", "description": "创建文件"}
        assert not tool_matches_plan_step("filesystem.read_text_preview", step)


class TestMarkNextPlanStepRunning:
    def test_marks_matching_step(self):
        plan = {
            "steps": [
                {"title": "读取文件", "tool_hint": "filesystem.read_file", "status": "pending"},
                {"title": "修改代码", "tool_hint": "code.edit_file", "status": "pending"},
            ],
        }
        tool_call = {"function": {"name": "filesystem__read_file"}}
        index = mark_next_plan_step_running(plan, tool_call)
        assert index == 0
        assert plan["steps"][0]["status"] == "running"

    def test_no_match_returns_none(self):
        plan = {
            "steps": [
                {"title": "读取文件", "tool_hint": "filesystem.read_file", "status": "pending"},
            ],
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
        finish_plan_step(plan, 5, {"status": "success"})  # 不应抛出异常


class TestCompleteRemainingPlanSteps:
    def test_marks_pending_as_skipped(self):
        plan = {
            "steps": [
                {"title": "a", "status": "completed"},
                {"title": "b", "status": "pending"},
                {"title": "c", "status": "running"},
            ],
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
            ],
        }
        interrupt_execution_plan(plan)
        assert plan["steps"][1]["status"] == "pending"
        assert "插话" in plan["steps"][1]["note"]
