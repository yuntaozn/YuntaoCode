from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from runtime.automation_scheduler import AutomationScheduler
from runtime.automation_store import AutomationStore


@dataclass
class _Workspace:
    id: str
    path: str = "D:/workspace"


class _Workspaces:
    def __init__(self) -> None:
        self.items = {"workspace-1": _Workspace(id="workspace-1")}

    def get(self, workspace_id: str):
        return self.items.get(workspace_id)

    def list(self):
        return list(self.items.values())


class _Conversations:
    def __init__(self) -> None:
        self.items = {}

    def get(self, conversation_id: str):
        return self.items.get(conversation_id)

    def create(self, workspace_id: str, *, title: str, mode: str):
        conversation = SimpleNamespace(
            id=f"conversation-{len(self.items) + 1}",
            workspace_id=workspace_id,
            title=title,
            mode=mode,
        )
        self.items[conversation.id] = conversation
        return conversation


class _ProductTasks:
    def __init__(self) -> None:
        self.items = {}
        self.attached = []

    def create(self, **kwargs):
        task = SimpleNamespace(
            id=f"task-{len(self.items) + 1}",
            run_count=0,
            **kwargs,
        )
        self.items[task.id] = task
        return task

    def get(self, task_id: str):
        return self.items.get(task_id)

    def attach_run(self, task_id: str, run_id: str, *, state: str = "running") -> None:
        self.attached.append((task_id, run_id, state))


class _Run:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)

    def to_public_dict(self, include_events: bool = False):
        return dict(self.__dict__)


class _Runs:
    def __init__(self) -> None:
        self.items = []

    def create(self, **kwargs):
        run = _Run(id=f"run-{len(self.items) + 1}", **kwargs)
        self.items.append(run)
        return run

    def list(self):
        return list(self.items)


class _RunEvents:
    def __init__(self) -> None:
        self.events = []

    def emit(self, run_id: str, event):
        self.events.append((run_id, event))


class _Runtime:
    def __init__(self, store: AutomationStore) -> None:
        self.automations = store
        self.workspaces = _Workspaces()
        self.conversations = _Conversations()
        self.product_tasks = _ProductTasks()
        self.runs = _Runs()
        self.run_events = _RunEvents()


@pytest.mark.asyncio
async def test_scheduler_creates_prepared_normal_run_for_due_automation(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    automation = store.create({
        "name": "Scheduled check",
        "state": "active",
        "next_run_at": "2026-07-19T08:00:00Z",
        "trigger": {"kind": "interval", "interval_seconds": 300},
        "task_template": {
            "goal": "Check project status",
            "workspace_id": "workspace-1",
        },
    })
    runtime = _Runtime(store)
    scheduler = AutomationScheduler(runtime, interval_seconds=1)

    results = await scheduler.tick(now=datetime(2026, 7, 19, 8, 1, tzinfo=timezone.utc))

    assert results[0]["status"] == "prepared_run_created"
    assert results[0]["run_id"] == "run-1"
    assert runtime.runs.items[0].status == "created"
    assert runtime.runs.items[0].user_content == "Check project status"
    task = runtime.product_tasks.items["task-1"]
    assert task.metadata["automation_id"] == automation.id
    assert task.metadata["triggered_by"] == "scheduler"
    assert store.get(automation.id).last_run_id == "run-1"  # type: ignore[union-attr]
    assert store.get(automation.id).next_run_at == "2026-07-19T08:06:00Z"  # type: ignore[union-attr]
    assert runtime.run_events.events[0][1]["event"] == "automation"


@pytest.mark.asyncio
async def test_scheduler_skip_if_running_advances_next_run(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    automation = store.create({
        "name": "Skip check",
        "state": "active",
        "concurrency_policy": "skip_if_running",
        "next_run_at": "2026-07-19T08:00:00Z",
        "trigger": {"kind": "interval", "interval_seconds": 300},
        "task_template": {
            "goal": "Check project status",
            "workspace_id": "workspace-1",
        },
    })
    runtime = _Runtime(store)
    task = runtime.product_tasks.create(
        goal="existing",
        conversation_id="conversation-1",
        workspace_id="workspace-1",
        kind="automation_task",
        metadata={"automation_id": automation.id},
    )
    runtime.runs.create(
        conversation_id="conversation-1",
        workspace_id="workspace-1",
        mode="terminal",
        user_content="existing",
        task_id=task.id,
        status="running",
    )
    scheduler = AutomationScheduler(runtime, interval_seconds=1)

    results = await scheduler.tick(now=datetime(2026, 7, 19, 8, 1, tzinfo=timezone.utc))

    assert results[0]["status"] == "skipped_active_run"
    assert store.get(automation.id).next_run_at == "2026-07-19T08:06:00Z"  # type: ignore[union-attr]
    assert len(runtime.runs.items) == 1


@pytest.mark.asyncio
async def test_scheduler_queue_next_keeps_due_time_while_active_run_exists(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.json")
    automation = store.create({
        "name": "Queue check",
        "state": "active",
        "concurrency_policy": "queue_next",
        "next_run_at": "2026-07-19T08:00:00Z",
        "trigger": {"kind": "interval", "interval_seconds": 300},
        "task_template": {
            "goal": "Check project status",
            "workspace_id": "workspace-1",
        },
    })
    runtime = _Runtime(store)
    task = runtime.product_tasks.create(
        goal="existing",
        conversation_id="conversation-1",
        workspace_id="workspace-1",
        kind="automation_task",
        metadata={"automation_id": automation.id},
    )
    runtime.runs.create(
        conversation_id="conversation-1",
        workspace_id="workspace-1",
        mode="terminal",
        user_content="existing",
        task_id=task.id,
        status="paused",
    )
    scheduler = AutomationScheduler(runtime, interval_seconds=1)

    results = await scheduler.tick(now=datetime(2026, 7, 19, 8, 1, tzinfo=timezone.utc))

    assert results[0]["status"] == "queued"
    assert store.get(automation.id).next_run_at == "2026-07-19T08:00:00Z"  # type: ignore[union-attr]
    assert len(runtime.runs.items) == 1
