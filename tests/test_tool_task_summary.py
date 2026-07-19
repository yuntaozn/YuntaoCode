from datetime import datetime, timezone

from runtime.task_store import TaskRecord
from runtime.tool_task_summary import build_tool_task_progress


def test_tool_task_progress_summarizes_live_command_facts() -> None:
    task = TaskRecord(
        id="task-1",
        tool="shell.run_command",
        input={"command": "python -m pip install playwright"},
        status="running",
        created_at="2026-06-02T14:00:00+00:00",
        updated_at="2026-06-02T14:02:00+00:00",
        logs=[
            {
                "time": "2026-06-02T14:00:00+00:00",
                "level": "info",
                "message": "running: python -m pip install playwright",
                "data": {
                    "kind": "command_start",
                    "cwd": "D:/demo",
                    "timeout": 600,
                    "command_role": "dependency_install",
                    "observable": True,
                },
            },
            {
                "time": "2026-06-02T14:01:00+00:00",
                "level": "info",
                "message": "Collecting playwright",
                "data": {
                    "kind": "command_output",
                    "stream": "stdout",
                    "elapsed_seconds": 60.0,
                },
            },
            {
                "time": "2026-06-02T14:02:00+00:00",
                "level": "info",
                "message": "command still running; elapsed 120s; no new output for 60s",
                "data": {
                    "kind": "command_heartbeat",
                    "elapsed_seconds": 120.0,
                    "silent_seconds": 60.0,
                },
            },
        ],
    )

    progress = build_tool_task_progress(
        task,
        now=datetime(2026, 6, 2, 14, 3, 0, tzinfo=timezone.utc),
    )

    assert progress["schema_version"] == "tool_task_progress.v1"
    assert progress["boundary"] == "evidence_only"
    assert progress["elapsed_seconds"] == 180
    assert progress["stale_seconds"] == 60
    assert progress["can_cancel"] is True
    assert progress["command"]["role"] == "dependency_install"
    assert progress["command"]["timeout"] == 600
    assert progress["last_output"]["stream"] == "stdout"
    assert progress["last_heartbeat"]["silent_seconds"] == 60.0
    assert progress["counts"]["output_events"] == 1
    assert progress["flags"]["is_dependency_install"] is True
    assert progress["flags"]["is_stale"] is True


def test_tool_task_progress_is_empty_but_stable_for_minimal_records() -> None:
    task = TaskRecord(
        id="task-2",
        tool="filesystem.read_file",
        input={"path": "README.md"},
        status="success",
        created_at="",
        updated_at="",
    )

    progress = build_tool_task_progress(task)

    assert progress["schema_version"] == "tool_task_progress.v1"
    assert progress["tool"] == "filesystem.read_file"
    assert progress["elapsed_seconds"] is None
    assert progress["can_cancel"] is False
    assert progress["counts"]["logs"] == 0
