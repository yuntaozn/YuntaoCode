import asyncio
from pathlib import Path
from typing import Any

import pytest

from runtime.security import PathGuard
from runtime.task_runner import TaskRunner, _compact_failure_message
from runtime.task_store import TaskStore
from runtime.tool_registry import ToolRegistry, ToolSpec


async def _demo_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    context.log("info", "demo handler ran", {"input": input_data})
    return {"ok": True, "input": input_data}


async def _shell_failure_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    if input_data.get("command") == "slow":
        context.log("error", "command timed out")
        return {"exit_code": 1, "stdout": "", "stderr": "", "timed_out": True, "timeout": 10}
    context.log("error", "command finished with exit code 1")
    return {"exit_code": 1, "stdout": "", "stderr": "SyntaxError: invalid syntax"}


def test_compact_failure_message_prefers_structured_failure_message() -> None:
    message = _compact_failure_message(
        {
            "exit_code": 1,
            "failure_message": "Node -c/--check expects a JavaScript file path.",
            "stderr": "Error: Cannot find module 'const fs = require(...)'",
        },
        "command exited with code 1",
    )

    assert message == (
        "command exited with code 1: "
        "Node -c/--check expects a JavaScript file path."
    )


async def _partial_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    context.log("warning", "partial output generated")
    return {
        "status": "partial_resumable",
        "partial_resumable": True,
        "stopped_reason": "max_seconds_exceeded:1800",
        "path": str(context.path_guard.resolve("partial.docx")),
    }


async def _temp_dir_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    return {"temp_dir": str(context.temp_dir), "task_id": context.task_id}


async def _backup_then_success_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    if callable(context.backup_file):
        context.backup_file(input_data.get("path") or "demo.txt")
    return {"ok": True}


