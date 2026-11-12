from __future__ import annotations

import pytest

from runtime.agent_strategy.plan_tracker import create_model_plan, apply_model_plan_updates


def test_model_plan_updates_validate_evidence_atomically():
    plan = {"steps": [{"title": "Create model", "status": "pending"}]}
    events = [{"task_id": "tool-1", "status": "success"}]
    updated = apply_model_plan_updates(plan, [{"index": 0, "status": "completed", "tool_task_ids": ["tool-1"]}], events)
    assert updated["steps"][0]["status"] == "completed"
    assert updated["steps"][0]["source"] == "model_declared"
    assert updated["steps"][0]["evidence_status"] == "referenced"
    assert plan["steps"][0]["status"] == "pending"
    for update in [
        {"index": 0, "status": "completed", "tool_task_ids": ["invented"]},
        {"index": 0, "status": []},
        {"index": 9, "status": "completed"},
    ]:
        with pytest.raises(ValueError):
            apply_model_plan_updates(plan, [update], events)
    with pytest.raises(ValueError):
        apply_model_plan_updates(plan, [{"index": 0, "status": "completed", "tool_task_ids": ["failed"]}], [{"task_id": "failed", "status": "failure"}])


def test_model_plan_is_optional_and_has_no_runtime_generated_stages():
    assert create_model_plan("goal", []) is None
    plan = create_model_plan("goal", ["Inspect", "Export"])
    assert [step["title"] for step in plan["steps"]] == ["Inspect", "Export"]
    assert plan["source"] == "model_declared"
    assert all(step["status"] == "pending" and "tool_hint" not in step for step in plan["steps"])
