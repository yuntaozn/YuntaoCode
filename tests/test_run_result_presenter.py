from __future__ import annotations

from runtime.core.result import RISK_CODES
from runtime.run_result_presenter import (
    append_changed_files_footer,
    answer_only_final_answer_error,
    build_execution_notice,
    build_max_rounds_after_write_message,
    needs_synthesized_final_answer,
    risk_message_zh,
    run_status_from_result,
    synthesize_final_answer,
    synthesize_partial_answer,
)


def test_known_run_result_risks_have_schema_codes() -> None:
    assert "document_output_length_unknown" in RISK_CODES
    assert "answer_output_too_short" in RISK_CODES
    assert "target_deliverable_not_observed" in RISK_CODES
    assert "invalid_tool_call_protocol" in RISK_CODES
    assert "artifact_integrity_invalid" in RISK_CODES
    assert "shell_stderr_warning" in RISK_CODES
    assert "capability_preflight_advisory" in RISK_CODES
    assert "capability_preflight_blocked" not in RISK_CODES


def test_risk_presenter_uses_user_facing_message() -> None:
    assert risk_message_zh("document_output_length_unknown") != "document_output_length_unknown"
    assert "无法确认文档输出长度" in risk_message_zh("document_output_length_unknown")
    assert risk_message_zh("max_rounds_exceeded") == "当前执行预算已用完。"
    assert "反复无新进展" in risk_message_zh("repeated_tool_failure")
    assert "能力预检提示" in risk_message_zh("capability_preflight_advisory")
    assert "最终回答已生成" in risk_message_zh("answer_output_too_short")
    assert "目标仍未闭合" in risk_message_zh("model_reported_goal_open")
    assert "完成自评" in risk_message_zh("model_completion_assessment_inconsistent")


def test_final_answer_gap_detection_is_presentation_fact() -> None:
    contract = {"intent": "answer_only"}

    assert answer_only_final_answer_error("", [], contract) == "model did not return a final answer"
    assert needs_synthesized_final_answer("", [], contract)
    assert not needs_synthesized_final_answer("直接回答。", [], contract)
    assert run_status_from_result({"status": "partial"}) == "partial"
    assert run_status_from_result({"status": "unknown"}) == "success"


def test_partial_answer_maps_risks_to_user_facing_messages() -> None:
    answer = synthesize_partial_answer(
        r"D:\demo",
        [],
        {
            "status": "partial",
            "changed_paths": ["draft.docx"],
            "risks": ["document_output_length_unknown"],
            "counts": {"test_successes": 0},
        },
    )

    assert "draft.docx" in answer
    assert "document_output_length_unknown" not in answer
    assert "无法确认文档输出长度" in answer
    assert answer.startswith("运行事实摘要")
    assert "可继续依据" in answer
    assert "建议：" not in answer


def test_max_rounds_after_write_message_is_evidence_based() -> None:
    message = build_max_rounds_after_write_message(
        4,
        [
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "src/app.js"},
            }
        ],
        is_write_tool=lambda tool_id: tool_id == "filesystem.write_file",
    )

    assert "运行事实摘要" in message
    assert "src/app.js" in message
    assert "可继续依据" in message
    assert "建议：" not in message


def test_execution_notice_is_neutral_presentation_evidence() -> None:
    notice = build_execution_notice(
        "terminal",
        "已修改 viewer.html",
        [
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "viewer.html"},
            },
        ],
        run_result={
            "risks": ["optional_write_not_verified"],
            "observed_written_paths": ["viewer.html"],
        },
        is_write_tool=lambda tool_id: tool_id == "filesystem.write_file",
        is_invalid_verification_method_event=lambda _event: False,
        assistant_claims_code_changed=lambda _content: True,
    )

    assert notice is not None
    assert notice["reason"] == "optional_write_not_verified"
    assert notice["facts"] == ["write_observed", "verification_not_observed"]
    assert notice["written_paths"] == ["viewer.html"]
    assert "运行事实提示" in notice["message"]
    assert "系统已判定" not in notice["message"]


def test_final_answer_summarizes_changed_paths_and_verification() -> None:
    answer = synthesize_final_answer(
        r"D:\demo",
        [
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": r"D:\demo\viewer.html"},
                "output": {"path": r"D:\demo\viewer.html"},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "node --check viewer.html"},
                "output": {"exit_code": 0},
            },
        ],
        {"files": [{"path": "viewer.html"}]},
        "coding",
        None,
        is_write_tool=lambda tool_id: tool_id == "filesystem.write_file",
        is_verification_tool=lambda tool_id, _mode: tool_id == "shell.run_command",
        relative_workspace_path=lambda _workspace, path: str(path).replace(r"D:\demo\\", ""),
        tool_event_failed=lambda _event: False,
        tool_event_failure_message=lambda _event: "",
    )

    assert "新增/变更文件：" in answer
    assert "- viewer.html" in answer
    assert "已执行验证：" in answer
    assert "shell.run_command" in answer


def test_final_answer_summarizes_external_state_deliverable() -> None:
    answer = synthesize_final_answer(
        r"D:\demo",
        [
            {
                "tool": "mcp_blender.execute_blender_code",
                "status": "success",
                "output": {
                    "content": "ok",
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            },
        ],
        None,
        "chat",
        {
            "requires_state_change": True,
            "deliverables": [{"kind": "external_state"}],
        },
        is_write_tool=lambda _tool_id: False,
        is_verification_tool=lambda _tool_id, _mode: False,
        relative_workspace_path=lambda _workspace, path: str(path),
        tool_event_failed=lambda _event: False,
        tool_event_failure_message=lambda _event: "",
    )

    assert "已观察到目标外部状态变更：" in answer
    assert "- mcp_blender.execute_blender_code" in answer


def test_append_changed_files_footer_adds_runtime_file_list() -> None:
    answer = append_changed_files_footer(
        "已完成页面优化，并通过预览确认视觉效果。",
        {
            "changed_paths": ["src/app.js"],
            "written_paths": ["src/app.js", "src/styles.css"],
        },
        {"files": [{"status": "M", "path": "src/app.js"}]},
    )

    assert "本轮新增/变更文件：" in answer
    assert "- src/app.js" in answer
    assert "- src/styles.css" in answer
    assert answer.count("src/app.js") == 1


def test_append_changed_files_footer_does_not_duplicate_existing_section() -> None:
    content = "已完成。\n\n本轮新增/变更文件：\n- src/app.js"

    assert append_changed_files_footer(
        content,
        {"changed_paths": ["src/app.js", "src/styles.css"]},
        None,
    ) == content


def test_append_changed_files_footer_uses_english_for_english_answer() -> None:
    answer = append_changed_files_footer(
        "Done and verified.",
        {"written_paths": ["README.md"]},
        None,
    )

    assert "Files changed this turn:" in answer
    assert "- README.md" in answer
