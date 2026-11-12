from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.run_scenario import RunScenario, ScenarioMessage
from tests.fakes.image_output import image_output


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
async def test_inline_tool_pixels_reach_model_and_transport_fallback_is_not_visual_receipt(monkeypatch, tmp_path, fallback):
    rounds = [
        _tool_round("capture-1", "mcp_demo.capture"),
    ]
    if fallback:
        rounds.append([{"error": "HTTP 400: image input not supported"}])
    rounds.append([{"message": "The screenshot is black; visual verification is not established."}, {"finish_reason": "stop"}])
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Inspect the screenshot", supports_vision=True,
        task_intent="answer_only", requires_write=False, requires_verification=False,
        model_rounds=rounds, tool_results=[{"tool": "mcp_demo.capture", "status": "success", "output": {**image_output(), "artifacts": ["image"]}}],
    )
    result = await scenario.run(monkeypatch)
    image_messages = [m for m in result.execution_model_calls[1]["messages"] if isinstance(m.get("content"), list)]
    assert image_messages[0]["content"][1]["type"] == "image_url"
    receipt = result.assistant.metadata["visual_context_evidence"][0]
    assert receipt["delivery_status"] == ("omitted_transport_fallback" if fallback else "accepted")
    assert receipt["injected_into_model_context"] is (not fallback)
    assert "data_url" not in receipt
    visual = result.run_result["visual_verification"]
    assert visual["counts"]["visual_evidence"] == 1
    assert visual["counts"]["model_context_injected"] == (0 if fallback else 1)
    assert visual["records"][0]["visual_review_status"] == "unconfirmed"
    assert result.synthesis_calls == []


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
@pytest.mark.parametrize("planning_policy", ["off", "auto", "always"])
async def test_main_execution_starts_without_auxiliary_task_contract_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    planning_policy: str,
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
        planning_policy=planning_policy,
        model_task_contract_error="Timeout during task contract request",
    )

    result = await scenario.run(monkeypatch)

    assert result.task_contract_calls == 0
    assert len(result.execution_model_calls) == 1
    assert result.synthesis_calls == []
    assert result.assistant.content == "I can analyze it from the available project evidence."
    assert not any(
        event.get("event") == "status" and event.get("status") == "plan_deciding"
        for event in result.events
    )
    plan_events = [event for event in result.events if event.get("event") == "plan_decision"]
    assert plan_events == []
    assert not any(event.get("event") == "plan" for event in result.events)
    assert result.execution_model_calls[0]["tools"]
    assert result.assistant.metadata["task_contract"]["requires_plan"] is False


@pytest.mark.asyncio
async def test_successful_write_and_verification_do_not_require_task_bookkeeping(monkeypatch, tmp_path):
    target = str(tmp_path / "output.txt")
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Create output.txt and verify it", planning_policy="auto",
        model_rounds=[
            _tool_round("write", "filesystem.write_file", path=target, content="done"),
            _tool_round("verify", "filesystem.read_file", path=target),
            [{"message": "Created output.txt and checked its contents."}, {"finish_reason": "stop"}],
        ],
        tool_results=[
            {"tool": "filesystem.write_file", "status": "success", "output": {"path": target}},
            {"tool": "filesystem.read_file", "status": "success", "output": {"path": target, "content": "done"}},
        ],
    )
    result = await scenario.run(monkeypatch)
    assert result.run_result["status"] == "success"
    assert result.run_result["execution_status"] == "completed"
    assert result.run_result["goal_status"] == "unknown"
    assert len(result.tool_calls) == 2
    assert result.task_contract_calls == 0
    assert result.synthesis_calls == []


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
    return [{"message": answer}, {"finish_reason": "stop"}]


@pytest.mark.asyncio
async def test_completion_json_in_answer_is_preserved_without_creating_task_state(monkeypatch, tmp_path):
    body = '{"schema_version":"completion_self_assessment.v1","kind":"completion_self_assessment","goal_closed":true}\n这是协议示例。\n'
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="解释这个 JSON 协议", tool_results=[],
        model_rounds=[_final_round(body)],
    )
    result = await scenario.run(monkeypatch)
    assert result.assistant.content == body
    assert result.run_result["goal_status"] == "unknown"
    assert not result.assistant.metadata.get("completion_decisions")
    assert result.synthesis_calls == []


