from __future__ import annotations

from runtime.api.tool_tasks import _tool_task_public_dict
from runtime.task_store import TaskRecord


def test_task_public_dict_normalizes_shell_timeout_error() -> None:
    task = TaskRecord(
        id="task-1",
        tool="shell.run_command",
        input={"command": "python -m http.server 8000", "timeout": 10},
        status="failure",
        output={"exit_code": 1, "timed_out": True},
        error="command exited with code 1",
    )

    data = _tool_task_public_dict(task)

    assert data["error"] == "command timed out after 10s"
