"""Shell command execution tools for YuntaoCode local task execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import locale
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from typing import Any

from runtime.debug_session import build_debug_session
from runtime.shell_command_facts import shell_command_facts
from runtime.tool_registry import ToolRegistry, ToolSpec

MAX_TIMEOUT = 900
DEFAULT_TIMEOUT = 30
MAX_STDOUT = 50_000
MAX_STDERR = 10_000
STREAM_READ_SIZE = 4096
LIVE_OUTPUT_MIN_INTERVAL = 0.75
MAX_LIVE_OUTPUT_EVENTS = 80
MAX_LIVE_MESSAGE_CHARS = 1200
PROGRESS_HEARTBEAT_SECONDS = 10.0
TASK_TEMP_CWD_ALIASES = {"task_temp", "__task_temp__", "$TASK_TEMP", "{task_temp}"}

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


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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


class _BoundedByteCapture:
    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self.data = bytearray()
        self.total_bytes = 0

    def add(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])

    @property
    def value(self) -> bytes:
        return bytes(self.data)

    @property
    def truncated(self) -> bool:
        return self.total_bytes > len(self.data)


class _LiveCommandObserver:
    def __init__(self, context: Any, started_at: float) -> None:
        self.context = context
        self.started_at = started_at
        self.last_output_at = started_at
        self.last_emit_at = 0.0
        self.output_events = 0
        self.pending: dict[str, str] = {}

    def feed(self, stream_name: str, chunk: bytes) -> None:
        now = time.monotonic()
        self.last_output_at = now
        text = _live_output_text(chunk)
        if not text:
            return
        self.pending[stream_name] = text
        if (
            self.output_events < MAX_LIVE_OUTPUT_EVENTS
            and now - self.last_emit_at >= LIVE_OUTPUT_MIN_INTERVAL
        ):
            self.flush()

    def flush(self, *, force: bool = False) -> bool:
        if not self.pending:
            return False
        if self.output_events >= MAX_LIVE_OUTPUT_EVENTS and not force:
            return False
        stream_name, message = next(reversed(self.pending.items()))
        self.pending.clear()
        self.last_emit_at = time.monotonic()
        self.output_events += 1
        self._log(
            "warning" if stream_name == "stderr" else "info",
            message,
            {
                "kind": "command_output",
                "stream": stream_name,
                "elapsed_seconds": round(self.last_emit_at - self.started_at, 1),
            },
        )
        return True

    def heartbeat(self) -> None:
        now = time.monotonic()
        flushed = self.flush(force=self.output_events >= MAX_LIVE_OUTPUT_EVENTS)
        silent_seconds = now - self.last_output_at
        if flushed or silent_seconds < PROGRESS_HEARTBEAT_SECONDS:
            return
        self._log(
            "info",
            f"command still running; elapsed {int(now - self.started_at)}s; "
            f"no new output for {int(silent_seconds)}s",
            {
                "kind": "command_heartbeat",
                "elapsed_seconds": round(now - self.started_at, 1),
                "silent_seconds": round(silent_seconds, 1),
            },
        )

    def _log(self, level: str, message: str, data: dict[str, Any]) -> None:
        try:
            self.context.log(level, message, data)
        except Exception:
            # Progress reporting must never terminate the subprocess itself.
            return


def _live_output_text(chunk: bytes) -> str:
    text = _decode_output(chunk).replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    compact = "\n".join(lines[-4:])
    return compact[:MAX_LIVE_MESSAGE_CHARS]


async def _read_process_stream(
    stream: asyncio.StreamReader | None,
    stream_name: str,
    capture: _BoundedByteCapture,
    observer: _LiveCommandObserver,
) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(STREAM_READ_SIZE)
        if not chunk:
            return
        capture.add(chunk)
        observer.feed(stream_name, chunk)


async def _wait_for_process(
    process: asyncio.subprocess.Process,
    timeout: int,
    observer: _LiveCommandObserver,
) -> bool:
    wait_task = asyncio.create_task(process.wait())
    deadline = time.monotonic() + timeout
    try:
        while not wait_task.done():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            done, _ = await asyncio.wait(
                {wait_task},
                timeout=min(PROGRESS_HEARTBEAT_SECONDS, remaining),
            )
            if done:
                return False
            observer.heartbeat()
        return False
    finally:
        if not wait_task.done():
            wait_task.cancel()


async def _finish_stream_readers(readers: list[asyncio.Task[Any]]) -> None:
    if not readers:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*readers), timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)


def _effective_timeout(input_data: dict[str, Any], command: str, argv: list[str]) -> int:
    facts = shell_command_facts(command, argv)
    default = facts.default_timeout if "timeout" not in input_data else DEFAULT_TIMEOUT
    try:
        requested = int(input_data.get("timeout", default))
    except (TypeError, ValueError):
        requested = default
    return max(1, min(requested, MAX_TIMEOUT))


async def run_command(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    command = (input_data.get("command") or "").strip()
    if not command:
        raise ValueError("command is required")
    argv = _normalize_args(input_data.get("args"))
    display_command = _compose_command(command, argv)

    if _is_dangerous(display_command):
        raise ValueError(f"command rejected as potentially destructive: {display_command[:100]}")

    cwd = _resolve_cwd(input_data, context)

    command_facts = shell_command_facts(command, argv)
    timeout = _effective_timeout(input_data, command, argv)

    context.log(
        "info",
        f"running: {display_command[:200]}",
        {
            "kind": "command_start",
            "cwd": cwd,
            "timeout": timeout,
            "command_role": command_facts.role,
            "observable": True,
        },
    )

    timed_out = False
    stdout_capture = _BoundedByteCapture(MAX_STDOUT)
    stderr_capture = _BoundedByteCapture(MAX_STDERR)
    process: asyncio.subprocess.Process | None = None
    readers: list[asyncio.Task[Any]] = []
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    observer = _LiveCommandObserver(context, started_monotonic)
    try:
        process_kwargs: dict[str, Any] = {}
        if argv:
            if sys.platform.startswith("win"):
                process_kwargs["creationflags"] = _WIN_NO_WINDOW
            else:
                process_kwargs["start_new_session"] = True
            process = await asyncio.create_subprocess_exec(
                command,
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                **process_kwargs,
            )
        elif sys.platform.startswith("win"):
            # PowerShell v5 doesn't support &&, replace with ;
            safe_command = display_command.replace("&&", ";")
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
                display_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                **process_kwargs,
            )

        readers = [
            asyncio.create_task(
                _read_process_stream(process.stdout, "stdout", stdout_capture, observer)
            ),
            asyncio.create_task(
                _read_process_stream(process.stderr, "stderr", stderr_capture, observer)
            ),
        ]
        timed_out = await _wait_for_process(process, timeout, observer)
        if timed_out:
            await _kill_process_tree(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            stderr_capture.add(
                f"\ncommand timed out after {timeout}s and the process tree was terminated".encode(
                    "utf-8"
                )
            )
        await _finish_stream_readers(readers)
        observer.flush(force=True)
    except asyncio.CancelledError:
        if process is not None and process.returncode is None:
            await _kill_process_tree(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        await _finish_stream_readers(readers)
        context.log(
            "warning",
            "command cancelled; child process tree termination requested",
            {"kind": "command_cancelled"},
        )
        raise
    except OSError as exc:
        raise ValueError(f"failed to execute command: {exc}") from exc

    stdout = _decode_output(stdout_capture.value)
    stderr = _decode_output(stderr_capture.value)
    exit_code = process.returncode if process is not None and process.returncode is not None else 0
    diagnostics = _shell_result_diagnostics(
        command=command,
        argv=argv,
        cwd=cwd,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )

    context.log(
        "info" if exit_code == 0 else "error",
        f"command finished with exit code {exit_code}",
        {"timed_out": timed_out},
    )

    output = {
        "command": display_command,
        "executable": command,
        "args": argv,
        "display_command": display_command,
        "cwd": cwd,
        "task_temp_dir": str(getattr(context, "temp_dir", "") or ""),
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "timeout": timeout,
        "command_role": command_facts.role,
        "observable": True,
        "pid": process.pid if process is not None else None,
        "stdout_truncated": stdout_capture.truncated,
        "stderr_truncated": stderr_capture.truncated,
    }
    if diagnostics:
        output["diagnostics"] = diagnostics
        output["failure_message"] = str(diagnostics[0].get("message") or "")
    output["debug_session"] = build_debug_session(
        source_type="shell.run_command",
        command=display_command,
        executable=command,
        args=argv,
        cwd=cwd,
        pid=process.pid if process is not None else None,
        exit_code=exit_code,
        timed_out=timed_out,
        timeout=timeout,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
        diagnostics=diagnostics,
        started_at=started_at,
        finished_at=_utc_now_iso(),
        duration_seconds=round(max(0.0, time.monotonic() - started_monotonic), 3),
    )
    return output


def _resolve_cwd(input_data: dict[str, Any], context: Any) -> str:
    temp_dir = _context_temp_dir(context)
    if input_data.get("use_task_temp"):
        if temp_dir is None:
            raise ValueError("task temp directory is not available")
        temp_dir.mkdir(parents=True, exist_ok=True)
        return str(temp_dir)

    cwd_raw = input_data.get("cwd")
    if cwd_raw:
        cwd_text = str(cwd_raw).strip()
        if cwd_text in TASK_TEMP_CWD_ALIASES:
            if temp_dir is None:
                raise ValueError("task temp directory is not available")
            temp_dir.mkdir(parents=True, exist_ok=True)
            return str(temp_dir)
        if temp_dir is not None:
            try:
                candidate = Path(cwd_text).expanduser()
                if candidate.is_absolute():
                    resolved = candidate.resolve()
                    resolved.relative_to(temp_dir)
                    return str(resolved)
            except (OSError, ValueError):
                pass
        return str(context.path_guard.resolve(cwd_text))
    return str(context.path_guard.workspace_roots[0])


def _context_temp_dir(context: Any) -> Path | None:
    temp_dir = getattr(context, "temp_dir", None)
    if temp_dir is None:
        return None
    return Path(temp_dir).resolve()


def _shell_result_diagnostics(
    *,
    command: str,
    argv: list[str],
    cwd: str,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> list[dict[str, Any]]:
    if exit_code == 0:
        return []
    node_check = _node_check_inline_script_diagnostic(command, argv, cwd)
    if node_check:
        return [node_check]
    return []


def _node_check_inline_script_diagnostic(
    command: str,
    argv: list[str],
    cwd: str,
) -> dict[str, Any] | None:
    executable = Path(str(command or "")).name.lower()
    if executable not in {"node", "node.exe"}:
        return None
    if not argv or str(argv[0]).strip().lower() not in {"-c", "--check"}:
        return None
    if len(argv) < 2:
        return None
    candidate = str(argv[1] or "").strip()
    if not candidate or not _looks_like_inline_javascript(candidate, cwd):
        return None
    suggested_file = _extract_read_file_sync_path(candidate)
    suggested: list[dict[str, Any]] = []
    if suggested_file:
        suggested.append({
            "command": "node",
            "args": ["--check", suggested_file],
            "purpose": "syntax-check the JavaScript file without executing it",
        })
    suggested.append({
        "command": "node",
        "args": ["-e", "<inline JavaScript>"],
        "purpose": "run a small inline Node.js probe when execution is intended",
    })
    return {
        "code": "node_check_inline_script",
        "severity": "error",
        "message": (
            "Node -c/--check expects a JavaScript file path, but this call passed "
            "inline JavaScript. Use node --check <file> for syntax-only checks, "
            "or node -e <code> for a small execution probe."
        ),
        "received_arg_preview": candidate[:500],
        "suggested_calls": suggested,
    }


def _looks_like_inline_javascript(value: str, cwd: str) -> bool:
    path_candidate = Path(value)
    if not path_candidate.is_absolute():
        path_candidate = Path(cwd) / value
    try:
        if path_candidate.exists():
            return False
    except OSError:
        pass
    lowered = value.lower()
    inline_markers = (
        "const ",
        "let ",
        "var ",
        "require(",
        "import ",
        "console.",
        "=>",
        ";",
        "\n",
    )
    return any(marker in lowered for marker in inline_markers)


def _extract_read_file_sync_path(value: str) -> str:
    match = re.search(r"readFileSync\(\s*['\"]([^'\"]+)['\"]", value)
    return match.group(1).replace("\\\\", "\\") if match else ""


def register_shell_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="shell.run_command",
            name="执行终端命令",
            description=(
                "在允许工作区或当前任务临时目录内执行终端命令。适合运行构建、测试、安装依赖等操作。"
                "跨平台任务优先使用 command+args 参数数组和 python/node 等可移植入口；不要假设 bash、PowerShell、cp、rm、"
                "Copy-Item 等平台专属语法一定可用。运行 filesystem.write_temp_file 创建的临时脚本时，"
                "可传 cwd='task_temp' 或 use_task_temp=true。不要把 python -m http.server、npm run dev 等长驻服务命令"
                "当作普通验证命令，除非用户明确要求启动服务。命令输出会在运行中持续显示；无输出时会显示心跳。"
                "普通命令超时默认30秒，依赖安装默认600秒，最大900秒。"
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
                    "cwd": {"type": "string", "description": "工作目录（可选，默认当前workspace；传 task_temp 使用任务临时目录）"},
                    "use_task_temp": {"type": "boolean", "default": False, "description": "是否在任务临时目录执行命令"},
                    "timeout": {
                        "type": "integer",
                        "default": 30,
                        "description": "超时秒数（普通命令默认30；依赖安装省略时默认600；最大900）",
                    },
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        ),
        run_command,
    )
