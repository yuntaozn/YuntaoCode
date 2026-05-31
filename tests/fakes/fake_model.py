"""Fake model stream for behaviour-driven testing of the agent loop.

``FakeModelStream`` replays a pre-scripted sequence of events, replacing
the real LLM streaming call.  Each event dict can contain:

- ``{"message": "..."}``              — a text delta
- ``{"tool_calls": [...]}``           — tool call deltas
- ``{"delay": 0.05}``                — simulate latency
- ``{"error": "..."}``                — simulate an upstream error

Helper ``script_*`` functions return ready-made scripts for common
scenarios.
"""

from __future__ import annotations

import asyncio
from typing import Any


def make_tool_call(
    tool_name: str,
    arguments_json: str,
    *,
    call_id: str = "",
) -> dict[str, Any]:
    """Build a single tool-call chunk as the streaming API would emit it."""
    return {
        "index": 0,
        "id": call_id or f"call_{tool_name}",
        "type": "function",
        "function": {"name": tool_name, "arguments": arguments_json},
    }


class FakeModelStream:
    """Replay a scripted event sequence, mimicking the streaming protocol."""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self._script = script

    async def __aiter__(self):
        for event in self._script:
            if event.get("delay"):
                await asyncio.sleep(event["delay"])
            yield event


# ---------------------------------------------------------------------------
# Pre-built scripts
# ---------------------------------------------------------------------------

def script_read_then_answer() -> list[dict[str, Any]]:
    """Model reads a file, then gives a text answer (no write)."""
    return [
        {"tool_calls": [make_tool_call("filesystem__read_file", '{"path":"src/main.py"}')]},
        {"message": "分析完成，代码结构如下..."},
    ]


def script_write_task() -> list[dict[str, Any]]:
    """Model reads, then writes, then confirms."""
    return [
        {"tool_calls": [make_tool_call("filesystem__read_file", '{"path":"src/main.py"}')]},
        {
            "tool_calls": [
                make_tool_call(
                    "code__edit_file",
                    '{"path":"src/main.py","old_text":"pass","new_text":"print(\\"hello\\")"}',
                )
            ]
        },
        {"message": "修改完成。"},
    ]


def script_write_fail_then_retry() -> list[dict[str, Any]]:
    """Model writes, fails, reads again, retries successfully."""
    return [
        {"tool_calls": [make_tool_call("filesystem__read_file", '{"path":"src/main.py"}')]},
        {
            "tool_calls": [
                make_tool_call(
                    "code__edit_file",
                    '{"path":"src/main.py","old_text":"wrong_text","new_text":"fixed"}',
                )
            ]
        },
        # After failure the model reads again
        {"tool_calls": [make_tool_call("filesystem__read_file", '{"path":"src/main.py"}')]},
        {
            "tool_calls": [
                make_tool_call(
                    "code__edit_file",
                    '{"path":"src/main.py","old_text":"correct_old","new_text":"fixed"}',
                )
            ]
        },
        {"message": "修复完成。"},
    ]


def script_recon_loop() -> list[dict[str, Any]]:
    """Model keeps reading/searching without ever writing."""
    return [
        {"tool_calls": [make_tool_call("filesystem__scan_folder", '{"path":"."}')]},
        {"tool_calls": [make_tool_call("filesystem__read_file", '{"path":"src/a.py"}')]},
        {"tool_calls": [make_tool_call("filesystem__read_file", '{"path":"src/b.py"}')]},
        {"tool_calls": [make_tool_call("code__search_text", '{"query":"TODO","path":"src"}')]},
        {"message": "分析结果如下..."},
    ]


def script_dangling_answer() -> list[dict[str, Any]]:
    """Model produces a dangling action message (says it will do something but doesn't)."""
    return [
        {"message": "让我先验证一下修改结果："},
    ]
