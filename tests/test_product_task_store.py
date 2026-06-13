from runtime.product_task_store import ProductTaskStore


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
