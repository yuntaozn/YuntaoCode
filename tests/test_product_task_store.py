from runtime.product_task_store import ProductTaskStore
from runtime.run_store import RunStore
from runtime.run_events import RunEventHub
import pytest


def test_task_store_enforces_terminal_transitions_and_retry_identity(tmp_path):
    store = ProductTaskStore(tmp_path / "tasks.db")
    task = store.create(goal="Create model")
    store.attach_run(task.id, "run-1")
    store.update_state(task.id, "completed")
    with pytest.raises(ValueError):
        store.update_state(task.id, "running")
    with pytest.raises(ValueError):
        store.attach_run(task.id, "run-2")
    with pytest.raises(ValueError):
        store.update_state(task.id, "unknown-state")
    store.close()


def test_retry_uses_resuming_and_ignores_previous_run_events(tmp_path):
    from types import SimpleNamespace
    store = ProductTaskStore(tmp_path / "tasks.db")
    task = store.create(goal="Create model")
    store.attach_run(task.id, "run-1")
    store.update_state(task.id, "paused")
    prepared = store.attach_run(task.id, "run-2", state="created")
    assert prepared.state == "resuming"
    assert prepared.run_count == 2
    store.sync_from_run(SimpleNamespace(id="run-1", task_id=task.id, status="success", stage="done", events=[]))
    assert store.get(task.id).current_run_id == "run-2"
    assert store.get(task.id).state == "resuming"
    store.sync_from_run(SimpleNamespace(id="run-2", task_id=task.id, status="running", stage="resumed", events=[]))
    assert store.get(task.id).state == "running"
    store.close()


@pytest.mark.parametrize("status", ["success", "partial"])
def test_live_event_projection_does_not_require_optional_goal_declaration(tmp_path, status):
    tasks = ProductTaskStore(tmp_path / "tasks.db")
    runs = RunStore(store_path=tmp_path / "runs.json")
    task = tasks.create(goal="Original user request")
    run = runs.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="again", task_id=task.id)
    tasks.attach_run(task.id, run.id)
    hub = RunEventHub(runs, product_tasks=tasks)
    hub.emit(run.id, {"event": "task_contract", "contract": {"source": "model_execution", "goal": "Model interpretation"}})
    hub.emit(run.id, {"event": "error", "error": "transport interrupted", "terminal": True})
    assert tasks.get(task.id).state == "running"
    hub.emit(run.id, {"event": "result", "result": {"status": status, "goal_status": "unknown"}})
    hub.emit(run.id, {"event": "done", "run_status": status})
    assert tasks.get(task.id).state == ("completed" if status == "success" else "paused")
    assert tasks.get(task.id).metadata["run_outcome"]["goal_status"] == "unknown"
    assert tasks.get(task.id).goal == "Original user request"
    assert tasks.get(task.id).metadata["model_understanding"]["contract"]["goal"] == "Model interpretation"
    runs.close()
    tasks.close()


@pytest.mark.parametrize("goal_status,expected_state", [("unknown", "completed"), ("complete", "completed"), ("incomplete", "paused")])
def test_explicit_goal_outcome_stays_stable_when_result_event_is_pruned(tmp_path, goal_status, expected_state):
    tasks = ProductTaskStore(tmp_path / "tasks.db")
    runs = RunStore(tmp_path / "runs.json", keep_events=2)
    task = tasks.create(goal="Inspect")
    run = runs.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Inspect", task_id=task.id)
    tasks.attach_run(task.id, run.id)
    hub = RunEventHub(runs, product_tasks=tasks)
    hub.emit(run.id, {"event": "result", "result": {"status": "success", "goal_status": goal_status}})
    for _ in range(3):
        hub.emit(run.id, {"event": "model_round"})
    hub.emit(run.id, {"event": "done", "run_status": "success"})
    assert tasks.get(task.id).state == expected_state
    assert tasks.get(task.id).metadata["run_outcome"]["goal_status"] == goal_status
    runs.close()
    tasks.close()


