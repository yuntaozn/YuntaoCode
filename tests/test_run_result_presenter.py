from __future__ import annotations

from runtime.core.result import RISK_CODES
from runtime.run_result_presenter import (
    risk_message_zh,
    synthesize_final_answer,
    synthesize_partial_answer,
)


def test_known_run_result_risks_have_schema_codes() -> None:
    assert "document_output_length_unknown" in RISK_CODES
    assert "target_deliverable_not_observed" in RISK_CODES
    assert "invalid_tool_call_protocol" in RISK_CODES
    assert "artifact_integrity_invalid" in RISK_CODES
    assert "shell_stderr_warning" in RISK_CODES


def test_risk_presenter_uses_user_facing_message() -> None:
    assert risk_message_zh("document_output_length_unknown") != "document_output_length_unknown"
    assert "无法确认文档输出长度" in risk_message_zh("document_output_length_unknown")


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
    assert answer.startswith("未完整完成")


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