@pytest.mark.asyncio
async def test_model_can_repeat_identical_failed_call_until_it_succeeds(monkeypatch, tmp_path):
    call = _tool_round("read", "filesystem.read_file", path="output.txt")
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="等文件出现后读取", tool_results=[
            {"tool": "filesystem.read_file", "status": "failure", "error": "not found"},
            {"tool": "filesystem.read_file", "status": "failure", "error": "not found"},
            {"tool": "filesystem.read_file", "status": "success", "output": {"content": "ready"}},
        ], model_rounds=[call, call, call, _final_round("ready")],
    )
    result = await scenario.run(monkeypatch)
    assert len(result.tool_calls) == 3
    assert result.assistant.content == "ready"
    assert result.synthesis_calls == []
    systems = [[m for m in request["messages"] if m["role"] == "system"] for request in result.execution_model_calls]
    assert all(messages == systems[0] for messages in systems)



@pytest.mark.asyncio
@pytest.mark.parametrize("clear_plan", [False, True])
async def test_optional_plan_neither_drives_tools_nor_requires_completion(monkeypatch, tmp_path, clear_plan):
    rounds = [
        _tool_round("plan", "runtime.update_task", plan=["Export a document"]),
        _tool_round("read", "filesystem.read_file", path="README.md"),
    ]
    if clear_plan:
        rounds.append(_tool_round("clear", "runtime.update_task", plan=[]))
    rounds.append([{"message": "Read the project description."}, {"finish_reason": "stop"}])
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Read the project description", planning_policy="always",
        model_rounds=rounds, task_intent="answer_only", requires_write=False, requires_verification=False,
        tool_results=[{"tool": "filesystem.read_file", "status": "success", "output": {"content": "project"}}],
    )
    result = await scenario.run(monkeypatch)
    assert len(result.execution_model_calls) == len(rounds)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool"] == "filesystem.read_file"
    assert not any(event["event"] == "plan_step" for event in result.events)
    plan = result.assistant.metadata["execution_plan"]
    if clear_plan:
        assert plan is None
        assert [event for event in result.events if event["event"] == "plan"][-1]["plan"] is None
    else:
        assert plan["steps"][0]["status"] == "pending"
    initial_system = [m for m in result.execution_model_calls[0]["messages"] if m["role"] == "system"]
    for call in result.execution_model_calls[1:]:
        assert [m for m in call["messages"] if m["role"] == "system"] == initial_system
    assert result.synthesis_calls == []


@pytest.mark.asyncio
async def test_native_task_progress_keeps_inspection_separate_from_goal_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    goal = "Inspect the project, then create a model"
    base = {"goal": goal, "requires_state_change": True, "requires_verification": False}
    scenario = RunScenario(
        workspace_path=tmp_path, user_content=goal,
        model_rounds=[
            _tool_round("declare", "runtime.update_task", **base, plan=["Inspect project", "Create model"]),
            _tool_round("read", "filesystem.read_file", path="README.md"),
            _tool_round("progress", "runtime.update_task", **base,
                        completion={"goal_closed": False, "remaining_work": ["Create model"]},
                        step_updates=[{"index": 0, "status": "completed", "tool_task_ids": ["observed-read"]}]),
            [{"message": "Inspected the project; the model has not been created."}, {"finish_reason": "stop"}],
        ],
        tool_results=[{"tool": "filesystem.read_file", "task_id": "observed-read", "status": "success", "output": {"content": "project"}}],
    )
    result = await scenario.run(monkeypatch)
    assert result.run_result["goal_status"] == "incomplete"
    assert result.run_result["status"] != "success"
    assert len(result.tool_calls) == 1
    plan = result.assistant.metadata["execution_plan"]
    assert plan["steps"][0]["source"] == "model_declared"
    assert plan["steps"][0]["status"] == "completed"
    assert plan["steps"][1]["status"] == "pending"
    assert result.synthesis_calls == []


@pytest.mark.asyncio
async def test_reasoning_and_literal_examples_never_become_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    example = '<toolcall>{"name":"filesystem.write_file","arguments":{"path":"example.txt","content":"example"}}</toolcall>'
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Explain tool calling syntax",
        task_intent="answer_only", requires_write=False, requires_verification=False,
        model_rounds=[[{"reasoning": example, "message": "Example only: " + example}, {"finish_reason": "stop"}]],
        tool_results=[],
    )
    result = await scenario.run(monkeypatch)
    assert result.tool_calls == []
    assert len(result.execution_model_calls) == 1
    assert result.assistant.content == "Example only: " + example
    assert result.synthesis_calls == []


