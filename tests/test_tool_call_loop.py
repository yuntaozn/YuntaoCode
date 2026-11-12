from __future__ import annotations

from typing import Any

import pytest

from runtime.tool_call_loop import ToolCallLoop
from runtime.model_providers.client import normalize_tool_call_chunks


def _stream_factory(events: list[dict[str, Any]], calls: list[dict[str, Any]]):
    async def stream(**kwargs: Any):
        calls.append(kwargs)
        for event in events:
            yield event

    return stream


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    [{"index": -1}], [{"index": 10**12}], [{"index": "0"}], [{"index": True}],
    [{"index": None}], [None], ["bad"], "bad",
    [{"index": 0, "function": []}], [{"index": 0, "function": {"arguments": {}}}],
    [{"index": 0, "function": {"name": 123}}],
])
async def test_bad_provider_chunk_invalidates_entire_round_and_preserves_audit(bad):
    valid = {"index": 0, "id": "call-1", "function": {"name": "filesystem.read_file", "arguments": "{}"}}
    emitted = []

    async def flush():
        pass

    # 通过真实 Provider 规范化，确保畸形条目不会在适配层被静默丢弃。
    loop = ToolCallLoop(emit=emitted.append, flush=flush, guidance_pending=lambda: False,
                        stream_factory=_stream_factory([
                            {"tool_calls": normalize_tool_call_chunks([valid])},
                            {"tool_calls": normalize_tool_call_chunks(bad)},
                            {"tool_calls": normalize_tool_call_chunks([valid])},
                            {"finish_reason": "tool_calls", "usage": {"completion_tokens": 12}},
                        ], []))
    result = await loop.run_model_round(
        settings=object(), model="demo", messages=[], tools=[], enable_thinking=False,
        reasoning_effort=None, consecutive_idle_timeouts=0,
        argument_observation_threshold=24000, large_argument_observations=0,
    )
    assert result.tool_call_chunks == []
    assert result.protocol_error in {"invalid_tool_call_index", "invalid_tool_call_chunk"}
    assert result.usage == {"completion_tokens": 12}
    assert emitted[-1]["event"] == "model_round"
    assert emitted[-1]["protocol_error"] == result.protocol_error


@pytest.mark.asyncio
async def test_partial_batch_with_unnamed_call_cannot_execute_named_subset():
    async def flush():
        pass

    loop = ToolCallLoop(emit=lambda _event: None, flush=flush, guidance_pending=lambda: False,
                        stream_factory=_stream_factory([{"tool_calls": [
                            {"index": 0, "function": {"name": "filesystem.read_file", "arguments": "{}"}},
                            {"index": 1, "function": {"arguments": "{}"}},
                        ]}, {"finish_reason": "tool_calls"}], []))
    result = await loop.run_model_round(
        settings=object(), model="demo", messages=[], tools=[], enable_thinking=False,
        reasoning_effort=None, consecutive_idle_timeouts=0,
        argument_observation_threshold=24000, large_argument_observations=0,
    )
    assert result.protocol_error == "incomplete_tool_call_batch"
    assert result.tool_call_chunks == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("protocol", "body", "reasoning", "expected_calls"), [
    ("none", '<toolcall>{"name":"filesystem.read_file","arguments":{"path":"README.md"}}</toolcall>', "", 0),
    ("tagged", '<toolcall>{"name":"filesystem.read_file","arguments":{"path":"README.md"}}</toolcall>', "", 1),
    ("tagged", 'Example only: <toolcall>{"name":"filesystem.read_file","arguments":{"path":"README.md"}}</toolcall>', "", 0),
    ("tagged", '```\n<toolcall>{"name":"filesystem.read_file","arguments":{"path":"README.md"}}</toolcall>\n```', "", 0),
    ("tagged", "Final answer", '<toolcall>{"name":"filesystem.read_file","arguments":{"path":"README.md"}}</toolcall>', 0),
])
async def test_text_calls_require_declared_protocol_and_exact_body(protocol, body, reasoning, expected_calls):
    class Settings:
        def resolve_model(self, model):
            return {"text_tool_protocol": protocol}, {}, "demo"

    async def flush():
        return None

    emitted = []
    loop = ToolCallLoop(emit=emitted.append, flush=flush, guidance_pending=lambda: False,
                        stream_factory=_stream_factory([{"message": body, "reasoning": reasoning}, {"finish_reason": "stop"}], []))
    result = await loop.run_model_round(
        settings=Settings(), model="demo", messages=[], tools=[], enable_thinking=False,
        reasoning_effort=None, consecutive_idle_timeouts=0,
        argument_observation_threshold=24000, large_argument_observations=0, round_index=3,
    )
    assert len(result.tool_call_chunks) == expected_calls
    audit = emitted[-1]
    assert audit["event"] == "model_round"
    assert audit["round"] == 3
    assert audit["named_tool_call_count"] == expected_calls
    assert "reasoning" not in audit
    assert "message" not in audit