async def _long_running_handler(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    context.log("info", "long task started")
    await asyncio.sleep(30)
    return {"ok": True}


def _build_runner(
    tmp_path: Path,
    *,
    settings: Any | None = None,
    backup_store: Any | None = None,
) -> TaskRunner:
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
            id="filesystem.write_file",
            name="Write File",
            description="Write file",
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
    registry.register(
        ToolSpec(
            id="demo.temp_dir",
            name="Temp Dir",
            description="Return temp dir",
            input_schema={"type": "object"},
        ),
        _temp_dir_handler,
    )
    registry.register(
        ToolSpec(
            id="demo.long_running",
            name="Long Running",
            description="Long-running tool used for cancellation tests",
            input_schema={"type": "object"},
        ),
        _long_running_handler,
    )
    return TaskRunner(
        registry=registry,
        store=TaskStore(tmp_path / "tasks.json"),
        path_guard=PathGuard([tmp_path]),
        backup_store=backup_store,
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


def test_shell_timeout_marks_task_failed_with_timeout_reason(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    task = asyncio.run(
        runner.submit("shell.run_command", {"command": "slow"}, wait=True, confirmed=True)
    )

    assert task.status == "failure"
    assert task.output["timed_out"] is True
    assert task.error == "command timed out after 10s"


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


def test_task_runner_provides_task_temp_dir(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    task = asyncio.run(
        runner.submit("demo.temp_dir", {}, wait=True, confirmed=True)
    )

    assert task.status == "success"
    assert task.output["task_id"] == task.id
    temp_dir = Path(task.output["temp_dir"])
    assert temp_dir.exists()
    assert temp_dir.name == task.id


def test_task_runner_reuses_artifact_scope_across_tool_tasks(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    first = asyncio.run(
        runner.submit(
            "demo.temp_dir",
            {},
            wait=True,
            confirmed=True,
            artifact_scope_id="run-123",
        )
    )
    second = asyncio.run(
        runner.submit(
            "demo.temp_dir",
            {},
            wait=True,
            confirmed=True,
            artifact_scope_id="run-123",
        )
    )

    assert first.id != second.id
    assert first.output["temp_dir"] == second.output["temp_dir"]
    assert Path(first.output["temp_dir"]).name == "run-123"


@pytest.mark.asyncio
async def test_task_runner_cancels_background_tool_task(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)
    task = await runner.submit(
        "demo.long_running",
        {},
        wait=False,
        confirmed=True,
    )

    for _ in range(50):
        current = runner.store.get(task.id)
        if current and current.status == "running":
            break
        await asyncio.sleep(0.01)

    assert runner.cancel(task.id) is True
    for _ in range(100):
        current = runner.store.get(task.id)
        if current and current.status == "cancelled":
            break
        await asyncio.sleep(0.01)

    current = runner.store.get(task.id)
    assert current is not None
    assert current.status == "cancelled"
    assert current.error == "tool task cancelled"


def test_ai_plugin_workspace_guard_blocks_write_file_to_workspace_draft(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    with pytest.raises(PermissionError) as exc:
        asyncio.run(
            runner.submit(
                "filesystem.write_file",
                {"path": str(tmp_path / "ai-plugins" / "video-generator" / "plugin.json")},
                wait=True,
                confirmed=True,
                workspace_path=str(tmp_path),
            )
        )

    assert "不能写入当前工作区的 ai-plugins/ 或 capability-packs/" in str(exc.value)


def test_ai_plugin_workspace_guard_blocks_shell_command_to_workspace_draft(tmp_path: Path) -> None:
    runner = _build_runner(tmp_path)

    with pytest.raises(PermissionError) as exc:
        asyncio.run(
            runner.submit(
                "shell.run_command",
                {"command": "mkdir ai-plugins\\video-generator"},
                wait=True,
                confirmed=True,
                workspace_path=str(tmp_path),
            )
        )

    assert "不能写入当前工作区的 ai-plugins/ 或 capability-packs/" in str(exc.value)


def test_disabled_plugin_blocks_submission(tmp_path: Path) -> None:
    class DisabledSettings:
        def is_tool_enabled(self, tool_id: str) -> bool:
            return False

    runner = _build_runner(tmp_path, settings=DisabledSettings())

    with pytest.raises(PermissionError):
        asyncio.run(
            runner.submit("demo.write", {"value": 3}, wait=True, confirmed=True)
        )


def test_backup_failure_is_recorded_without_blocking_tool_success(tmp_path: Path) -> None:
    class BackupSettings:
        def is_tool_enabled(self, tool_id: str) -> bool:
            return True

        def get_access_scope(self) -> str:
            return "project_only"

        def get_backup_settings(self) -> dict[str, Any]:
            return {"enabled": True, "keep_rounds": 5}

    class FailingBackupSession:
        def backup_file(self, path: str | Path) -> None:
            raise PermissionError("backup destination locked")

        def finish(self, status: str, keep_rounds: int) -> None:
            return None

    class FailingBackupStore:
        def begin(self, *args: Any, **kwargs: Any) -> FailingBackupSession:
            return FailingBackupSession()

    runner = _build_runner(
        tmp_path,
        settings=BackupSettings(),
        backup_store=FailingBackupStore(),
    )
    runner.registry.unregister("filesystem.write_file")
    runner.registry.register(
        ToolSpec(
            id="filesystem.write_file",
            name="Write File",
            description="Write file",
            input_schema={"type": "object"},
            requires_confirmation=True,
        ),
        _backup_then_success_handler,
    )

    task = asyncio.run(
        runner.submit(
            "filesystem.write_file",
            {"path": "demo.txt"},
            wait=True,
            confirmed=True,
            workspace_path=str(tmp_path),
        )
    )

    assert task.status == "success"
    assert task.output["ok"] is True
    assert task.output["_backup_warnings"] == [
        {"path": "demo.txt", "error": "backup destination locked"}
    ]
    assert any(
        log["level"] == "warning" and "backup failed" in log["message"]
        for log in task.logs
    )


def test_backup_finish_failure_is_recorded_without_blocking_tool_success(tmp_path: Path) -> None:
    class BackupSettings:
        def is_tool_enabled(self, tool_id: str) -> bool:
            return True

        def get_access_scope(self) -> str:
            return "project_only"

        def get_backup_settings(self) -> dict[str, Any]:
            return {"enabled": True, "keep_rounds": 5}

    class FailingBackupSession:
        def backup_file(self, path: str | Path) -> None:
            return None

        def finish(self, status: str, keep_rounds: int) -> None:
            raise PermissionError("old backup asset is locked")

    class FailingBackupStore:
        def begin(self, *args: Any, **kwargs: Any) -> FailingBackupSession:
            return FailingBackupSession()

    runner = _build_runner(
        tmp_path,
        settings=BackupSettings(),
        backup_store=FailingBackupStore(),
    )
    runner.registry.unregister("filesystem.write_file")
    runner.registry.register(
        ToolSpec(
            id="filesystem.write_file",
            name="Write File",
            description="Write file",
            input_schema={"type": "object"},
            requires_confirmation=True,
        ),
        _backup_then_success_handler,
    )

    task = asyncio.run(
        runner.submit(
            "filesystem.write_file",
            {"path": "demo.txt"},
            wait=True,
            confirmed=True,
            workspace_path=str(tmp_path),
        )
    )

    assert task.status == "success"
    assert task.output["ok"] is True
    assert task.output["_backup_warnings"] == [
        {"path": "", "error": "old backup asset is locked", "phase": "finish"}
    ]
    assert any(
        log["level"] == "warning" and "backup finish failed" in log["message"]
        for log in task.logs
    )
