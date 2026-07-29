from __future__ import annotations

from runtime.agent_strategy.convergence import (
    ESCALATE_NO_PROGRESS,
    REPORT_REPETITION,
    build_execution_convergence_decision,
    failure_route_signature,
    format_convergence_decision,
    repeated_failure_action,
)


def _failure(
    *,
    tool: str = "filesystem.write_file",
    path: str = "viewer/index.html",
    content: str = "hello",
    reason: str = "invalid_tool_input",
    error: str = "missing path",
) -> dict:
    return {
        "tool": tool,
        "status": "failure",
        "input": {"path": path, "content": content},
        "error": error,
        "output": {"reason": reason},
    }


def test_same_failed_route_reports_before_budget_escalation() -> None:
    event = _failure()

    decision = build_execution_convergence_decision([event] * 2)

    assert decision.action == REPORT_REPETITION
    assert decision.route_attempt_count == 2
    assert decision.budget_limit_route_attempts == 9
    assert repeated_failure_action([event] * 9) == ESCALATE_NO_PROGRESS


def test_success_resets_no_progress_window() -> None:
    failure = _failure()
    progress = {
        "tool": "filesystem.write_file",
        "status": "success",
        "input": {"path": "viewer/index.html"},
        "output": {"path": "viewer/index.html"},
    }

    decision = build_execution_convergence_decision([failure, failure, progress, failure])

    assert decision.action == "none"
    assert decision.route_attempt_count == 1
    assert decision.distinct_failed_routes == 1


def test_changed_failed_routes_expand_self_correction_budget() -> None:
    first = _failure(path="viewer/index.html", error="missing content")
    second = _failure(
        tool="filesystem.append_text_chunk",
        path="viewer/index.html",
        reason="invalid_tool_input",
        error="draft_id is required",
    )
    events = [first, second, first] + [first] * 9

    decision = build_execution_convergence_decision(events)

    assert decision.route_changed_without_progress is True
    assert decision.distinct_failed_routes == 2
    assert decision.budget_limit_route_attempts == 11
    assert decision.route_attempt_count == 11
    assert decision.action == ESCALATE_NO_PROGRESS
    assert any("budget is saturated" in item for item in decision.model_decision)


def test_changed_route_does_not_pause_at_base_budget() -> None:
    first = _failure(path="viewer/index.html", error="missing content")
    second = _failure(
        tool="filesystem.append_text_chunk",
        path="viewer/index.html",
        reason="invalid_tool_input",
        error="draft_id is required",
    )
    events = [first, second, first] + [first] * 6

    decision = build_execution_convergence_decision(events)

    assert decision.route_attempt_count == 8
    assert decision.budget_limit_route_attempts == 11
    assert decision.action == REPORT_REPETITION


def test_large_input_signature_uses_hash_not_full_content() -> None:
    first = _failure(content="x" * 50_000)
    second = _failure(content="x" * 50_000)

    signature = failure_route_signature(first)

    assert signature == failure_route_signature(second)
    assert len(signature) < 1200
    assert "50000" in signature
    assert "xxxxxxxxxx" not in signature


def test_tool_attempt_observation_fields_reach_prompt_facts() -> None:
    observation = {
        "reason": "invalid_tool_input",
        "boundary": "tool_call_protocol",
        "missing_fields": ["path", "content"],
    }
    decision = build_execution_convergence_decision([
        {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {},
            "error": "missing fields",
            "output": {
                "type": "tool_attempt_observation",
                "reason": "invalid_tool_input",
                "observation": observation,
            },
            "tool_attempt_observation": observation,
        },
        {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {},
            "error": "missing fields",
            "output": {
                "type": "tool_attempt_observation",
                "reason": "invalid_tool_input",
                "observation": observation,
            },
            "tool_attempt_observation": observation,
        },
    ])
    rendered = format_convergence_decision(decision)

    assert decision.latest_boundary == "tool_call_protocol"
    assert decision.latest_missing_fields == ("path", "content")
    assert "latest missing fields: path, content" in rendered
    assert "route attempts" in rendered
