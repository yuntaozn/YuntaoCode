from __future__ import annotations

import sys
from pathlib import Path

import pytest

from runtime.cli_provider_manager import CliProviderManager
from runtime.security import PathGuard
from runtime.task_runner import TaskRunner
from runtime.task_store import TaskStore
from runtime.tool_registry import ToolRegistry


def _write_file_provider(command: str) -> dict:
    return {
        "id": "demo",
        "name": "Demo CLI",
        "enabled": True,
        "tools": [
            {
                "id": "write_text",
                "name": "Write text with CLI",
                "capability": "demo.write_text",
                "command": command,
                "args": [
                    "-c",
                    (
                        "import pathlib,sys; "
                        "pathlib.Path(sys.argv[1]).write_text('hello from cli', encoding='utf-8')"
                    ),
                    "{output_path}",
                ],
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string"},
                    },
                    "required": ["output_path"],
                },
                "outputs": [
                    {"path": "{output_path}", "artifact": "text", "required": True},
                ],
                "effects": ["file_write"],
                "roles": ["deliverable", "verification"],
                "verification_strength": "standard",
                "timeout": 30,
                "requires_confirmation": True,
            }
        ],
    }


def test_cli_provider_registers_declared_tool(tmp_path: Path) -> None:
    registry = ToolRegistry()
    manager = CliProviderManager(tmp_path / "cli-providers.json", registry=registry)

    provider = manager.upsert(_write_file_provider(sys.executable))
    spec = registry.get_public_spec("cli_demo.write_text")

    assert provider["provider_kind"] == "cli"
    assert spec["provider_kind"] == "cli"
    assert spec["source_type"] == "cli"
    assert spec["source_id"] == "demo"
    assert spec["capability"] == "demo.write_text"
    assert spec["effects"] == ["file_write"]
    assert spec["roles"] == ["deliverable", "verification"]
    assert manager.is_tool_available("cli_demo.write_text", source_id="demo") is True


@pytest.mark.asyncio
async def test_cli_provider_runs_through_task_runner_with_evidence(tmp_path: Path) -> None:
    registry = ToolRegistry()
    CliProviderManager(tmp_path / "cli-providers.json", registry=registry).upsert(
        _write_file_provider(sys.executable)
    )
    runner = TaskRunner(
        registry=registry,
        store=TaskStore(tmp_path / "tasks.json"),
        path_guard=PathGuard([tmp_path]),
    )

    task = await runner.submit(
        "cli_demo.write_text",
        {"output_path": "out.txt"},
        wait=True,
        confirmed=True,
        workspace_path=str(tmp_path),
    )
    record = runner.store.get(task.id)

    assert record is not None
    assert record.status == "success"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello from cli"
    assert record.output is not None
    assert record.output["provider_kind"] == "cli"
    assert record.output["paths"] == [str(tmp_path / "out.txt")]
    assert record.output["effects"] == ["file_write"]
    assert record.output["roles"] == ["deliverable", "verification"]
    assert all(item["ok"] for item in record.output["evidence"])


@pytest.mark.asyncio
async def test_cli_provider_waits_for_confirmation(tmp_path: Path) -> None:
    registry = ToolRegistry()
    CliProviderManager(tmp_path / "cli-providers.json", registry=registry).upsert(
        _write_file_provider(sys.executable)
    )
    runner = TaskRunner(
        registry=registry,
        store=TaskStore(tmp_path / "tasks.json"),
        path_guard=PathGuard([tmp_path]),
    )

    task = await runner.submit(
        "cli_demo.write_text",
        {"output_path": "out.txt"},
        wait=True,
        confirmed=False,
        workspace_path=str(tmp_path),
    )
    record = runner.store.get(task.id)

    assert record is not None
    assert record.status == "waiting_confirmation"
    assert not (tmp_path / "out.txt").exists()


@pytest.mark.asyncio
async def test_cli_provider_paths_stay_inside_workspace(tmp_path: Path) -> None:
    registry = ToolRegistry()
    CliProviderManager(tmp_path / "cli-providers.json", registry=registry).upsert(
        _write_file_provider(sys.executable)
    )
    runner = TaskRunner(
        registry=registry,
        store=TaskStore(tmp_path / "tasks.json"),
        path_guard=PathGuard([tmp_path]),
    )

    task = await runner.submit(
        "cli_demo.write_text",
        {"output_path": str(tmp_path.parent / "outside.txt")},
        wait=True,
        confirmed=True,
        workspace_path=str(tmp_path),
    )
    record = runner.store.get(task.id)

    assert record is not None
    assert record.status == "failure"
    assert "outside allowed workspace roots" in str(record.error)
    assert not (tmp_path.parent / "outside.txt").exists()


def test_cli_provider_reports_missing_command_as_capability_issue(tmp_path: Path) -> None:
    registry = ToolRegistry()
    manager = CliProviderManager(tmp_path / "cli-providers.json", registry=registry)
    manager.upsert(_write_file_provider("definitely-missing-yuntaocode-cli"))

    metadata = manager.tool_runtime_metadata("cli_demo.write_text", source_id="demo")
    issues = manager.capability_issues()

    assert manager.is_tool_available("cli_demo.write_text", source_id="demo") is False
    assert metadata["tool_health"] == "unavailable"
    assert "definitely-missing-yuntaocode-cli" in metadata["tool_last_error"]
    assert issues[0]["source_type"] == "cli"
    assert issues[0]["capability_id"] == "demo.write_text"
    assert issues[0]["recommended_action"] == "configure"
