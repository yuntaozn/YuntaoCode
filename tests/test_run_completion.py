from runtime.run_completion import (
    build_completion_decision,
    build_completion_evidence_pack,
    format_completion_evidence_pack,
)
from runtime.tool_call_protocol import build_tool_attempt_observation


def test_completion_evidence_pack_collects_audits_progress_and_decisions() -> None:
    tool_attempt = build_tool_attempt_observation(
        tool_id="filesystem.write_file",
        arguments={"content": "hello"},
        reason="invalid_tool_input",
        message="missing path",
        missing_fields=["path"],
    )
    pack = build_completion_evidence_pack(
        workspace_path="D:/demo",
        task_contract={"goal": "create and verify an HTML viewer", "intent": "write_required"},
        run_result={
            "status": "partial",
            "target_written_paths": ["viewer/index.html"],
            "verification_evidence": [
                {
                    "tool": "preview.capture_file",
                    "path": "viewer/index.html",
                    "strength": "standard",
                    "sufficient": True,
                    "modalities": ["visual", "runtime"],
                }
            ],
            "visual_verification": {
                "schema_version": "visual_verification.v1",
                "kind": "visual_verification",
                "boundary": "evidence_only",
                "counts": {"visual_evidence": 1, "runtime_error_records": 1},
                "flags": {"has_visual_evidence": True, "has_runtime_errors": True},
            },
            "debug_audit": {
                "schema_version": "debug_audit.v1",
                "kind": "debug_audit",
                "boundary": "evidence_only",
                "counts": {"debug_sessions": 1, "preview_sessions": 1},
                "flags": {"has_preview_service": True},
            },
            "capability_evidence": {
                "schema_version": "capability_evidence_summary.v1",
                "requested_capability_ids": ["code.text_write"],
                "observed_capability_ids": ["code.text_write", "preview.visual_debug"],
                "unobserved_requested_capability_ids": [],
            },
            "risks": ["test_not_observed"],
            "counts": {"deliverable_successes": 1, "verification_successes": 1, "failures": 0},
        },
        tool_events=[
            {
                "tool": "shell.run_command",
                "status": "running",
                "progress": {
                    "tool_task": {
                        "kind": "tool_task_progress",
                        "task_id": "task-1",
                        "tool": "shell.run_command",
                        "status": "running",
                        "elapsed_seconds": 120,
                        "stale_seconds": 60,
                        "can_cancel": True,
                        "command": {"role": "dependency_install"},
                        "flags": {"has_heartbeat": True, "has_live_output": True},
                        "last_log": {
                            "level": "info",
                            "kind": "command_heartbeat",
                            "message": "command still running",
                        },
                        "last_heartbeat": {"silent_seconds": 60, "elapsed_seconds": 120},
                    }
                },
            },
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {"content": "hello"},
                "error": "missing path",
                "output": {
                    "type": "tool_attempt_observation",
                    "reason": "invalid_tool_input",
                    "message": "missing path",
                    "observation": tool_attempt,
                },
                "tool_attempt_observation": tool_attempt,
            }
        ],
        completion_decisions=[
            {"review_count": 1, "action": "continue_with_tools", "tool_call_count": 1}
        ],
    )
    text = format_completion_evidence_pack(pack)

    assert pack["schema_version"] == "completion_evidence_pack.v1"
    assert pack["boundary"] == "evidence_only"
    assert pack["tool_progress"][0]["role"] == "dependency_install"
    assert pack["tool_attempts"][0]["missing_fields"] == ["path"]
    assert pack["visual_verification"]["flags"]["has_runtime_errors"] is True
    assert pack["debug_audit"]["flags"]["has_preview_service"] is True
    assert pack["previous_completion_decisions"][0]["action"] == "continue_with_tools"
    assert "Completion evidence pack" in text
    assert "viewer/index.html" in text
    assert "recent tool progress" in text
    assert "recent unexecuted tool attempts" in text
    assert "dependency_install" in text
    assert "invalid_tool_input" in text


def test_completion_decision_records_continue_with_tools_without_forcing_strategy() -> None:
    decision = build_completion_decision(
        review_count=1,
        run_result={"status": "success", "risks": []},
        tool_calls=[{"name": "filesystem.read_text_preview"}],
        content="",
        finish_reason="tool_calls",
    )

    assert decision["schema_version"] == "completion_decision.v1"
    assert decision["source"] == "model_observed_behavior"
    assert decision["action"] == "continue_with_tools"
    assert decision["tool_call_count"] == 1
    assert decision["result_status"] == "success"
    assert decision["evidence_pack"] == {}


def test_completion_decision_records_final_answer_candidate() -> None:
    content = "I completed the file but did not run tests."
    decision = build_completion_decision(
        review_count=2,
        run_result={"status": "partial", "risks": ["write_not_verified"]},
        tool_calls=[],
        content=content,
        finish_reason="stop",
    )

    assert decision["action"] == "final_answer_candidate"
    assert decision["content_chars"] == len(content)
    assert decision["risks"] == ["write_not_verified"]


def test_completion_decision_records_protocol_repair_evidence() -> None:
    decision = build_completion_decision(
        review_count=1,
        run_result={"status": "partial"},
        tool_calls=[],
        content="<toolcall>filesystem.write_file</toolcall>",
        reason="malformed_tool_call",
    )

    assert decision["action"] == "repair_protocol"
    assert decision["reason"] == "malformed_tool_call"


def test_completion_decision_records_compact_evidence_pack_summary() -> None:
    decision = build_completion_decision(
        review_count=2,
        run_result={"status": "partial", "risks": ["visual_verification_not_observed"]},
        tool_calls=[],
        content="Still missing visual verification.",
        evidence_pack={
            "schema_version": "completion_evidence_pack.v1",
            "kind": "completion_evidence_pack",
            "boundary": "evidence_only",
            "result_status": "partial",
            "risks": ["visual_verification_not_observed"],
            "missing_verification_modalities": ["visual"],
            "tool_progress": [
                {"tool": "preview.capture_file", "status": "failure", "role": "preview_service"}
            ],
            "tool_attempts": [
                {"tool": "filesystem.write_file", "reason": "invalid_tool_input"}
            ],
        },
    )

    assert decision["evidence_pack"]["schema_version"] == "completion_evidence_pack.v1"
    assert decision["evidence_pack"]["result_status"] == "partial"
    assert decision["evidence_pack"]["missing_verification_modalities"] == ["visual"]
    assert decision["evidence_pack"]["tool_progress"][0]["tool"] == "preview.capture_file"
    assert decision["evidence_pack"]["tool_attempts"][0]["tool"] == "filesystem.write_file"
