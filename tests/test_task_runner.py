import asyncio
from pathlib import Path
from typing import Any

import pytest

from runtime.security import PathGuard
from runtime.task_runner import TaskRunner
from runtime.task_store import TaskStore
from runtime.tool_registry import ToolRegistry, ToolSpec


async def _demo_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    context.log("info", "demo handler ran", {"input": input_data})
    return {"ok": True, "input": input_data}


async def _shell_failure_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    context.log("error", "command finished with exit code 1")
    return {"exit_code": 1, "stdout": "", "stderr": "SyntaxError: invalid syntax"}


async def _partial_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    context.log("warning", "partial output generated")
    return {
        "status": "partial_resumable",
        "partial_resumable": True,
        "stopped_reason": "max_seconds_exceeded:1800",
        "path": str(context.path_guard.resolve("partial.docx")),
    }


def _build_runner(tmp_path: Path, *, settings: Any | None = None) -> TaskRunner:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="demo.write",
            name="Demo Write",
            description="Demo write tool",
            input_schema={"type": "object"},
            requires_confirmation=True,
        ),
        _demo_handler,
    )
    registry.register(
        ToolSpec(
            id="shell.run_command",
            name="Shell",
            description="Run shell command",
            input_schema={"type": "object"},
            requires_confirmation=True,
        ),
        _shell_failure_handler,
    )
    registry.register(
        ToolSpec(
            id="demo.partial",
            name="Partial",
            description="Partial write tool",
            input_schema={"type": "object"},
            requires_confirmation=True,
        ),
        _partial_handler,
    )
    return TaskRunner(
        registry=registry,
        store=TaskStore(tmp_path / "tasks.json"),
        path_guard=PathGuard([tmp_path]),
        settings=settings,
    )


def test_confirmation_required_tools_wait_before_running(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    task = asyncio.run(
        runner.submit("demo.write", {"value": 1}, wait=True, confirmed=False)
    )

    assert task.status == "waiting_confirmation"
    assert task.output == {"reason": "tool requires confirmation"}
    assert any(log["level"] == "warning" for log in task.logs)


def test_confirmed_tool_runs_successfully(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    task = asyncio.run(
        runner.submit("demo.write", {"value": 2}, wait=True, confirmed=True)
    )

    assert task.status == "success"
    assert task.output == {"ok": True, "input": {"value": 2}}
    assert any(log["message"] == "demo handler ran" for log in task.logs)


def test_submit_uses_canonical_tool_id_for_alias(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)
    runner.registry.register_alias("demo.old_write", "demo.write")

    task = asyncio.run(
        runner.submit("demo.old_write", {"value": 4}, wait=True, confirmed=True)
    )

    assert task.tool == "demo.write"
    assert task.status == "success"


def test_shell_nonzero_exit_code_marks_task_failed(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    task = asyncio.run(
        runner.submit("shell.run_command", {"command": "python"}, wait=True, confirmed=True)
    )

    assert task.status == "failure"
    assert task.output == {"exit_code": 1, "stdout": "", "stderr": "SyntaxError: invalid syntax"}
    assert "command exited with code 1" in (task.error or "")
    assert "SyntaxError" in (task.error or "")


def test_resumable_partial_output_marks_task_partial(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    task = asyncio.run(
        runner.submit("demo.partial", {}, wait=True, confirmed=True)
    )

    assert task.status == "partial"
    assert task.output["status"] == "partial_resumable"
    assert task.output["partial_resumable"] is True
    assert task.error == "max_seconds_exceeded:1800"
    assert any(log["level"] == "warning" for log in task.logs)


def test_disabled_plugin_blocks_submission(tmp_path: Path) -> None:
    class DisabledSettings:
        def is_tool_enabled(self, tool_id: str) -> bool:
            return False

    runner = _build_runner(tmp_path, settings=DisabledSettings())

    with pytest.raises(PermissionError):
        asyncio.run(
            runner.submit("demo.write", {"value": 3}, wait=True, confirmed=True)
        )
