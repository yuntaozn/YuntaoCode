from __future__ import annotations

from datetime import datetime, timezone

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


def test_automation_store_initializes_next_run_for_scheduled_trigger(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    created = store.create({
        "name": "Interval schedule",
        "state": "active",
        "trigger": {"kind": "interval", "interval_seconds": 300},
        "task_template": {"goal": "Check status"},
    })

    assert created.next_run_at


def test_automation_store_advances_interval_after_prepared_run(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    created = store.create({
        "name": "Interval schedule",
        "state": "active",
        "next_run_at": "2026-07-19T08:00:00Z",
        "trigger": {"kind": "interval", "interval_seconds": 300},
        "task_template": {"goal": "Check status"},
    })

    updated = store.record_prepared_run(
        created.id,
        "run-1",
        now=datetime(2026, 7, 19, 8, 1, tzinfo=timezone.utc),
    )

    assert updated.last_run_id == "run-1"
    assert updated.next_run_at == "2026-07-19T08:06:00Z"


def test_automation_store_clears_once_after_prepared_run(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    created = store.create({
        "name": "Once schedule",
        "state": "active",
        "next_run_at": "2026-07-19T08:00:00Z",
        "trigger": {"kind": "once", "run_at": "2026-07-19T08:00:00Z"},
        "task_template": {"goal": "Check once"},
    })

    updated = store.record_prepared_run(
        created.id,
        "run-1",
        now=datetime(2026, 7, 19, 8, 1, tzinfo=timezone.utc),
    )

    assert updated.last_run_id == "run-1"
    assert updated.next_run_at == ""


def test_automation_store_validates_goal(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")

    try:
        store.create({"name": "Missing goal"})
    except ValueError as exc:
        assert "goal" in str(exc)
    else:
        raise AssertionError("expected missing goal to fail")
