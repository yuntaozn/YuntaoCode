from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.conversations import ConversationMessagesStreamHandler


class _Registry:
    def get(self, tool_id: str) -> Any:
        return SimpleNamespace(spec=SimpleNamespace(name=tool_id))


@pytest.mark.asyncio
async def test_malformed_tool_arguments_are_not_executed() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler.runtime = SimpleNamespace(registry=_Registry())
    tool_call = {
        "id": "call-1",
        "function": {
            "name": "filesystem__write_file",
            "arguments": '{"path":"demo.html","content":"partial',
        },
    }

    _message, event = await handler._execute_tool_call(
        tool_call,
        {"filesystem__write_file": "filesystem.write_file"},
        ".",
    )

    assert event["status"] == "failure"
    assert event["output"]["reason"] == "malformed_tool_arguments"


@pytest.mark.asyncio
async def test_non_object_tool_arguments_are_not_executed() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler.runtime = SimpleNamespace(registry=_Registry())
    tool_call = {
        "id": "call-2",
        "function": {
            "name": "filesystem__write_file",
            "arguments": '["demo.html", "content"]',
        },
    }

    _message, event = await handler._execute_tool_call(
        tool_call,
        {"filesystem__write_file": "filesystem.write_file"},
        ".",
    )

    assert event["status"] == "failure"
    assert event["output"]["reason"] == "non_object_tool_arguments"
