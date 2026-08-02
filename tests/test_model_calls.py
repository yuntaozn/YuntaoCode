from __future__ import annotations

import asyncio
from typing import Any

import pytest

from runtime.model_calls import (
    MODEL_CALL_SCHEMA_VERSION,
    ModelCallPolicy,
    ModelCallTimeoutError,
    run_model_call,
)


@pytest.mark.asyncio
async def test_model_call_records_success_and_passes_timeout() -> None:
    events: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}

    async def generate(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        captured.update(kwargs)
        return "answer", {
            "provider": "fake",
            "api_model": "fake-api-model",
            "usage": {"total_tokens": 12},
        }

    answer, metadata = await run_model_call(
        purpose="task_contract",
        settings=object(),
        model="fake-model",
        messages=[{"role": "user", "content": "hello"}],
        policy=ModelCallPolicy(timeout_seconds=2, heartbeat_interval_seconds=0.1),
        generate=generate,
        emit=events.append,
    )

    assert answer == "answer"
    assert captured["request_timeout"] == 2
    assert [event["status"] for event in events if event["event"] == "model_call"] == [
        "started",
        "completed",
    ]
    assert metadata["model_call"]["schema_version"] == MODEL_CALL_SCHEMA_VERSION
    assert metadata["model_call"]["purpose"] == "task_contract"
    assert events[-1]["usage"] == {"total_tokens": 12}


@pytest.mark.asyncio
async def test_model_call_emits_heartbeats_and_times_out() -> None:
    events: list[dict[str, Any]] = []

    async def generate(**_kwargs: Any) -> tuple[str, dict[str, Any]]:
        await asyncio.sleep(10)
        return "late", {}

    with pytest.raises(ModelCallTimeoutError):
        await run_model_call(
            purpose="result_synthesis",
            settings=object(),
            model="slow-model",
            messages=[],
            policy=ModelCallPolicy(
                timeout_seconds=0.04,
                heartbeat_interval_seconds=0.01,
            ),
            generate=generate,
            emit=events.append,
        )

    assert any(event["event"] == "heartbeat" for event in events)
    failed = [
        event
        for event in events
        if event["event"] == "model_call" and event["status"] == "failed"
    ]
    assert len(failed) == 1
    assert failed[0]["timed_out"] is True


@pytest.mark.asyncio
async def test_model_call_records_provider_failure_without_rewriting_it() -> None:
    events: list[dict[str, Any]] = []

    async def generate(**_kwargs: Any) -> tuple[str, dict[str, Any]]:
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await run_model_call(
            purpose="result_synthesis",
            settings=object(),
            model="fake-model",
            messages=[],
            generate=generate,
            emit=events.append,
        )

    failed = events[-1]
    assert failed["status"] == "failed"
    assert failed["timed_out"] is False
    assert failed["error"] == "provider unavailable"


@pytest.mark.asyncio
async def test_model_call_cancellation_cancels_provider_task_and_records_fact() -> None:
    events: list[dict[str, Any]] = []
    provider_cancelled = asyncio.Event()

    async def generate(**_kwargs: Any) -> tuple[str, dict[str, Any]]:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            provider_cancelled.set()
            raise
        return "late", {}

    call = asyncio.create_task(run_model_call(
        purpose="task_contract",
        settings=object(),
        model="fake-model",
        messages=[],
        generate=generate,
        emit=events.append,
    ))
    await asyncio.sleep(0.01)
    call.cancel()

    with pytest.raises(asyncio.CancelledError):
        await call

    assert provider_cancelled.is_set()
    assert events[-1]["event"] == "model_call"
    assert events[-1]["status"] == "cancelled"