@pytest.mark.asyncio
async def test_native_completion_closes_verified_goal_without_final_text_header(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = str(tmp_path / "output.txt")
    contract = {"goal": "Create and verify output", "requires_state_change": True,
                "requires_write": True, "requires_verification": True,
                "deliverables": [{"kind": "file", "path_hint": target}]}
    declaration = _tool_round("declare", "runtime.update_task", **contract)
    write = _tool_round("write", "filesystem.write_file", path=target, content="done")
    write[0]["tool_calls"][0]["index"] = 1
    declaration[0]["tool_calls"].extend(write[0]["tool_calls"])
    scenario = RunScenario(
        workspace_path=tmp_path, user_content=contract["goal"],
        model_rounds=[
            declaration,
            _tool_round("verify", "shell.run_command", command="verify output.txt"),
            _tool_round("close", "runtime.update_task", completion={"goal_closed": True}),
            [{"message": "Created output and verified it."}, {"finish_reason": "stop"}],
        ],
        tool_results=[
            {"tool": "filesystem.write_file", "task_id": "write-task", "status": "success", "output": {"path": target}},
            {"tool": "shell.run_command", "task_id": "verify-task", "status": "success", "output": {"exit_code": 0, "stdout": "ok"}},
        ],
    )
    result = await scenario.run(monkeypatch)
    assert result.run_result["status"] == "success"
    assert result.run_result["execution_status"] == "completed"
    assert result.run_result["goal_status"] == "complete"
    assert result.run_result["verification_status"] == "satisfied"
    assert result.assistant.content.startswith("Created output and verified it.")
    assert len(result.tool_calls) == 2
    assert result.synthesis_calls == []


@pytest.mark.asyncio
async def test_missing_native_payload_returns_protocol_facts_and_model_can_choose_a_new_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Inspect the project",
        task_intent="answer_only", requires_write=False, requires_verification=False,
        model_rounds=[
            [{"finish_reason": "tool_calls"}],
            _tool_round("read-1", "filesystem.read_file", path="README.md"),
            _final_round("Read the project description."),
        ],
        tool_results=[{"tool": "filesystem.read_file", "status": "success", "output": {"content": "project"}}],
    )

    result = await scenario.run(monkeypatch)

    assert len(result.execution_model_calls) == 3
    assert len(result.tool_calls) == 1
    assert result.run_result["execution_status"] == "completed"
    assert result.run_result["goal_status"] == "unknown"
    assert result.assistant.metadata["model_protocol_errors"][0]["code"] == "missing_tool_call_payload"
    assert any('"executed_tool_calls": 0' in str(m.get("content"))
               for m in result.execution_model_calls[1]["messages"])
    assert not any('"executed_tool_calls": 0' in str(m.get("content"))
                   for m in result.execution_model_calls[2]["messages"])


@pytest.mark.asyncio
async def test_invalid_native_batch_never_executes_subset_and_model_decides_when_to_end(monkeypatch, tmp_path):
    invalid_round = _tool_round("read-1", "filesystem.read_file", path="README.md")
    invalid_round.insert(1, {"tool_calls": [{"index": -1, "function": {"name": "filesystem__write_file", "arguments": "{}"}}]})
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Inspect the project", tool_results=[],
        task_intent="answer_only", requires_write=False, requires_verification=False,
        model_rounds=[invalid_round, invalid_round, [{"message": "两次调用均未执行。"}, {"finish_reason": "stop"}]],
    )
    result = await scenario.run(monkeypatch)
    assert result.tool_calls == []
    assert len(result.execution_model_calls) == 3
    assert result.run_result["execution_status"] == "completed"
    assert [e["code"] for e in result.assistant.metadata["model_protocol_errors"]] == ["invalid_tool_call_index"] * 2
    assert len([e for e in result.events if e["event"] == "model_round"]) == 3


@pytest.mark.asyncio
async def test_repeated_protocol_errors_do_not_force_a_provider_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Create a model",
        task_intent="answer_only", requires_write=False, requires_verification=False,
        model_rounds=[
            _tool_round("read-1", "filesystem.read_file", path="README.md"),
            [{"message": "Preparing the model."}, {"finish_reason": "tool_calls"}],
            [{"finish_reason": "tool_calls"}],
            [{"message": "未执行模型创建操作。"}, {"finish_reason": "stop"}],
        ],
        tool_results=[{"tool": "filesystem.read_file", "status": "success", "output": {"content": "project"}}],
    )

    result = await scenario.run(monkeypatch)

    assert len(result.execution_model_calls) == 4
    assert len(result.tool_calls) == 1
    assert result.run_result["execution_status"] == "completed"
    assert result.run_result["counts"]["deliverable_successes"] == 0
    assert "model_provider_error" not in result.run_result["risks"]
    assert len(result.assistant.metadata["model_protocol_errors"]) == 2
    assert any(e.get("event") == "error" and e.get("protocol_error") == "missing_tool_call_payload"
               for e in result.events)


