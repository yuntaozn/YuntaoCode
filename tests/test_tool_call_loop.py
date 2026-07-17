from __future__ import annotations

from typing import Any

import pytest

from runtime.tool_call_loop import ToolCallLoop


def _stream_factory(events: list[dict[str, Any]], calls: list[dict[str, Any]]):
    async def stream(**kwargs: Any):
        calls.append(kwargs)
        for event in events:
            yield event

    return stream


@pytest.mark.asyncio
async def test_model_round_collects_protocol_facts_without_choosing_strategy() -> None:
    emitted: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    flush_count = 0

    async def flush() -> None:
        nonlocal flush_count
        flush_count += 1

    loop = ToolCallLoop(
        emit=emitted.append,
        flush=flush,
        guidance_pending=lambda: False,
        stream_factory=_stream_factory(
            [
                {
                    "request_budget": {
                        "context_limit": 8192,
                        "tools_pruned": 2,
                    }
                },
                {
                    "heartbeat": True,
                    "message": "still running",
                    "idle_seconds": 8,
                },
                {"message": "working", "reasoning": "inspect facts"},
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {
                                "name": "filesystem.read_file",
                                "arguments": '{"path":"D:/demo/readme.md"}',
                            },
                        }
                    ]
                },
                {
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                    "finish_reason": "tool_calls",
                },
            ],
            calls,
        ),
    )

    result = await loop.run_model_round(
        settings=object(),
        model="demo-model",
        messages=[{"role": "user", "content": "inspect"}],
        tools=[{"type": "function", "function": {"name": "filesystem__read_file"}}],
        enable_thinking=True,
        reasoning_effort="medium",
        has_runtime_facts=False,
        consecutive_idle_timeouts=1,
        argument_observation_threshold=8,
        large_argument_observations=2,
    )

    assert result.content_parts == ["working"]
    assert result.reasoning_parts == ["inspect facts"]
    assert result.tool_call_chunks[0]["function"]["name"] == "filesystem.read_file"
    assert result.finish_reason == "tool_calls"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 4}
    assert result.request_budget == {"context_limit": 8192, "tools_pruned": 2}
    assert result.consecutive_idle_timeouts == 0
    assert result.large_argument_observations == 3
    assert calls[0]["tool_choice"] is None
    assert any(event.get("event") == "heartbeat" for event in emitted)
    assert any(event.get("status") == "tool_argument_stream_observed_large" for event in emitted)
    assert flush_count >= 5


@pytest.mark.asyncio
async def test_idle_timeout_is_retryable_once_then_fatal() -> None:
    emitted: list[dict[str, Any]] = []

    async def flush() -> None:
        return None

    loop = ToolCallLoop(
        emit=emitted.append,
        flush=flush,
        guidance_pending=lambda: False,
        stream_factory=_stream_factory(
            [{"error": "idle", "idle_timeout": True}],
            [],
        ),
    )
    first = await loop.run_model_round(
        settings=object(),
        model="demo",
        messages=[],
        tools=[],
        enable_thinking=False,
        reasoning_effort=None,
        has_runtime_facts=False,
        consecutive_idle_timeouts=0,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )
    second = await loop.run_model_round(
        settings=object(),
        model="demo",
        messages=[],
        tools=[],
        enable_thinking=False,
        reasoning_effort=None,
        has_runtime_facts=False,
        consecutive_idle_timeouts=first.consecutive_idle_timeouts,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert first.idle_timeout and not first.fatal
    assert first.consecutive_idle_timeouts == 1
    assert second.idle_timeout and second.fatal
    assert second.consecutive_idle_timeouts == 2
    assert any(event.get("status") == "idle_timeout" for event in emitted)
    assert any(event.get("event") == "error" for event in emitted)


@pytest.mark.asyncio
async def test_provider_error_reports_whether_runtime_facts_allow_finalization() -> None:
    async def flush() -> None:
        return None

    emitted: list[dict[str, Any]] = []
    loop = ToolCallLoop(
        emit=emitted.append,
        flush=flush,
        guidance_pending=lambda: False,
        stream_factory=_stream_factory([{"error": "provider unavailable"}], []),
    )

    recoverable = await loop.run_model_round(
        settings=object(),
        model="demo",
        messages=[],
        tools=[],
        enable_thinking=False,
        reasoning_effort=None,
        has_runtime_facts=True,
        consecutive_idle_timeouts=0,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert recoverable.model_error == "provider unavailable"
    assert not recoverable.fatal
    assert emitted[-1]["recoverable"] is True


@pytest.mark.asyncio
async def test_runtime_guidance_interrupts_after_preserving_streamed_delta() -> None:
    emitted: list[dict[str, Any]] = []
    guidance_checks = 0

    async def flush() -> None:
        return None

    def guidance_pending() -> bool:
        nonlocal guidance_checks
        guidance_checks += 1
        return guidance_checks >= 1

    loop = ToolCallLoop(
        emit=emitted.append,
        flush=flush,
        guidance_pending=guidance_pending,
        stream_factory=_stream_factory(
            [{"message": "partial"}, {"message": "should not be consumed"}],
            [],
        ),
    )

    result = await loop.run_model_round(
        settings=object(),
        model="demo",
        messages=[],
        tools=[],
        enable_thinking=False,
        reasoning_effort=None,
        has_runtime_facts=False,
        consecutive_idle_timeouts=0,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert result.interrupted_by_guidance
    assert result.content_parts == ["partial"]
    assert emitted[-1]["status"] == "runtime_intervention"
