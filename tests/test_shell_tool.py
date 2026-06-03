from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import pytest

from runtime.security import PathGuard
from runtime.skills.shell import _compose_command, run_command


@dataclass
class FakeContext:
    path_guard: PathGuard

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        return None


def test_compose_command_appends_args() -> None:
    command = _compose_command("python", ["-m", "pip", "install", "python-docx"])

    assert "python" in command
    assert "-m" in command
    assert "pip" in command
    assert "python-docx" in command


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
    assert "ARGS_OK" in result["stdout"]
    assert "python" in result["command"]
    assert "-c" in result["command"]


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
