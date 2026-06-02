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


def test_disabled_plugin_blocks_submission(tmp_path: Path) -> None:
    class DisabledSettings:
        def is_tool_enabled(self, tool_id: str) -> bool:
            return False

    runner = _build_runner(tmp_path, settings=DisabledSettings())

    with pytest.raises(PermissionError):
        asyncio.run(
            runner.submit("demo.write", {"value": 3}, wait=True, confirmed=True)
        )
