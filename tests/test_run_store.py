import json
import sqlite3
import pytest

from runtime.run_store import RunStore
from runtime.run_events import RunEventHub
from runtime.product_task_store import ProductTaskStore


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("status,task_state", [("success", "completed"), ("failure", "failed"), ("partial", "paused"), ("stopped", "paused"), ("cancelled", "cancelled")])
def test_finalized_run_keeps_late_evidence_without_reopening_or_overwriting_result(tmp_path, backend, status, task_state):
    store = RunStore(tmp_path / "runs.json") if backend == "json" else RunStore.sqlite(tmp_path / "runs.db")
    tasks = ProductTaskStore(tmp_path / "tasks.db")
    task = tasks.create(goal="Model", conversation_id="conv", workspace_id="workspace")
    run = store.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Model", task_id=task.id)
    tasks.attach_run(task.id, run.id)
    hub = RunEventHub(store, product_tasks=tasks)
    hub.emit(run.id, {"event": "result", "result": {"status": status, "goal_status": "complete"}})
    hub.emit(run.id, {"event": "done", "run_status": status})
    before = store.get(run.id)
    queue = hub.subscribe(run.id)
    for late in [
        {"event": "tool", "tool": "filesystem.read_file", "status": "failure", "output": {"diagnostic": "late failure"}},
        {"event": "status", "status": "resumed"},
        {"event": "confirm", "message": "late confirmation"},
        {"event": "error", "error": "late error"},
        {"event": "result", "result": {"status": "success", "goal_status": "incomplete"}},
        {"event": "task_contract", "contract": {"goal": "late replacement"}},
        {"event": "done", "run_status": "success"},
    ]:
        live = hub.emit(run.id, late)
        assert live["event"] == "late_event"
        assert live["original_event"]["event"] == late["event"]
        assert queue.get_nowait()["event"] == "late_event"
    persisted = store.get(run.id)
    assert (persisted.status, persisted.stage, persisted.message) == (before.status, "done", before.message)
    assert [e["result"] for e in persisted.events if e["event"] == "result"] == [{"status": status, "goal_status": "complete"}]
    assert tasks.get(task.id).state == task_state
    assert "model_understanding" not in tasks.get(task.id).metadata
    hub.unsubscribe(run.id, queue)
    store.close()
    tasks.close()


