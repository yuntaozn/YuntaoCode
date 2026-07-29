from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys

import pytest

from runtime.security import PathGuard
from runtime.skills.shell import (
    _compose_command,
    _effective_timeout,
    _node_check_inline_script_diagnostic,
    register_shell_tools,
    run_command,
)
from runtime.tool_registry import ToolRegistry


@dataclass
class FakeContext:
    path_guard: PathGuard
    temp_dir: Path | None = None
    logs: list[dict] = field(default_factory=list)

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        self.logs.append({"level": level, "message": message, "data": data or {}})


def test_compose_command_appends_args() -> None:
    command = _compose_command("python", ["-m", "pip", "install", "python-docx"])

    assert "python" in command
    assert "-m" in command
    assert "pip" in command
    assert "python-docx" in command


def test_node_check_inline_script_diagnostic_suggests_file_check(tmp_path: Path) -> None:
    script = (
        "const fs = require('fs'); "
        "const content = fs.readFileSync('D:\\\\code\\\\demo\\\\src\\\\app.js', 'utf8'); "
        "console.log(content.length);"
    )

    diagnostic = _node_check_inline_script_diagnostic("node", ["-c", script], str(tmp_path))

    assert diagnostic is not None
    assert diagnostic["code"] == "node_check_inline_script"
    assert "expects a JavaScript file path" in diagnostic["message"]
    assert diagnostic["suggested_calls"][0]["args"] == [
        "--check",
        "D:\\code\\demo\\src\\app.js",
    ]


@pytest.mark.asyncio
async def test_run_command_uses_args_array(tmp_path: Path) -> None:
    context = FakeContext(PathGuard([tmp_path]))

    result = await run_command(
        {
            "command": "python",
            "args": ["-c", "print('ARGS_OK')"],
            "timeout": 10,
        },
        context,
    )

    assert result["exit_code"] == 0
    assert result["timeout"] == 10
    assert "ARGS_OK" in result["stdout"]
    assert "python" in result["command"]
    assert "-c" in result["command"]
    assert result["execution_mode"] == "foreground"
    assert result["shell_dialect"] == "direct_exec"


@pytest.mark.asyncio
async def test_run_command_passes_multiline_args_without_shell_requoting(tmp_path: Path) -> None:
    context = FakeContext(PathGuard([tmp_path]))

    script = "value = \"引号'和中文冒号：OK\"\nprint(value)"
    result = await run_command(
        {
            "command": sys.executable,
            "args": ["-c", script],
            "timeout": 10,
        },
        context,
    )

    assert result["exit_code"] == 0
    assert "引号'和中文冒号：OK" in result["stdout"]
    assert result["debug_session"]["kind"] == "debug_session"
    assert result["debug_session"]["source"]["type"] == "shell.run_command"
    assert result["debug_session"]["command"]["executable"] == sys.executable
    assert result["debug_session"]["process"]["exit_code"] == 0
    assert result["debug_session"]["health"]["status"] == "success"


@pytest.mark.asyncio
async def test_run_command_can_use_task_temp_cwd(tmp_path: Path) -> None:
    temp_dir = tmp_path / "task-temp"
    temp_dir.mkdir()
    script = temp_dir / "hello.py"
    script.write_text("print('TEMP_OK')", encoding="utf-8")
    context = FakeContext(PathGuard([tmp_path / "workspace"]), temp_dir=temp_dir)

    result = await run_command(
        {
            "command": sys.executable,
            "args": ["hello.py"],
            "cwd": "task_temp",
            "timeout": 10,
        },
        context,
    )

    assert result["exit_code"] == 0
    assert result["cwd"] == str(temp_dir.resolve())
    assert result["task_temp_dir"] == str(temp_dir)
    assert "TEMP_OK" in result["stdout"]
    assert result["debug_session"]["command"]["cwd"] == str(temp_dir.resolve())


@pytest.mark.asyncio
async def test_run_command_streams_output_before_process_finishes(tmp_path: Path) -> None:
    context = FakeContext(PathGuard([tmp_path]))
    task = asyncio.create_task(
        run_command(
            {
                "command": sys.executable,
                "args": [
                    "-c",
                    "import time; print('INSTALL_STEP_1', flush=True); time.sleep(3); print('DONE')",
                ],
                "timeout": 5,
            },
            context,
        )
    )

    for _ in range(100):
        if any(
            item["data"].get("kind") == "command_output"
            and "INSTALL_STEP_1" in item["message"]
            for item in context.logs
        ):
            break
        await asyncio.sleep(0.025)

    assert not task.done()
    assert any(
        item["data"].get("kind") == "command_output"
        and "INSTALL_STEP_1" in item["message"]
        for item in context.logs
    ), context.logs
    result = await task
    assert result["exit_code"] == 0
    assert "DONE" in result["stdout"]


@pytest.mark.asyncio
async def test_run_command_emits_heartbeat_when_process_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("runtime.skills.shell.PROGRESS_HEARTBEAT_SECONDS", 0.05)
    context = FakeContext(PathGuard([tmp_path]))

    result = await run_command(
        {
            "command": sys.executable,
            "args": ["-c", "import time; time.sleep(0.16)"],
            "timeout": 5,
        },
        context,
    )

    assert result["exit_code"] == 0
    assert any(item["data"].get("kind") == "command_heartbeat" for item in context.logs)


@pytest.mark.asyncio
async def test_run_command_can_start_program_in_background(tmp_path: Path) -> None:
    context = FakeContext(PathGuard([tmp_path]))

    result = await run_command(
        {
            "command": sys.executable,
            "args": ["-c", "import time; time.sleep(0.1)"],
            "background": True,
        },
        context,
    )

    assert result["exit_code"] is None
    assert result["background"] is True
    assert result["execution_mode"] == "background"
    assert result["process_state"] == "running"
    assert result["shell_dialect"] == "direct_exec"
    assert result["effects"] == ["external_state_change"]
    assert result["roles"] == ["deliverable", "evidence"]
    assert isinstance(result["pid"], int)
    assert result["debug_session"]["health"] == {
        "status": "running",
        "has_runtime_errors": False,
    }
    await asyncio.sleep(0.2)


def test_shell_spec_exposes_execution_dialect_and_background_mode() -> None:
    registry = ToolRegistry()
    register_shell_tools(registry)

    spec = registry.get_public_spec("shell.run_command")

    assert "command+args" in spec["description"]
    assert "background=true" in spec["description"]
    assert "background" in spec["input_schema"]["properties"]
    affordances = {item["id"]: item for item in spec["affordances"]}
    assert set(affordances) == {
        "process.direct_exec",
        "process.start_background",
        "shell.platform_expression",
    }
    assert affordances["process.start_background"]["effects"] == [
        "external_state_change"
    ]
    assert affordances["process.start_background"]["evidence_limits"] == [
        "process creation is not behavioral verification of the application"
    ]
    if sys.platform.startswith("win"):
        assert "Windows PowerShell 5.1" in spec["description"]


def test_dependency_install_gets_long_default_timeout() -> None:
    assert _effective_timeout(
        {},
        sys.executable,
        ["-m", "playwright", "install", "chromium"],
    ) == 600
    assert _effective_timeout(
        {"timeout": 45},
        sys.executable,
        ["-m", "pip", "install", "demo"],
    ) == 45
