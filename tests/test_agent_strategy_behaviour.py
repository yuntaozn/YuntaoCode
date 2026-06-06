"""Behaviour-level smoke tests for extracted agent strategy helpers.

These tests use fake model/tool streams to cover strategy interactions that are
larger than single pure functions but still avoid the real model, filesystem,
shell, or Tornado request stack.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.agent_strategy.classifiers import (
    complete_tool_calls,
    has_successful_write,
    is_recon_tool,
    is_recoverable_write_failure,
    is_write_tool,
    has_unresolved_tool_call_markup,
    looks_like_dangling_action,
    merge_tool_call_chunks,
    parse_tool_arguments_strict,
    progress_key,
)
from runtime.agent_strategy.plan_tracker import normalize_tool_id
from runtime.agent_strategy.prompts import (
    dangling_action_prompt,
    malformed_tool_call_prompt,
    progress_observer_prompt,
    recon_budget_prompt,
    write_repair_prompt,
)
from tests.fakes.fake_model import (
    FakeModelStream,
    script_dangling_answer,
    script_read_then_answer,
    script_recon_loop,
    script_write_fail_then_retry,
)
from tests.fakes.fake_tool_runner import FakeToolRunner


async def run_scripted_loop(
    script: list[dict[str, Any]],
    runner: FakeToolRunner,
) -> tuple[str, list[dict[str, Any]]]:
    """Run a tiny model/tool loop using the extracted strategy helpers."""
    content_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []

    async for item in FakeModelStream(script):
        if item.get("message"):
            content_parts.append(str(item["message"]))

        chunks = item.get("tool_calls") or []
        if not chunks:
            continue

        calls: list[dict[str, Any]] = []
        merge_tool_call_chunks(calls, chunks)
        for call in complete_tool_calls(calls, len(tool_events)):
            function = call.get("function") or {}
            tool_id = normalize_tool_id(function.get("name"))
            raw_args = str(function.get("arguments") or "{}")
            arguments, argument_error = parse_tool_arguments_strict(raw_args)
            if argument_error:
                tool_events.append({
                    "tool": tool_id,
                    "status": "failure",
                    "input": {},
                    "output": {"reason": argument_error},
                    "error": argument_error,
                })
                continue

            result = await runner.run(tool_id, arguments)
            tool_events.append({
                "tool": tool_id,
                "status": result.get("status"),
                "input": arguments,
                "output": result.get("output") or {},
                "error": result.get("error") or "",
            })

    return "".join(content_parts), tool_events


@pytest.mark.asyncio
async def test_fake_read_only_script_never_executes_write_tools() -> None:
    runner = FakeToolRunner()

    content, events = await run_scripted_loop(script_read_then_answer(), runner)

    assert "分析完成" in content
    assert runner.call_count == 1
    assert all(not is_write_tool(tool_id) for tool_id, _ in runner.executed)
    assert events == [
        {
            "tool": "filesystem.read_file",
            "status": "success",
            "input": {"path": "src/main.py"},
            "output": {"path": "src/main.py"},
            "error": "",
        }
    ]


@pytest.mark.asyncio
async def test_fake_write_failure_is_recoverable_and_retry_can_succeed() -> None:
    attempts = {"count": 0}

    def edit_outcome(tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {"status": "failure", "error": "old_text not found in file"}
        return {"status": "success", "output": {"path": arguments.get("path")}}

    runner = FakeToolRunner({"code.edit_file": edit_outcome})

    _, events = await run_scripted_loop(script_write_fail_then_retry(), runner)

    write_events = [event for event in events if event["tool"] == "code.edit_file"]
    assert len(write_events) == 2
    assert is_recoverable_write_failure("code.edit_file", write_events[0])
    assert has_successful_write(events)

    repair_prompt = write_repair_prompt(
        "code.edit_file",
        write_events[0]["input"],
        write_events[0],
        "D:/workspace",
    )
    assert "old_text" in repair_prompt
    assert "不能用文字声称已经修改完成" in repair_prompt


@pytest.mark.asyncio
async def test_fake_recon_loop_produces_progress_signal_without_write() -> None:
    runner = FakeToolRunner()

    _, events = await run_scripted_loop(script_recon_loop(), runner)

    assert len(events) == 4
    assert all(is_recon_tool(event["tool"]) for event in events)
    assert not has_successful_write(events)
    assert progress_key(events, "coding") != "[]"

    nudge = progress_observer_prompt(
        "D:/workspace",
        "explorer",
        events,
        True,
        "recon-loop",
    )
    assert "尚未写入" in nudge
    assert "recon-loop" in nudge
    assert "4 次" in recon_budget_prompt(4, "D:/workspace")


@pytest.mark.asyncio
async def test_fake_dangling_answer_gets_correction_prompt() -> None:
    runner = FakeToolRunner()

    content, events = await run_scripted_loop(script_dangling_answer(), runner)

    assert events == []
    assert looks_like_dangling_action(content)
    prompt = dangling_action_prompt("D:/workspace", content, events, "coding")
    assert "悬空动作" in prompt
    assert "不要只说" in prompt


def test_dangling_action_prompt_respects_declared_capability_boundary() -> None:
    prompt = dangling_action_prompt(
        "D:/workspace",
        "I will create the file next.",
        [],
        "terminal",
        allow_state_change=False,
    )

    assert "当前任务契约没有声明本地变更" in prompt
    assert "不要创建或修改文件" in prompt


def test_malformed_tool_call_gets_structured_call_correction_prompt() -> None:
    content = "让我先读取文件。<toolcall>filesystem.read_file</toolcall>"

    assert has_unresolved_tool_call_markup(content)
    prompt = malformed_tool_call_prompt("D:/workspace", content)
    assert "不可执行的工具调用格式" in prompt
    assert "结构化工具调用" in prompt
    assert "明确 path 参数" in prompt
