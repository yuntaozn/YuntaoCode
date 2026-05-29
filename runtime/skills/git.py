"""Git version control skills for the local intelligent terminal."""

from __future__ import annotations

import asyncio
from typing import Any

from runtime.tool_registry import ToolRegistry, ToolSpec

MAX_DIFF_OUTPUT = 30_000
MAX_LOG_ENTRIES = 30


async def _run_git(args: list[str], cwd: str, max_output: int = 50_000) -> dict[str, Any]:
    """Run a git command and return structured output."""
    cmd = ["git"] + args
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=30
        )
    except asyncio.TimeoutError:
        return {"exit_code": -1, "stdout": "", "stderr": "git command timed out", "error": True}
    except OSError as exc:
        return {"exit_code": -1, "stdout": "", "stderr": str(exc), "error": True}

    stdout = stdout_bytes.decode("utf-8", errors="replace")[:max_output]
    stderr = stderr_bytes.decode("utf-8", errors="replace")[:10_000]
    return {
        "exit_code": process.returncode or 0,
        "stdout": stdout,
        "stderr": stderr,
        "error": (process.returncode or 0) != 0,
    }


# ---------------------------------------------------------------------------
# git.status
# ---------------------------------------------------------------------------

async def git_status(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    cwd_raw = input_data.get("path")
    cwd = str(context.path_guard.resolve(cwd_raw)) if cwd_raw else str(context.path_guard.workspace_roots[0])

    result = await _run_git(["status", "--porcelain=v1", "-b"], cwd)
    if result["error"]:
        raise ValueError(f"git status failed: {result['stderr']}")

    lines = result["stdout"].strip().splitlines()
    branch = ""
    files: list[dict[str, str]] = []
    for line in lines:
        if line.startswith("##"):
            branch = line[3:].split("...")[0].strip()
        elif len(line) >= 4:
            status_code = line[:2].strip()
            file_path = line[3:].strip()
            files.append({"status": status_code, "path": file_path})

    return {
        "cwd": cwd,
        "branch": branch,
        "files": files,
        "file_count": len(files),
        "clean": len(files) == 0,
    }


# ---------------------------------------------------------------------------
# git.diff
# ---------------------------------------------------------------------------

async def git_diff(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    cwd_raw = input_data.get("path")
    cwd = str(context.path_guard.resolve(cwd_raw)) if cwd_raw else str(context.path_guard.workspace_roots[0])

    staged = bool(input_data.get("staged", False))
    target_file = input_data.get("file")

    args = ["diff"]
    if staged:
        args.append("--cached")
    args += ["--stat", "--patch"]
    if target_file:
        args += ["--", target_file]

    result = await _run_git(args, cwd, max_output=MAX_DIFF_OUTPUT)
    if result["error"]:
        raise ValueError(f"git diff failed: {result['stderr']}")

    output = result["stdout"]
    truncated = len(output) >= MAX_DIFF_OUTPUT
    return {
        "cwd": cwd,
        "staged": staged,
        "file": target_file,
        "diff": output,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# git.log
# ---------------------------------------------------------------------------

async def git_log(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    cwd_raw = input_data.get("path")
    cwd = str(context.path_guard.resolve(cwd_raw)) if cwd_raw else str(context.path_guard.workspace_roots[0])

    count = min(int(input_data.get("count", 10)), MAX_LOG_ENTRIES)
    result = await _run_git(
        ["log", f"-{count}", "--pretty=format:%H|%an|%ai|%s"],
        cwd,
    )
    if result["error"]:
        raise ValueError(f"git log failed: {result['stderr']}")

    commits: list[dict[str, str]] = []
    for line in result["stdout"].strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })

    return {
        "cwd": cwd,
        "commits": commits,
        "count": len(commits),
    }


# ---------------------------------------------------------------------------
# git.commit
# ---------------------------------------------------------------------------

async def git_commit(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    cwd_raw = input_data.get("path")
    cwd = str(context.path_guard.resolve(cwd_raw)) if cwd_raw else str(context.path_guard.workspace_roots[0])

    message = (input_data.get("message") or "").strip()
    if not message:
        raise ValueError("commit message is required")

    # Stage all changes
    add_result = await _run_git(["add", "-A"], cwd)
    if add_result["error"]:
        raise ValueError(f"git add failed: {add_result['stderr']}")

    # Commit
    commit_result = await _run_git(["commit", "-m", message], cwd)
    if commit_result["error"]:
        stderr = commit_result["stderr"] or commit_result["stdout"]
        if "nothing to commit" in stderr.lower() or "nothing to commit" in commit_result["stdout"].lower():
            return {"cwd": cwd, "committed": False, "message": "nothing to commit"}
        raise ValueError(f"git commit failed: {stderr}")

    context.log("info", f"committed: {message[:80]}")
    return {
        "cwd": cwd,
        "committed": True,
        "message": message,
        "output": commit_result["stdout"][:2000],
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_git_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="git.status",
            name="Git 状态",
            description="查看当前 Git 仓库状态，包括分支名和修改/暂存/未跟踪文件列表。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "仓库路径（可选，默认当前workspace）"},
                },
            },
        ),
        git_status,
    )
    registry.register(
        ToolSpec(
            id="git.diff",
            name="Git 差异",
            description="查看 Git diff 输出。可指定查看已暂存(staged)或未暂存的差异，也可指定单个文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "仓库路径（可选）"},
                    "staged": {"type": "boolean", "default": False, "description": "是否查看已暂存的差异"},
                    "file": {"type": "string", "description": "指定文件路径（可选）"},
                },
            },
        ),
        git_diff,
    )
    registry.register(
        ToolSpec(
            id="git.log",
            name="Git 日志",
            description="查看最近的 Git 提交记录，默认显示最近 10 条。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "仓库路径（可选）"},
                    "count": {"type": "integer", "default": 10, "description": "显示条数（最大30）"},
                },
            },
        ),
        git_log,
    )
    registry.register(
        ToolSpec(
            id="git.commit",
            name="Git 提交",
            description="暂存所有变更并提交（git add -A && git commit -m message）。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "仓库路径（可选）"},
                    "message": {"type": "string", "description": "提交信息"},
                },
                "required": ["message"],
            },
            requires_confirmation=True,
        ),
        git_commit,
    )
