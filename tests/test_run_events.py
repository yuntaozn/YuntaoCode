from runtime.run_events import canonical_run_event_name, compact_run_event


def test_compact_tool_event_includes_schema_and_canonical_name() -> None:
    event = compact_run_event({
        "event": "tool",
        "status": "success",
        "tool": "filesystem.scan_folder",
        "name": "Scan Folder",
        "input": {"path": "."},
        "output": {"count": 3},
    })

    assert event["schema_version"] == "0.1"
    assert event["event"] == "tool"
    assert event["event_name"] == "tool.completed"
    assert event["tool"] == "filesystem.scan_folder"


def test_result_event_is_recorded_as_runtime_result() -> None:
    event = compact_run_event({
        "event": "result",
        "result": {"kind": "run_result", "status": "partial"},
    })

    assert event == {
        "schema_version": "0.1",
        "event": "result",
        "event_name": "run.result",
        "result": {"kind": "run_result", "status": "partial"},
    }


def test_canonical_run_event_name_maps_runtime_events() -> None:
    assert canonical_run_event_name({"event": "status", "status": "thinking"}) == "run.status"
    assert canonical_run_event_name({"event": "tool", "status": "running"}) == "tool.started"
    assert canonical_run_event_name({"event": "tool", "status": "partial"}) == "tool.partial"
    assert canonical_run_event_name({"event": "tool", "status": "failure"}) == "tool.failed"
    assert canonical_run_event_name({"event": "done"}) == "run.completed"
