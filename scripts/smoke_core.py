from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.security import PathGuard
from runtime.skills import register_builtin_tools
from runtime.task_runner import TaskRunner
from runtime.task_store import TaskStore
from runtime.tool_registry import ToolRegistry


async def main() -> None:
    workspace = Path.cwd().resolve()
    registry = ToolRegistry()
    register_builtin_tools(registry)

    store = TaskStore()
    runner = TaskRunner(
        registry=registry,
        store=store,
        path_guard=PathGuard([workspace]),
    )

    tools = registry.list_specs()
    print(f"registered tools: {len(tools)}")
    for tool in tools:
        print(f"- {tool['id']}: {tool['name']}")

    scan_task = await runner.submit(
        "filesystem.scan_folder",
        {"path": ".", "max_depth": 2},
        wait=True,
    )
    print(f"scan status: {scan_task.status}")
    print(f"scan file_count: {scan_task.output.get('file_count') if scan_task.output else '-'}")

    search_task = await runner.submit(
        "code.search_text",
        {"path": ".", "query": "本地智能终端", "max_matches": 10},
        wait=True,
    )
    print(f"search status: {search_task.status}")
    print(f"search match_count: {search_task.output.get('match_count') if search_task.output else '-'}")

    if scan_task.status != "success" or search_task.status != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