def test_result_publication_seals_execution_but_allows_checkpoint_and_done(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    run = store.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Model")
    store.record_event(run.id, {"event": "result", "result": {"status": "success"}})
    late = store.record_event(run.id, {"event": "tool", "status": "failure"})
    assert (late.status, late.stage) == ("success", "result")
    assert late.events[-1]["event"] == "late_event"
    store.record_event(run.id, {"event": "checkpoint", "checkpoint": {"id": "checkpoint-1"}})
    done = store.record_event(run.id, {"event": "done", "run_status": "success"})
    assert done.stage == "done"
    assert any(e["event"] == "checkpoint" for e in done.events)
    store.close()


def test_user_stop_cannot_be_revived_by_late_execution_or_finalizer(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    run = store.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Model")
    store.record_event(run.id, {"event": "status", "status": "stopped"})
    for event in [{"event": "tool", "status": "failure"}, {"event": "status", "status": "resumed"}]:
        assert store.record_event(run.id, event).status == "stopped"
    store.record_event(run.id, {"event": "result", "result": {"status": "success"}})
    assert store.record_event(run.id, {"event": "done", "run_status": "success"}).status == "stopped"
    store.close()


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("result_status", ["success", "partial", "no_tool_activity"])
def test_result_seal_survives_event_retention_and_checkpoint(tmp_path, backend, result_status):
    store = RunStore(tmp_path / "runs.json", keep_events=3) if backend == "json" else RunStore.sqlite(tmp_path / "runs.db", keep_events=3)
    run = store.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Inspect")
    store.record_event(run.id, {"event": "result", "result": {"status": result_status}})
    for _ in range(4):
        store.record_event(run.id, {"event": "model_round"})
    store.record_event(run.id, {"event": "checkpoint", "checkpoint": {"id": "checkpoint"}})
    before = store.get(run.id)
    assert not any(e["event"] == "result" for e in before.events)
    assert before.stage == "result"
    late = store.record_event(run.id, {"event": "tool", "tool": "read", "status": "failure"})
    assert late.events[-1]["event"] == "late_event"
    assert (late.stage, late.status) == (before.stage, before.status)
    done = store.record_event(run.id, {"event": "done", "run_status": "success" if result_status == "no_tool_activity" else result_status})
    assert done.stage == "done"
    store.close()


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_user_stop_survives_event_retention(tmp_path, backend):
    store = RunStore(tmp_path / "runs.json", keep_events=2) if backend == "json" else RunStore.sqlite(tmp_path / "runs.db", keep_events=2)
    run = store.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Stop")
    store.record_event(run.id, {"event": "status", "status": "stopped"})
    for _ in range(3):
        store.record_event(run.id, {"event": "model_round"})
    assert not any(e.get("status") == "stopped" for e in store.get(run.id).events)
    store.record_event(run.id, {"event": "result", "result": {"status": "success"}})
    assert store.record_event(run.id, {"event": "done", "run_status": "success"}).status == "stopped"
    store.close()


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("status", ["success", "partial", "stopped"])
def test_terminal_state_survives_restart_after_source_events_are_pruned(tmp_path, backend, status):
    path = tmp_path / ("runs.json" if backend == "json" else "runs.db")
    factory = RunStore if backend == "json" else RunStore.sqlite
    store = factory(path, keep_events=2)
    run = store.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Inspect")
    if status == "stopped":
        store.record_event(run.id, {"event": "status", "status": "stopped"})
    else:
        store.record_event(run.id, {"event": "result", "result": {"status": status}})
    for _ in range(3):
        store.record_event(run.id, {"event": "model_round"})
    store.close()
    reopened = factory(path, keep_events=2)
    before = reopened.get(run.id)
    late = reopened.record_event(run.id, {"event": "tool", "status": "failure"})
    assert late.events[-1]["event"] == "late_event"
    assert (late.status, late.stage) == (before.status, before.stage)
    assert late.status == status
    reopened.close()


def test_checkpoint_before_result_does_not_seal_an_active_run(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    run = store.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Inspect")
    store.record_event(run.id, {"event": "checkpoint", "checkpoint": {"kind": "pause"}})
    active = store.record_event(run.id, {"event": "tool", "status": "success"})
    assert active.events[-1]["event"] == "tool" and active.stage == "tool"
    store.close()


def test_run_store_persists_schema_version_and_record_kind(tmp_path) -> None:
    path = tmp_path / "runs.json"
    store = RunStore(path)

    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "0.1"
    assert data["record_kind"] == "run_store"
    assert data["runs"][0]["schema_version"] == "0.1"
    assert data["runs"][0]["record_kind"] == "run"
    assert data["runs"][0]["id"] == run.id


def test_run_store_records_result_events_as_result_stage(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )

    updated = store.record_event(
        run.id,
        {
            "schema_version": "0.1",
            "event": "result",
            "event_name": "run.result",
            "result": {"kind": "run_result", "status": "partial"},
        },
    )

    assert updated is not None
    assert updated.stage == "result"
    assert updated.message == "result partial"
    assert updated.events[-1]["event_name"] == "run.result"


def test_run_store_keeps_recoverable_model_error_running_until_result(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="write then model fails",
    )

    errored = store.record_event(
        run.id,
        {
            "schema_version": "0.1",
            "event": "error",
            "event_name": "run.failed",
            "error": "HTTP 400",
            "terminal": False,
            "recoverable": True,
        },
    )

    assert errored is not None
    assert errored.status == "running"
    assert errored.stage == "model_error"

    resulted = store.record_event(
        run.id,
        {
            "schema_version": "0.1",
            "event": "result",
            "event_name": "run.result",
            "result": {"kind": "run_result", "status": "partial"},
        },
    )

    assert resulted is not None
    assert resulted.status == "partial"
    assert resulted.stage == "result"


def test_run_store_keeps_waiting_confirmation_until_user_resumes(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )

    waiting = store.record_event(
        run.id,
        {
            "schema_version": "0.1",
            "event": "confirm",
            "event_name": "tool.waiting_confirmation",
            "message": "confirm?",
        },
    )
    assert waiting is not None
    assert waiting.status == "waiting_confirmation"

    still_waiting = store.record_event(
        run.id,
        {
            "schema_version": "0.1",
            "event": "status",
            "event_name": "run.status",
            "status": "thinking",
            "message": "still alive",
        },
    )
    assert still_waiting is not None
    assert still_waiting.status == "waiting_confirmation"

    resumed = store.record_event(
        run.id,
        {
            "schema_version": "0.1",
            "event": "status",
            "event_name": "run.status",
            "status": "resumed",
            "message": "continue",
        },
    )
    assert resumed is not None
    assert resumed.status == "running"


def test_run_store_pause_resists_status_noise_until_resume(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )

    paused = store.record_event(run.id, {
        "event": "status",
        "status": "paused",
        "message": "user paused",
    })
    assert paused is not None
    assert paused.status == "paused"
    assert paused.stage == "paused"

    noisy = store.record_event(run.id, {
        "event": "status",
        "status": "thinking",
        "message": "late heartbeat",
    })
    assert noisy is not None
    assert noisy.status == "paused"
    assert noisy.stage == "paused"
    assert noisy.message == "late heartbeat"

    resumed = store.record_event(run.id, {
        "event": "status",
        "status": "resumed",
        "message": "continue",
    })
    assert resumed is not None
    assert resumed.status == "running"
    assert resumed.stage == "resumed"


def test_run_store_marks_user_stopped_status_as_terminal(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )

    stopped = store.record_event(run.id, {
        "event": "status",
        "status": "stopped",
        "message": "user stopped generation",
    })

    assert stopped is not None
    assert stopped.status == "stopped"
    assert stopped.stage == "stopped"
    assert stopped.message == "user stopped generation"


def test_sqlite_run_store_persists_events_and_supports_indexed_filters(tmp_path) -> None:
    database_path = tmp_path / "runtime.db"
    store = RunStore.sqlite(database_path)
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )
    store.record_event(run.id, {
        "schema_version": "0.1",
        "event": "done",
        "event_name": "run.completed",
        "run_status": "success",
    })
    store.close()

    reopened = RunStore.sqlite(database_path)
    persisted = reopened.get(run.id)
    filtered = reopened.list(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        status="success",
    )

    assert persisted is not None
    assert persisted.events[-1]["event_name"] == "run.completed"
    assert [item.id for item in filtered] == [run.id]
    assert filtered[0].to_public_dict()["event_count"] == 1
    reopened.close()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert "idx_runs_conversation_updated" in indexes
    assert "idx_runs_workspace_updated" in indexes
    assert "idx_runs_status_updated" in indexes
    assert "idx_run_events_run_sequence" in indexes
    assert "idx_runs_task_updated" in indexes


def test_sqlite_run_store_persists_task_and_replay_lineage(tmp_path) -> None:
    database_path = tmp_path / "runtime.db"
    store = RunStore.sqlite(database_path)
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="retry task",
        task_id="task-1",
        parent_run_id="run-parent",
        source_run_id="run-source",
        attempt=3,
        resume_from_checkpoint_id="checkpoint-1",
        status="created",
    )
    store.close()

    reopened = RunStore.sqlite(database_path)
    persisted = reopened.get(run.id)
    assert persisted is not None
    assert persisted.task_id == "task-1"
    assert persisted.parent_run_id == "run-parent"
    assert persisted.source_run_id == "run-source"
    assert persisted.attempt == 3
    assert persisted.resume_from_checkpoint_id == "checkpoint-1"
    assert [item.id for item in reopened.list(task_id="task-1")] == [run.id]
    reopened.close()


def test_sqlite_run_store_imports_legacy_json_once_and_keeps_source(tmp_path) -> None:
    legacy_path = tmp_path / "runs.json"
    legacy_store = RunStore(legacy_path)
    legacy_run = legacy_store.create(
        conversation_id="legacy_conv",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="legacy",
    )
    legacy_store.record_event(legacy_run.id, {
        "event": "done",
        "run_status": "success",
    })
    source_after_first_run = legacy_path.read_text(encoding="utf-8")

    database_path = tmp_path / "runtime.db"
    migrated = RunStore.sqlite(database_path, legacy_store_path=legacy_path)
    assert migrated.get(legacy_run.id) is not None
    sqlite_run = migrated.create(
        conversation_id="sqlite_conv",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="new sqlite run",
    )
    migrated.record_event(sqlite_run.id, {
        "event": "done",
        "run_status": "success",
    })
    migrated.close()
    assert legacy_path.read_text(encoding="utf-8") == source_after_first_run

    extra_legacy_run = legacy_store.create(
        conversation_id="legacy_conv",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="added after import",
    )
    reopened = RunStore.sqlite(database_path, legacy_store_path=legacy_path)

    assert reopened.get(legacy_run.id) is not None
    assert reopened.get(extra_legacy_run.id) is None
    reopened.close()


def test_sqlite_run_store_applies_run_and_event_retention(tmp_path) -> None:
    store = RunStore.sqlite(tmp_path / "runtime.db", keep_runs=2, keep_events=2)
    first = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="first",
    )
    for index in range(3):
        store.record_event(first.id, {
            "event": "status",
            "status": f"stage_{index}",
            "message": str(index),
        })
    retained_first = store.get(first.id)
    assert retained_first is not None
    assert [event["message"] for event in retained_first.events] == ["1", "2"]

    second = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="second",
    )
    third = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="third",
    )

    assert store.get(first.id) is None
    assert {item.id for item in store.list()} == {second.id, third.id}
    store.close()


