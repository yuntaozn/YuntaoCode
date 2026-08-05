"""Shell 命令的纯操作事实。

这些事实用于调整执行与展示，不路由用户意图，也不决定模型是否应执行命令。"""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Any


@dataclass(frozen=True)
class ShellCommandFacts:
    role: str = "command"
    long_running: bool = False
    default_timeout: int = 30
    operation_label: str = "执行终端命令"


def shell_command_facts(command: Any, args: Any = None) -> ShellCommandFacts:
    argv = _normalize_tokens(args)
    executable = _executable_name(command)
    if not argv:
        executable, argv = _split_inline_command(command, executable)
    lowered = [item.lower() for item in argv]

    if _is_python_install(executable, lowered) or _is_package_manager_install(
        executable,
        lowered,
    ):
        return ShellCommandFacts(
            role="dependency_install",
            long_running=True,
            default_timeout=600,
            operation_label="安装或更新运行依赖",
        )
    return ShellCommandFacts()


def _executable_name(command: Any) -> str:
    text = str(command or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1].lower()


def _normalize_tokens(args: Any) -> list[str]:
    if args is None:
        return []
    if isinstance(args, (list, tuple)):
        return [str(item).strip() for item in args]
    return [str(args).strip()]


def _split_inline_command(command: Any, fallback_executable: str) -> tuple[str, list[str]]:
    text = str(command or "").strip()
    if not text or not any(char.isspace() for char in text):
        return fallback_executable, []
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        return fallback_executable, []
    if len(tokens) < 2:
        return fallback_executable, []
    executable = _executable_name(tokens[0].strip("\"'"))
    argv = [str(item).strip("\"'") for item in tokens[1:]]
    return executable, argv


def _is_python_install(executable: str, argv: list[str]) -> bool:
    is_python = executable in {"py", "py.exe"} or executable.startswith("python")
    if not is_python or len(argv) < 3 or argv[0] != "-m":
        return False
    module = argv[1]
    action = argv[2]
    return (module == "pip" and action == "install") or (
        module == "playwright" and action == "install"
    )


def _is_package_manager_install(executable: str, argv: list[str]) -> bool:
    executable = executable.removesuffix(".cmd").removesuffix(".exe")
    if not argv:
        return False
    action = argv[0]
    actions = {
        "pip": {"install"},
        "pip3": {"install"},
        "uv": {"add", "sync"},
        "poetry": {"add", "install", "update"},
        "npm": {"add", "ci", "i", "install", "update"},
        "pnpm": {"add", "i", "install", "update"},
        "yarn": {"add", "install", "up", "upgrade"},
        "bun": {"add", "install", "update"},
    }
    if action in actions.get(executable, set()):
        return True
    if executable in {"npx", "pnpx", "bunx"}:
        return len(argv) >= 2 and argv[0] == "playwright" and argv[1] == "install"
    if executable == "uv" and len(argv) >= 2:
        return argv[0] == "pip" and argv[1] == "install"
    return False
