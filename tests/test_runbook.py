from runtime.run_store import RunStore
from runtime.runbook import build_replay_request, build_runbook


def test_build_runbook_summarizes_trace_and_result(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="Create viewer.html",
    )
    store.record_event(run.id, {
        "event": "task_contract",
        "contract": {
            "goal": "Create viewer.html",
            "requires_write": True,
            "deliverables": [{"kind": "file", "path_hint": "viewer.html"}],
        },
    })
    store.record_event(run.id, {
        "event": "capability_snapshot",
        "snapshot": {"available_tool_ids": ["filesystem.write_file"], "unavailable_tool_ids": []},
        "preflight": {"ok": True, "target_capability_ids": ["filesystem"]},
    })
    store.record_event(run.id, {
        "event": "plan",
        "plan": {
            "title": "Create file",
            "state": "running",
            "steps": [{"title": "Write file", "status": "completed", "tool_hint": "filesystem.write_file"}],
        },
    })
    store.record_event(run.id, {
        "event": "tool",
        "tool": "filesystem.write_file",
        "status": "success",
        "input": {"path": "viewer.html"},
        "output": {"path": "viewer.html"},
    })
    store.record_event(run.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "partial",
            "risks": ["write_not_verified"],
        },
    })

    current = store.get(run.id)
    runbook = build_runbook(current)

    assert runbook["schema_version"] == "runbook.v1"
    assert runbook["run"]["goal"] == "Create viewer.html"
    assert runbook["task_contract"]["requires_write"] is True
    assert runbook["capability_snapshot"]["ok"] is True
    assert runbook["plan"]["step_count"] == 1
    assert runbook["tool_steps"][0]["tool"] == "filesystem.write_file"
    assert runbook["risks"] == ["write_not_verified"]
    assert runbook["replay"]["kind"] == "replay_request"
    assert runbook["replay"]["boundary"] == "manual_start_required"


def test_build_replay_request_does_not_execute_or_require_events(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="Analyze only",
    )

    replay = build_replay_request(run)

    assert replay["schema_version"] == "replay_request.v1"
    assert replay["source_run_id"] == run.id
    assert replay["goal"] == "Analyze only"
    assert replay["replayable"] is False
    assert replay["boundary"] == "manual_start_required"
    assert replay["runbook"]["run"]["id"] == run.id