def test_sqlite_run_store_startup_recovery_preserves_events(tmp_path) -> None:
    database_path = tmp_path / "runtime.db"
    store = RunStore.sqlite(database_path)
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )
    store.record_event(run.id, {
        "event": "status",
        "status": "thinking",
        "message": "working",
    })
    store.close()

    recovered_store = RunStore.sqlite(database_path)
    recovered = recovered_store.get(run.id)

    assert recovered is not None
    assert recovered.status == "stopped"
    assert recovered.stage == "interrupted"
    assert recovered.events[-1]["message"] == "working"
    recovered_store.close()


def test_sqlite_run_store_startup_recovery_stops_paused_runs(tmp_path) -> None:
    database_path = tmp_path / "runtime.db"
    store = RunStore.sqlite(database_path)
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="hello",
    )
    store.record_event(run.id, {
        "event": "status",
        "status": "paused",
        "message": "paused by user",
    })
    store.close()

    recovered_store = RunStore.sqlite(database_path)
    recovered = recovered_store.get(run.id)

    assert recovered is not None
    assert recovered.status == "stopped"
    assert recovered.stage == "interrupted"
    recovered_store.close()


def test_sqlite_run_store_rejects_newer_database_schema(tmp_path) -> None:
    database_path = tmp_path / "runtime.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 999")

    try:
        RunStore.sqlite(database_path)
    except RuntimeError as exc:
        assert "newer than supported" in str(exc)
    else:
        raise AssertionError("newer operational schema should be rejected")
