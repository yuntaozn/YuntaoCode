from __future__ import annotations

import json

import pytest

from runtime.agent_strategy.task_contract import default_task_contract
from runtime.task_state_control import TASK_STATE_TOOL_ID, TaskStateControl


def _contract():
    return default_task_contract(
        task_intent="answer_only", mode="terminal", planning_policy="auto",
        confirmation_policy="conservative", workspace_path="/workspace", access_scope="workspace",
    )


def _call():
    return {"id": "declare-1", "function": {"name": "runtime__update_task"}}


@pytest.mark.asyncio
async def test_task_declaration_records_model_semantics_without_external_success_or_permission_grant():
    updates = []

    async def update(contract, plan, declaration):
        updates.append((contract, plan))

    control = TaskStateControl(_contract(), update)
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {
        "goal": "Create and verify a model", "intent": "write_required",
        "requires_write": False, "requires_state_change": True, "requires_verification": True,
        "capability_ids": ["mcp.blender"], "plan": ["Create model", "Verify model"],
    }, "tool_calls")

    contract, plan = updates[0]
    assert contract["source"] == "model_execution"
    assert contract["requires_state_change"] is True
    assert contract["confirmation_policy"] == "conservative"
    assert contract["access_scope"] == "workspace"
    assert plan == ["Create model", "Verify model"]
    assert json.loads(response["content"])["execution_performed"] is False
    assert "effects" not in json.loads(response["content"])


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {"permissions": {"arbitrary_code": "allow"}},
    {"access_scope": "full_local"},
    {"requires_verification": "false"},
    {"intent": []},
    {"plan": ["step"] * 9},
    {"capability_ids": [123]},
    {"required_verification_modalities": ["visual_typo"]},
    {"required_verification_modalities": ["visual"], "requires_verification": False},
    {"capability_ids": ["x"] * 7},
    {"deliverables": [{"kind": "unknown"}]},
    {"deliverables": [{"kind": "file", "extra": True}]},
    {"deliverables": [{"path_hint": "model.blend"}]},
    {"deliverables": [{"kind": "file", "path_hint": 123}]},
    {"completion": None},
    {"completion": {"goal_closed": True, "verification_limits": ["x" * 501]}},
    {"step_updates": [{"index": True, "status": "completed"}]},
    {"step_updates": [{"index": -1, "status": "completed"}]},
    {"step_updates": [{"index": 0, "status": "unknown"}]},
    {"step_updates": [{"index": 0, "status": "completed", "tool_task_ids": [123]}]},
    {"step_updates": [{"index": 0, "status": "completed", "extra": True}]},
])
async def test_invalid_task_declarations_do_not_modify_run_state(extra):
    updates = []

    async def update(contract, plan, declaration):
        updates.append(contract)

    initial = _contract()
    control = TaskStateControl(initial, update)
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {
        "goal": "Create model", "requires_state_change": True, "requires_verification": True, **extra,
    }, "tool_calls")

    assert json.loads(response["content"])["status"] == "rejected"
    assert updates == []
    assert control.contract == initial


@pytest.mark.asyncio
async def test_valid_verification_requirements_are_preserved():
    updates = []

    async def update(contract, *_args):
        updates.append(contract)

    control = TaskStateControl(_contract(), update)
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {
        "goal": "Verify model", "requires_state_change": True, "requires_verification": True,
        "required_verification_modalities": ["visual", "structural"],
        "deliverables": [{"kind": "file", "path_hint": "model.blend"}],
    }, "tool_calls")
    assert json.loads(response["content"])["status"] == "recorded"
    assert updates[0]["required_verification_modalities"] == ["visual", "structural"]
    assert updates[0]["deliverables"][0]["path_hint"] == "model.blend"
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {
        "goal": "Verify model", "requires_state_change": True, "requires_verification": True,
        "completion": {"goal_closed": False, "remaining_work": ["Verify screenshot"]},
    }, "tool_calls")
    assert json.loads(response["content"])["status"] == "recorded"
    assert updates[-1]["required_verification_modalities"] == ["visual", "structural"]
    assert updates[-1]["deliverables"][0]["path_hint"] == "model.blend"
    assert "deliverables" not in updates[-1]["model_explicit_fields"]


@pytest.mark.asyncio
async def test_truncated_declaration_is_rejected_and_other_tools_are_not_intercepted():
    async def update(contract, plan, declaration):
        raise AssertionError("truncated declarations must not be applied")

    control = TaskStateControl(_contract(), update)
    assert await control.handle_call(_call(), "filesystem.write_file", {}, "tool_calls") is None
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {}, "length")
    assert json.loads(response["content"])["status"] == "rejected"


@pytest.mark.asyncio
async def test_completion_only_update_preserves_task_semantics_and_permissions():
    updates = []

    async def update(contract, plan, declaration):
        updates.append((contract, declaration))

    initial = _contract()
    initial.update(goal="Verify saved model", source="model_execution", requires_verification=True,
                   required_verification_modalities=["structural", "visual"],
                   deliverables=[{"kind": "file", "path_hint": "model.blend"}])
    control = TaskStateControl(initial, update)
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {
        "completion": {"goal_closed": True, "verification_limits": ["visual quality remains subjective"]},
    }, "tool_calls")
    assert json.loads(response["content"])["status"] == "recorded"
    assert updates[0][0] == initial
    assert updates[0][1]["completion"]["goal_closed"] is True


@pytest.mark.asyncio
async def test_empty_update_and_inconsistent_partial_verification_are_atomic():
    async def update(*_args):
        raise AssertionError("invalid updates cannot change state")

    initial = _contract()
    initial.update(requires_verification=True, required_verification_modalities=["visual"])
    control = TaskStateControl(initial, update)
    for arguments in [{}, {"requires_verification": False}]:
        response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, arguments, "tool_calls")
        assert json.loads(response["content"])["status"] == "rejected"
        assert control.contract == initial


@pytest.mark.asyncio
async def test_completion_and_plan_updates_are_declarations_not_tool_effects():
    updates = []

    async def update(contract, plan, declaration):
        updates.append(declaration)

    control = TaskStateControl(_contract(), update)
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {
        "goal": "Inspect project", "requires_state_change": False, "requires_verification": False,
        "completion": {"goal_closed": False, "remaining_work": ["create model"]},
        "step_updates": [{"index": 0, "status": "completed", "tool_task_ids": ["read-1"]}],
    }, "tool_calls")
    assert json.loads(response["content"])["status"] == "recorded"
    assert json.loads(response["content"])["execution_performed"] is False
    assert updates[0]["completion"]["goal_closed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", [{"goal_closed": "true"}, {"goal_closed": True, "remaining_work": "none"}])
async def test_invalid_completion_is_rejected_before_mutating_state(completion):
    async def update(*_args):
        raise AssertionError("invalid declarations must not change state")

    control = TaskStateControl(_contract(), update)
    response = await control.handle_call(_call(), TASK_STATE_TOOL_ID, {
        "goal": "Inspect project", "requires_state_change": False, "requires_verification": False,
        "completion": completion,
    }, "tool_calls")
    assert json.loads(response["content"])["status"] == "rejected"
