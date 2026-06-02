"""Shell command execution skill for the local intelligent terminal."""

from __future__ import annotations

import asyncio
import locale
import os
import re
import shlex
import signal
import subprocess
import sys
from typing import Any

from runtime.tool_registry import ToolRegistry, ToolSpec

MAX_TIMEOUT = 120
DEFAULT_TIMEOUT = 30
MAX_STDOUT = 50_000
MAX_STDERR = 10_000

# Patterns that are clearly destructive on Windows or Unix
DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r"\bdel\s+/s\s+/q\s+[a-z]:\\", re.IGNORECASE),
    re.compile(r"\brmdir\s+/s\s+/q\s+[a-z]:\\", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+~", re.IGNORECASE),
    re.compile(r"Remove-Item\s+.*-Recurse.*-Force.*[A-Z]:\\$", re.IGNORECASE),
]


def _is_dangerous(command: str) -> bool:
    return any(pattern.search(command) for pattern in DANGEROUS_PATTERNS)


def _decode_output(raw: bytes) -> str:
    encodings = [
        "utf-8-sig",
        locale.getpreferredencoding(False),
        "gbk",
        "cp936",
        "utf-16",
    ]
    seen: set[str] = set()
    for encoding in encodings:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _quote_windows_arg(value: Any) -> str:
    text = str(value)
    if not text:
        return "''"
    return "'" + text.replace("'", "''") + "'"


def _normalize_args(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _compose_command(command: str, args: Any) -> str:
    argv = _normalize_args(args)
    if not argv:
        return command
    if sys.platform.startswith("win"):
        return " ".join([command, *(_quote_windows_arg(arg) for arg in argv)])
    return " ".join([command, *(shlex.quote(arg) for arg in argv)])


# On Windows, suppress the console window for child processes
_WIN_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if sys.platform.startswith("win"):
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=_WIN_NO_WINDOW,
            )
            await asyncio.wait_for(killer.communicate(), timeout=5)
            return
        except Exception:
            pass
    try:
        if not sys.platform.startswith("win"):
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            return


async def run_command(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    command = (input_data.get("command") or "").strip()
    if not command:
        raise ValueError("command is required")
    command = _compose_command(command, input_data.get("args"))

    if _is_dangerous(command):
        raise ValueError(f"command rejected as potentially destructive: {command[:100]}")

    cwd_raw = input_data.get("cwd")
    if cwd_raw:
        cwd = str(context.path_guard.resolve(cwd_raw))
    else:
        cwd = str(context.path_guard.workspace_roots[0])

    timeout = min(int(input_data.get("timeout", DEFAULT_TIMEOUT)), MAX_TIMEOUT)

    context.log("info", f"running: {command[:200]}", {"cwd": cwd, "timeout": timeout})

    timed_out = False
    stdout_bytes = b""
    stderr_bytes = b""
    try:
        process_kwargs: dict[str, Any] = {}
        if sys.platform.startswith("win"):
            # PowerShell v5 doesn't support &&, replace with ;
            safe_command = command.replace("&&", ";")
            ps_command = (
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                "$OutputEncoding = [System.Text.Encoding]::UTF8; "
                f"{safe_command}"
            )
            process = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                creationflags=_WIN_NO_WINDOW,
            )
        else:
            process_kwargs["start_new_session"] = True
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                **process_kwargs,
            )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            timed_out = True
            await _kill_process_tree(process)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=5
                )
            except asyncio.TimeoutError:
                stderr_bytes = (
                    stderr_bytes
                    + f"\ncommand timed out after {timeout}s and the process tree was terminated".encode("utf-8")
                )
    except OSError as exc:
        raise ValueError(f"failed to execute command: {exc}") from exc

    stdout = _decode_output(stdout_bytes)[:MAX_STDOUT]
    stderr = _decode_output(stderr_bytes)[:MAX_STDERR]
    exit_code = process.returncode or 0

    context.log(
        "info" if exit_code == 0 else "error",
        f"command finished with exit code {exit_code}",
        {"timed_out": timed_out},
    )

    return {
        "command": command,
        "cwd": cwd,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "stdout_truncated": len(stdout_bytes) > MAX_STDOUT,
        "stderr_truncated": len(stderr_bytes) > MAX_STDERR,
    }


def register_shell_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="shell.run_command",
            name="执行终端命令",
            description=(
                "在允许工作区内执行终端命令。适合运行构建、测试、安装依赖等操作。"
                "Windows 下通过 PowerShell 执行，请优先使用 PowerShell 命令，例如 Copy-Item、Get-ChildItem、"
                "Remove-Item、python -m py_compile；不要假设 bash/cp/rm 语法可用。超时默认30秒，最大120秒。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选命令参数数组，会安全拼接到 command 后执行",
                    },
                    "cwd": {"type": "string", "description": "工作目录（可选，默认当前workspace）"},
                    "timeout": {"type": "integer", "default": 30, "description": "超时秒数（最大120）"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        ),
        run_command,
    )