def test_previous_incomplete_outcome_does_not_pause_successful_retry(tmp_path):
    tasks = ProductTaskStore(tmp_path / "tasks.db")
    runs = RunStore(tmp_path / "runs.json")
    task = tasks.create(goal="Inspect")
    hub = RunEventHub(runs, product_tasks=tasks)
    first = runs.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Inspect", task_id=task.id)
    tasks.attach_run(task.id, first.id)
    hub.emit(first.id, {"event": "result", "result": {"status": "success", "goal_status": "incomplete"}})
    hub.emit(first.id, {"event": "done", "run_status": "success"})
    assert tasks.get(task.id).state == "paused"
    retry = runs.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Retry", task_id=task.id)
    tasks.attach_run(task.id, retry.id)
    # 当前尝试没有声明未完成，旧尝试的缓存不得代替当前结果。
    hub.emit(retry.id, {"event": "done", "run_status": "success"})
    assert tasks.get(task.id).state == "completed"
    runs.close()
    tasks.close()


def test_completed_task_replay_creates_new_task_without_reopening_source(tmp_path):
    from types import SimpleNamespace
    from runtime.api.runs import RunActionHandler
    tasks = ProductTaskStore(tmp_path / "tasks.db")
    runs = RunStore(store_path=tmp_path / "runs.json")
    task = tasks.create(goal="Create model", conversation_id="conv", workspace_id="workspace")
    run = runs.create(conversation_id="conv", workspace_id="workspace", mode="terminal", user_content="Create model", task_id=task.id)
    tasks.attach_run(task.id, run.id)
    tasks.update_state(task.id, "completed")
    runs.record_event(run.id, {"event": "done", "run_status": "success"})
    run = runs.get(run.id)
    handler = object.__new__(RunActionHandler)
    handler.runtime = SimpleNamespace(product_tasks=tasks, runs=runs)
    replay = handler._prepare_new_run(run, recovery=False)
    prepared = runs.get(replay["prepared_run"]["id"])
    assert prepared.task_id != task.id
    assert tasks.get(task.id).state == "completed"
    assert tasks.get(prepared.task_id).metadata["source_task_id"] == task.id
    assert prepared.source_run_id == run.id
    tasks.close()
    runs.close()


def test_product_task_store_persists_task_and_run_relationship(tmp_path) -> None:
    database_path = tmp_path / "runtime.db"
    store = ProductTaskStore(database_path)
    task = store.create(
        goal="Build a model viewer",
        conversation_id="conv-1",
        workspace_id="workspace-1",
        kind="conversation_task",
    )

    running = store.attach_run(task.id, "run-1")

    assert running.state == "running"
    assert running.current_run_id == "run-1"
    assert running.run_count == 1
    store.close()

    reopened = ProductTaskStore(database_path)
    persisted = reopened.get(task.id)
    assert persisted is not None
    assert persisted.goal == "Build a model viewer"
    assert persisted.current_run_id == "run-1"
    reopened.close()


def test_product_task_store_persists_snapshot_and_checkpoint(tmp_path) -> None:
    store = ProductTaskStore(tmp_path / "runtime.db")
    task = store.create(goal="Translate document")
    snapshot = store.create_context_snapshot(
        task_id=task.id,
        run_id="run-1",
        phase="recovery",
        snapshot={
            "schema_version": "context_snapshot.v1",
            "task_id": task.id,
            "phase": "recovery",
            "unresolved": ["translation incomplete"],
        },
    )
    checkpoint = store.create_checkpoint(
        task_id=task.id,
        run_id="run-1",
        kind="run_result",
        state="partial",
        context_snapshot_id=snapshot["id"],
        data={"completed": 20},
    )

    assert store.get_checkpoint(checkpoint["id"])["data"] == {"completed": 20}
    assert store.get_context_snapshot(snapshot["id"])["snapshot"]["unresolved"] == [
        "translation incomplete"
    ]
    assert store.list_checkpoints(task_id=task.id)[0]["run_id"] == "run-1"
    store.close()


def test_product_task_store_marks_interrupted_tasks_paused(tmp_path) -> None:
    database_path = tmp_path / "runtime.db"
    store = ProductTaskStore(database_path)
    task = store.create(goal="Long task")
    store.attach_run(task.id, "run-1")
    store.close()

    recovered = ProductTaskStore(database_path)
    assert recovered.get(task.id).state == "paused"
    recovered.close()
