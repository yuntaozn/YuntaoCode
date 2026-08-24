from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.run_scenario import RunScenario


@pytest.mark.asyncio
async def test_real_run_pipeline_keeps_direct_answer_to_one_execution_round(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = RunScenario(
        workspace_path=tmp_path,
        user_content="What is this project?",
        model_rounds=[[{"message": "It is a local-first AI Task Runtime."}, {"finish_reason": "stop"}]],
        tool_results=[],
        task_intent="answer_only",
        requires_write=False,
        requires_verification=False,
    )

    result = await scenario.run(monkeypatch)

    assert len(result.execution_model_calls) == 1
    assert result.tool_calls == []
    assert result.synthesis_calls == []
    assert result.run_result["status"] == "no_tool_activity"
    assert result.assistant.content == "It is a local-first AI Task Runtime."


@pytest.mark.asyncio
async def test_task_contract_failure_returns_directly_to_main_execution_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = RunScenario(
        workspace_path=tmp_path,
        user_content="Analyze the current project.",
        model_rounds=[[
            {"message": "I can analyze it from the available project evidence."},
            {"finish_reason": "stop"},
        ]],
        tool_results=[],
        task_intent="answer_only",
        requires_write=False,
        requires_verification=False,
        planning_policy="auto",
        model_task_contract_error="Timeout during task contract request",
    )

    result = await scenario.run(monkeypatch)

    assert result.task_contract_calls == 1
    assert len(result.execution_model_calls) == 1
    assert result.synthesis_calls == []
    assert result.assistant.content == "I can analyze it from the available project evidence."
    assert not any(
        event.get("event") == "status" and event.get("status") == "plan_deciding"
        for event in result.events
    )
    plan_events = [event for event in result.events if event.get("event") == "plan_decision"]
    assert plan_events[-1]["decision"]["source"] == "main_execution"
    assert plan_events[-1]["decision"]["enabled"] is False


def _tool_round(call_id: str, tool_id: str, **arguments: Any) -> list[dict[str, Any]]:
    return [
        {
            "tool_calls": [{
                "index": 0,
                "id": call_id,
                "function": {
                    "name": tool_id.replace(".", "__"),
                    "arguments": json.dumps(arguments),
                },
            }],
        },
        {"finish_reason": "tool_calls"},
    ]


def _final_round(answer: str, *, goal_closed: bool = True) -> list[dict[str, Any]]:
    assessment = json.dumps({
        "schema_version": "completion_self_assessment.v1",
        "kind": "completion_self_assessment",
        "goal_closed": goal_closed,
        "remaining_work": [] if goal_closed else ["more work remains"],
        "verification_limits": [],
    })
    return [
        {"message": f"{assessment}\n{answer}"},
        {"finish_reason": "stop"},
    ]


@pytest.mark.asyncio
async def test_real_run_pipeline_reaches_verified_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "output.txt"
    scenario = RunScenario(
        workspace_path=tmp_path,
        user_content="Create output.txt and verify it.",
        model_rounds=[
            _tool_round("write-1", "filesystem.write_file", path=str(target), content="done"),
            _tool_round("verify-1", "shell.run_command", command="verify output.txt"),
            _final_round("Created output.txt and verified the result."),
        ],
        tool_results=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "output": {"path": str(target)},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "output": {"exit_code": 0, "stdout": "ok"},
            },
        ],
    )

    result = await scenario.run(monkeypatch)

    assert result.run_result["status"] == "success"
    assert [item["tool"] for item in result.tool_calls] == [
        "filesystem.write_file",
        "shell.run_command",
    ]
    assert len(result.execution_model_calls) == 3
    assert result.synthesis_calls == []
    assert result.assistant.content.startswith("Created output.txt and verified the result.")
    assert not any(event.get("event") == "completion_decision" for event in result.events)
    assert all(
        sum(
            "Review fresh runtime evidence" in str(message.get("content") or "")
            for message in call["messages"]
        ) <= 1
        for call in result.execution_model_calls
    )
    assert result.events[-1]["event"] == "done"


@pytest.mark.asyncio
async def test_real_run_pipeline_preserves_model_answer_after_route_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "output.txt"
    scenario = RunScenario(
        workspace_path=tmp_path,
        user_content="Create output.txt.",
        model_rounds=[
            _tool_round("write-1", "filesystem.write_file", path=str(target), content="too large"),
            _tool_round("write-2", "code.apply_patch", patch="create output.txt"),
            _final_round(
                "The first write route failed, so I changed route and created output.txt. "
                "No independent verification was run."
            ),
        ],
        tool_results=[
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "error": "provider rejected the large request",
                "output": {"reason": "provider_error"},
            },
            {
                "tool": "code.apply_patch",
                "status": "success",
                "output": {"path": str(target)},
            },
        ],
    )

    result = await scenario.run(monkeypatch)

    assert [item["tool"] for item in result.tool_calls] == [
        "filesystem.write_file",
        "code.apply_patch",
    ]
    assert result.run_result["status"] == "partial"
    assert result.synthesis_calls == []
    assert result.assistant.content.startswith("The first write route failed")
    assert "runtime partial fallback" not in result.assistant.content
    assert "unexpected synthesized answer" not in result.assistant.content


@pytest.mark.asyncio
async def test_real_run_pipeline_drops_stale_convergence_prompt_after_route_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "output.txt"
    scenario = RunScenario(
        workspace_path=tmp_path,
        user_content="Create output.txt and recover if one route fails.",
        model_rounds=[
            _tool_round(
                "write-1",
                "filesystem.write_file",
                path=str(target),
                content="same attempt",
            ),
            _tool_round(
                "write-2",
                "filesystem.write_file",
                path=str(target),
                content="same attempt",
            ),
            _tool_round("write-3", "code.apply_patch", patch="create output.txt"),
            _final_round("Changed route and created output.txt."),
        ],
        tool_results=[
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "error": "same provider failure",
                "output": {"reason": "provider_error"},
            },
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "error": "same provider failure",
                "output": {"reason": "provider_error"},
            },
            {
                "tool": "code.apply_patch",
                "status": "success",
                "output": {"path": str(target)},
            },
        ],
    )

    result = await scenario.run(monkeypatch)

    convergence_text = "The same route has repeated without progress"
    assert any(
        convergence_text in str(message.get("content") or "")
        for message in result.execution_model_calls[2]["messages"]
    )
    assert all(
        convergence_text not in str(message.get("content") or "")
        for message in result.execution_model_calls[3]["messages"]
    )
    assert result.assistant.content.startswith("Changed route and created output.txt.")
