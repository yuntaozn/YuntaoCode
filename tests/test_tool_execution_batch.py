from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.tool_execution_batch import ToolExecutionBatch, ToolExecutionState


class FakeToolExecutionHost:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = list(results)
        self.events: list[dict[str, Any]] = []
        self.executed: list[str] = []
        self.active_tool_events: list[dict[str, Any]] = []

    async def _wait_if_paused(self) -> None:
        return None

    def _tool_call_details(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        function = tool_call["function"]
        name = str(function["name"])
        return tool_name_map.get(name, name), dict(function.get("arguments") or {})

    def _skipped_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_id: str,
        arguments: dict[str, Any],
        *,
        reason: str,
        message: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        event = {
            "tool": tool_id,
            "status": "failure",
            "input": arguments,
            "error": message,
            "output": {"reason": reason},
        }
        return self._tool_message(tool_call, event), event

    def _is_recoverable_write_failure(
        self,
        tool_id: str,
        event: dict[str, Any],
    ) -> bool:
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        return (
            tool_id == "filesystem.write_file"
            and (
                output.get("reason") == "truncated_tool_call"
                or "repairable" in str(event.get("error") or "")
            )
        )

    def _write_repair_prompt(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        event: dict[str, Any],
        workspace_path: str,
    ) -> str:
        return f"repair advisory for {tool_id} in {workspace_path}"

    def _mark_next_plan_step_running(
        self,
        execution_plan: dict[str, Any] | None,
        tool_call: dict[str, Any],
    ) -> int | None:
        if not execution_plan:
            return None
        execution_plan["steps"][0]["status"] = "running"
        return 0

    def _finish_plan_step(
        self,
        execution_plan: dict[str, Any],
        step_index: int,
        tool_event: dict[str, Any],
    ) -> None:
        execution_plan["steps"][step_index]["status"] = (
            "completed" if tool_event.get("status") == "success" else "failed"
        )

    def _set_active_tool_events(self, tool_events: list[dict[str, Any]]) -> None:
        self.active_tool_events = list(tool_events)

    def _is_recon_tool(self, tool_id: str) -> bool:
        return tool_id == "filesystem.read_file"

    def _tool_signature(self, tool_id: str, arguments: dict[str, Any]) -> str:
        return f"{tool_id}:{json.dumps(arguments, sort_keys=True)}"

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
        workspace_path: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.executed.append(str(tool_call["id"]))
        event = self.results.pop(0)
        return self._tool_message(tool_call, event), event

    def _is_write_tool(self, tool_id: str) -> bool:
        return tool_id == "filesystem.write_file"

    def _read_file_range_record(
        self,
        arguments: dict[str, Any],
        tool_event: dict[str, Any],
    ) -> dict[str, Any]:
        return {"path": arguments.get("path"), "start_line": 1, "end_line": 20}

    def write_event(self, payload: dict[str, Any]) -> None:
        self.events.append(payload)

    async def flush(self, include_footers: bool = False) -> None:
        return None

    @staticmethod
    def _tool_message(
        tool_call: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": tool_call["function"]["name"],
            "content": json.dumps(event, ensure_ascii=False),
        }


def _call(call_id: str, tool_id: str, **arguments: Any) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": tool_id, "arguments": arguments},
    }


@pytest.mark.asyncio
async def test_tool_responses_precede_repair_advisories_for_entire_batch() -> None:
    host = FakeToolExecutionHost([
        {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "a.txt"},
            "error": "repairable write failure",
        },
        {
            "tool": "filesystem.read_file",
            "status": "success",
            "input": {"path": "a.txt"},
            "output": {"path": "a.txt"},
        },
    ])
    batch = ToolExecutionBatch(host)

    result = await batch.execute(
        tool_calls=[
            _call("call_1", "filesystem.write_file", path="a.txt", content="text"),
            _call("call_2", "filesystem.read_file", path="a.txt"),
        ],
        tool_name_map={},
        workspace_path="D:/workspace",
        execution_plan=None,
        finish_reason="tool_calls",
        previous_tool_events=[],
        state=ToolExecutionState(),
    )

    assert [message["role"] for message in result.model_messages] == [
        "tool",
        "tool",
        "system",
    ]
    assert result.model_messages[2]["content"].startswith("repair advisory")
    assert result.state.write_repair_mode
    assert result.state.read_file_ranges[0]["path"] == "a.txt"
    assert len(host.active_tool_events) == 2


@pytest.mark.asyncio
async def test_truncated_batch_records_failure_without_executing_tool() -> None:
    host = FakeToolExecutionHost([])
    batch = ToolExecutionBatch(host)

    result = await batch.execute(
        tool_calls=[
            _call("call_1", "filesystem.write_file", path="large.html", content="partial")
        ],
        tool_name_map={},
        workspace_path="D:/workspace",
        execution_plan=None,
        finish_reason="length",
        previous_tool_events=[],
        state=ToolExecutionState(),
    )

    assert host.executed == []
    assert result.tool_events[0]["output"]["reason"] == "truncated_tool_call"
    assert [message["role"] for message in result.model_messages] == ["tool", "system"]
    assert result.state.write_repair_mode


@pytest.mark.asyncio
async def test_duplicate_recon_is_reported_as_fact_without_changing_route() -> None:
    call = _call("call_1", "filesystem.read_file", path="readme.md")
    host = FakeToolExecutionHost([
        {
            "tool": "filesystem.read_file",
            "status": "success",
            "input": {"path": "readme.md"},
            "output": {"path": "readme.md"},
        }
    ])
    signature = host._tool_signature("filesystem.read_file", {"path": "readme.md"})
    batch = ToolExecutionBatch(host)

    result = await batch.execute(
        tool_calls=[call],
        tool_name_map={},
        workspace_path="D:/workspace",
        execution_plan=None,
        finish_reason="tool_calls",
        previous_tool_events=[],
        state=ToolExecutionState(
            seen_recon_signatures={signature},
            recon_tool_count=1,
        ),
    )

    assert host.executed == ["call_1"]
    assert result.state.recon_tool_count == 1
    assert [message["role"] for message in result.model_messages] == ["tool", "system"]
    assert "repeats the same tool" in result.model_messages[1]["content"]


@pytest.mark.asyncio
async def test_plan_step_events_remain_auditable() -> None:
    host = FakeToolExecutionHost([
        {
            "tool": "filesystem.write_file",
            "status": "success",
            "input": {"path": "done.txt"},
            "output": {"path": "done.txt"},
        }
    ])
    plan = {"steps": [{"title": "write", "status": "pending"}]}

    result = await ToolExecutionBatch(host).execute(
        tool_calls=[
            _call("call_1", "filesystem.write_file", path="done.txt", content="done")
        ],
        tool_name_map={},
        workspace_path="D:/workspace",
        execution_plan=plan,
        finish_reason="tool_calls",
        previous_tool_events=[],
        state=ToolExecutionState(write_repair_mode=True),
    )

    assert plan["steps"][0]["status"] == "completed"
    assert [event["event"] for event in host.events] == [
        "plan_step",
        "tool",
        "plan_step",
    ]
    assert not result.state.write_repair_mode
