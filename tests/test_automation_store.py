from __future__ import annotations

from runtime.automation_store import AutomationStore


def test_automation_store_persists_task_template_and_trigger(tmp_path) -> None:
    path = tmp_path / "automations.json"
    store = AutomationStore(path)

    created = store.create({
        "name": "Daily review",
        "state": "active",
        "trigger": {"kind": "daily", "time_of_day": "09:30"},
        "task_template": {
            "goal": "Summarize recent failed runs",
            "workspace_id": "workspace-1",
            "model": "model-1",
        },
    })

    reopened = AutomationStore(path)
    loaded = reopened.get(created.id)

    assert loaded is not None
    assert loaded.name == "Daily review"
    assert loaded.trigger.kind == "daily"
    assert loaded.trigger.time_of_day == "09:30"
    assert loaded.task_template.goal == "Summarize recent failed runs"
    assert loaded.task_template.workspace_id == "workspace-1"


def test_automation_store_updates_state_and_run_reference(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    created = store.create({
        "name": "Manual check",
        "trigger": {"kind": "manual"},
        "task_template": {"goal": "Check project status"},
    })

    paused = store.set_state(created.id, "paused")
    recorded = store.record_prepared_run(created.id, "run-1")

    assert paused.state == "paused"
    assert recorded.last_run_id == "run-1"
    assert store.get(created.id).last_run_id == "run-1"  # type: ignore[union-attr]


def test_automation_store_prevents_parallel_by_default(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    created = store.create({
        "name": "No parallel",
        "state": "active",
        "trigger": {"kind": "interval", "interval_seconds": 60},
        "task_template": {"goal": "Check status"},
    })

    assert store.can_trigger(created.id, active_runs=0)
    assert not store.can_trigger(created.id, active_runs=1)


def test_automation_store_validates_goal(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")

    try:
        store.create({"name": "Missing goal"})
    except ValueError as exc:
        assert "goal" in str(exc)
    else:
        raise AssertionError("expected missing goal to fail")