@pytest.mark.asyncio
@pytest.mark.parametrize(("events", "expected"), [
    ([{"finish_reason": "tool_calls"}], "missing_tool_call_payload"),
    ([{"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]},
      {"finish_reason": "function_call"}], "missing_tool_call_payload"),
    ([{"message": "Answer"}, {"finish_reason": "stop"}], ""),
    ([{"error": "provider error"}, {"finish_reason": "tool_calls"}], ""),
])
async def test_model_round_reports_missing_native_call_as_protocol_fact(
    events: list[dict[str, Any]], expected: str,
) -> None:
    async def flush() -> None:
        return None

    loop = ToolCallLoop(
        emit=lambda _event: None, flush=flush, guidance_pending=lambda: False,
        stream_factory=_stream_factory(events, []),
    )
    result = await loop.run_model_round(
        settings=object(), model="demo", messages=[], tools=[],
        enable_thinking=False, reasoning_effort=None,
        consecutive_idle_timeouts=0, argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert result.protocol_error == expected
    assert result.fatal == bool(result.model_error)


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
        consecutive_idle_timeouts=1,
        argument_observation_threshold=8,
        large_argument_observations=2,
    )

    assert result.content_parts == ["working"]
    assert result.reasoning_parts == ["inspect facts"]
    assert result.tool_call_chunks[0]["function"]["name"] == "filesystem.read_file"
    assert result.finish_reason == "tool_calls"
    assert result.protocol_error == ""
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
        consecutive_idle_timeouts=first.consecutive_idle_timeouts,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert first.idle_timeout and not first.fatal
    assert first.model_error == ""
    assert first.consecutive_idle_timeouts == 1
    assert second.idle_timeout and second.fatal
    assert second.model_error == "idle"
    assert second.consecutive_idle_timeouts == 2
    assert any(event.get("status") == "idle_timeout" for event in emitted)
    assert any(event.get("event") == "error" for event in emitted)


@pytest.mark.asyncio
async def test_provider_error_is_transport_evidence_without_task_finalization() -> None:
    async def flush() -> None:
        return None

    emitted: list[dict[str, Any]] = []
    loop = ToolCallLoop(
        emit=emitted.append,
        flush=flush,
        guidance_pending=lambda: False,
        stream_factory=_stream_factory([{"error": "provider unavailable"}], []),
    )

    result = await loop.run_model_round(
        settings=object(),
        model="demo",
        messages=[],
        tools=[],
        enable_thinking=False,
        reasoning_effort=None,
        consecutive_idle_timeouts=0,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert result.model_error == "provider unavailable"
    assert result.fatal
    error = next(e for e in emitted if e.get("event") == "error")
    assert error["terminal"] is False
    assert "recoverable" not in error


@pytest.mark.asyncio
async def test_visual_transport_error_retries_with_text_evidence() -> None:
    emitted: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []

    async def flush() -> None:
        return None

    async def stream(**kwargs: Any):
        calls.append(kwargs)
        if len(calls) == 1:
            yield {"error": "HTTP 400: image input is not accepted"}
        else:
            yield {"message": "checked visual facts"}
            yield {"finish_reason": "stop"}

    loop = ToolCallLoop(
        emit=emitted.append,
        flush=flush,
        guidance_pending=lambda: False,
        stream_factory=stream,
    )

    result = await loop.run_model_round(
        settings=object(),
        model="demo",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Runtime visual evidence path: preview.png"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        tools=[],
        enable_thinking=False,
        reasoning_effort=None,
        consecutive_idle_timeouts=0,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert len(calls) == 2
    assert calls[0]["messages"][0]["content"][1]["type"] == "image_url"
    assert isinstance(calls[1]["messages"][0]["content"], str)
    assert "Runtime visual evidence path: preview.png" in calls[1]["messages"][0]["content"]
    assert "image artifact" in calls[1]["messages"][0]["content"]
    assert result.content_parts == ["checked visual facts"]
    assert result.finish_reason == "stop"
    assert result.model_error == ""
    assert result.visual_context_fallback is True
    assert set(result.visual_context_delivery.values()) == {"omitted_transport_fallback"}
    assert result.visual_context_error == "HTTP 400: image input is not accepted"
    assert emitted[-1]["visual_context_delivery"] == result.visual_context_delivery
    assert any(event.get("status") == "visual_context_text_fallback" for event in emitted)


@pytest.mark.asyncio
async def test_empty_visual_stream_does_not_establish_image_receipt():
    async def flush():
        pass

    loop = ToolCallLoop(emit=lambda _event: None, flush=flush, guidance_pending=lambda: False,
                        stream_factory=_stream_factory([], []))
    result = await loop.run_model_round(
        settings=object(), model="demo", messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,pixels"}},
        ]}], tools=[], enable_thinking=False, reasoning_effort=None,
        consecutive_idle_timeouts=0, argument_observation_threshold=24000, large_argument_observations=0,
    )
    assert set(result.visual_context_delivery.values()) == {"unconfirmed"}


@pytest.mark.asyncio
async def test_user_guidance_interrupts_after_preserving_streamed_delta() -> None:
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
        consecutive_idle_timeouts=0,
        argument_observation_threshold=24000,
        large_argument_observations=0,
    )

    assert result.interrupted_by_guidance
    assert result.content_parts == ["partial"]
    status = next(e for e in emitted if e.get("status") == "user_guidance_interrupt")
    assert status["legacy_status"] == "runtime_intervention"
    assert emitted[-1]["event"] == "model_round"
    assert emitted[-1]["interrupted_by_guidance"] is True
