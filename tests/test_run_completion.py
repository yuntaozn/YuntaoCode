from runtime.run_completion import build_completion_decision


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
