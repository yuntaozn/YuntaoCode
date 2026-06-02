import json

from runtime.run_store import RunStore


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
