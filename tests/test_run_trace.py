from runtime.run_store import RunStore
from runtime.run_trace import build_run_trace_summary


def test_run_trace_summary_normalizes_legacy_events(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="Create viewer.html",
    )
    store.record_event(run.id, {
        "event": "capability_snapshot",
        "snapshot": {"available_tool_ids": ["filesystem.write_file"]},
        "preflight": {"ok": True, "target_capability_ids": ["code.text_write"]},
    })
    store.record_event(run.id, {
        "event": "tool",
        "status": "success",
        "tool": "filesystem.write_file",
        "input": {"path": "viewer.html"},
        "output": {"content": "full file content must not enter trace"},
    })
    store.record_event(run.id, {
        "event": "tool",
        "status": "failure",
        "tool": "node.check",
        "error": "syntax error",
    })
    store.record_event(run.id, {
        "event": "result",
        "result": {"kind": "run_result", "status": "partial"},
    })

    current = store.get(run.id)
    summary = build_run_trace_summary(current)

    assert summary["schema_version"] == "run_trace_summary.v1"
    assert summary["event_count"] == 4
    assert summary["event_name_counts"]["capability.snapshot"] == 1
    assert summary["event_name_counts"]["tool.completed"] == 1
    assert summary["event_name_counts"]["tool.failed"] == 1
    assert summary["event_family_counts"]["tool"] == 2
    assert summary["failed_tool_count"] == 1
    assert summary["result_status"] == "partial"
    assert summary["latest_event_name"] == "run.result"
    assert "full file content" not in str(summary["timeline"])

    without_timeline = build_run_trace_summary(current, timeline_limit=0)
    assert without_timeline["event_count"] == 4
    assert without_timeline["timeline"] == []