@pytest.mark.asyncio
async def test_guidance_preserves_declared_task_and_plan_without_another_semantic_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = tmp_path / "output.txt"
    goal = "Create output.txt and verify it."
    guidance = "The application is already open. Are you calling it?"
    scenario = RunScenario(
        workspace_path=tmp_path, user_content=goal,
        task_intent="answer_only", requires_write=False, planning_policy="auto",
        guidance_on_round={2: guidance},
        model_rounds=[
            _tool_round("declare-1", "runtime.update_task", goal=goal, intent="write_required",
                        requires_write=True, requires_state_change=True, requires_verification=True,
                        plan=["Create output", "Verify output"]),
            [{"message": "Preparing the operation."}, {"finish_reason": "stop"}],
            _tool_round("write-1", "filesystem.write_file", path=str(target), content="done"),
            _tool_round("verify-1", "shell.run_command", command="verify output.txt"),
            _final_round("Created output.txt and verified it."),
        ],
        tool_results=[
            {"tool": "filesystem.write_file", "status": "success", "output": {"path": str(target)}},
            {"tool": "shell.run_command", "status": "success", "output": {"exit_code": 0, "stdout": "ok"}},
        ],
    )

    result = await scenario.run(monkeypatch)

    assert result.task_contract_calls == 0
    assert result.run_result["status"] == "success"
    assert result.assistant.metadata["task_contract"]["goal"] == goal
    assert result.assistant.metadata["task_contract"]["source"] == "model_execution"
    assert [call["tool"] for call in result.tool_calls] == ["filesystem.write_file", "shell.run_command"]
    assert len([e for e in result.events if e["event"] == "task_contract"]) == 2
    assert any(m == {"role": "user", "content": guidance} for m in result.execution_model_calls[2]["messages"])
    assert not any("interrupted" in str(e) for e in result.events if e["event"] == "plan")
    assert not any(e.get("status") == "task_contract_deciding" for e in result.events)


@pytest.mark.asyncio
async def test_confirmation_keeps_user_request_and_answer_only_assistant_promise_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    original = "Create a model in the connected application."
    promise = "Connected. Confirm and I will create the model."
    scenario = RunScenario(
        workspace_path=tmp_path, user_content="Confirmed", task_intent="answer_only",
        requires_write=False, requires_verification=False,
        prior_messages=[
            ScenarioMessage("user", original),
            ScenarioMessage("user", "The application is open. Are you calling it?", {"guidance": True, "during_run": True}),
            ScenarioMessage("assistant", promise, {"task_contract": {"goal": "Answer connection status", "intent": "answer_only"}}),
        ],
        model_rounds=[_final_round("The current request continues the model creation task.", goal_closed=False)],
        tool_results=[],
    )

    result = await scenario.run(monkeypatch)

    messages = result.execution_model_calls[0]["messages"]
    assert {"role": "user", "content": original} in messages
    assert {"role": "assistant", "content": promise} in messages
    assert {"role": "user", "content": "Confirmed"} in messages
    assert result.task_contract_calls == 0
    assert result.run_result["status"] != "success"


@pytest.mark.asyncio
async def test_real_run_pipeline_reaches_verified_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "output.txt"
    write_round = _tool_round("write-1", "filesystem.write_file", path=str(target), content="done")
    write_round[0]["tool_calls"][0]["index"] = 1
    write_round[0]["tool_calls"].insert(0, _tool_round(
        "declare-1", "runtime.update_task", goal="Create output.txt and verify it.",
        intent="write_required", requires_write=True, requires_state_change=True,
        requires_verification=True, deliverables=[{"kind": "file", "path_hint": str(target)}],
    )[0]["tool_calls"][0])
    scenario = RunScenario(
        workspace_path=tmp_path,
        user_content="Create output.txt and verify it.",
        model_rounds=[
            write_round,
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
    decisions = [
        event["decision"]
        for event in result.events
        if event.get("event") == "completion_decision"
    ]
    assert decisions == []
    assert not any(
        event.get("event") == "status" and event.get("status") == "completion_review"
        for event in result.events
    )
    assert all(
        sum(
            "Review fresh runtime evidence" in str(message.get("content") or "")
            for message in call["messages"]
        ) == 0
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
async def test_real_run_pipeline_audits_repeated_failure_without_injecting_system_strategy(
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

    for call in result.execution_model_calls:
        assert all(
            "The same route has repeated without progress" not in str(message.get("content") or "")
            for message in call["messages"]
        )
    assert result.assistant.metadata["execution_convergence"]["route_attempt_count"] == 2
    assert any(event.get("status") == "repeated_route_observed" for event in result.events)
    assert result.assistant.content.startswith("Changed route and created output.txt.")
