"""辅助非流式模型调用的可观察生命周期。

本模块管理一次非流式请求的计时、心跳、取消和审计事实。
它不推断任务意图、不选择工具，也不判断 Run 是否完成。"""

from __future__ import annotations

import asyncio
import inspect
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from runtime.model_providers import generate_chat_completion


MODEL_CALL_SCHEMA_VERSION = "model_call.v1"

ModelGenerator = Callable[..., Awaitable[tuple[str, dict[str, Any]]]]
EventEmitter = Callable[[dict[str, Any]], Any]
EventFlusher = Callable[[], Any]


@dataclass(frozen=True)
class ModelCallPolicy:
    """可选模型辅助运行阶段共享的操作策略。"""

    timeout_seconds: float = 90.0
    heartbeat_interval_seconds: float = 15.0
    blocking: bool = True
    optional: bool = True


AUXILIARY_MODEL_CALL_POLICY = ModelCallPolicy()


class ModelCallTimeoutError(TimeoutError):
    """辅助模型调用超过生命周期预算时抛出。"""


async def run_model_call(
    *,
    purpose: str,
    settings: Any,
    model: str,
    messages: list[dict[str, Any]],
    enable_thinking: bool = True,
    reasoning_effort: str = "medium",
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
    policy: ModelCallPolicy = AUXILIARY_MODEL_CALL_POLICY,
    generate: ModelGenerator = generate_chat_completion,
    emit: EventEmitter | None = None,
    flush: EventFlusher | None = None,
) -> tuple[str, dict[str, Any]]:
    """执行一次非流式模型请求，并提供可观察的生命周期事实。"""

    call_id = str(uuid4())
    normalized_purpose = str(purpose or "auxiliary").strip() or "auxiliary"
    timeout_seconds = max(0.01, float(policy.timeout_seconds))
    heartbeat_seconds = max(0.01, float(policy.heartbeat_interval_seconds))
    started_at = time.monotonic()
    task: asyncio.Task[tuple[str, dict[str, Any]]] | None = None

    def elapsed() -> float:
        return round(max(0.0, time.monotonic() - started_at), 3)

    base_event = {
        "event": "model_call",
        "schema_version": MODEL_CALL_SCHEMA_VERSION,
        "call_id": call_id,
        "purpose": normalized_purpose,
        "model": model,
        "blocking": bool(policy.blocking),
        "optional": bool(policy.optional),
        "timeout_seconds": timeout_seconds,
    }
    await _publish({**base_event, "status": "started", "elapsed_seconds": 0.0}, emit, flush)

    try:
        task = asyncio.create_task(generate(
            settings=settings,
            model=model,
            messages=messages,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            tools=tools,
            tool_choice=tool_choice,
            request_timeout=timeout_seconds,
        ))
        while True:
            if task.done():
                answer, metadata = await task
                return await _complete_model_call(
                    answer=answer,
                    metadata=metadata,
                    base_event=base_event,
                    call_id=call_id,
                    purpose=normalized_purpose,
                    timeout_seconds=timeout_seconds,
                    elapsed_seconds=elapsed(),
                    emit=emit,
                    flush=flush,
                )
            remaining = timeout_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                raise ModelCallTimeoutError(
                    f"model call '{normalized_purpose}' timed out after {timeout_seconds:g}s"
                )
            done, _pending = await asyncio.wait(
                {task},
                timeout=min(heartbeat_seconds, remaining),
            )
            if done:
                answer, metadata = await task
                return await _complete_model_call(
                    answer=answer,
                    metadata=metadata,
                    base_event=base_event,
                    call_id=call_id,
                    purpose=normalized_purpose,
                    timeout_seconds=timeout_seconds,
                    elapsed_seconds=elapsed(),
                    emit=emit,
                    flush=flush,
                )

            await _publish(
                {
                    "event": "heartbeat",
                    "phase": f"model_call:{normalized_purpose}",
                    "call_id": call_id,
                    "purpose": normalized_purpose,
                    "idle_seconds": int(elapsed()),
                    "connection_alive": True,
                },
                emit,
                flush,
            )
    except asyncio.CancelledError:
        await _cancel_task(task)
        await _publish(
            {**base_event, "status": "cancelled", "elapsed_seconds": elapsed()},
            emit,
            flush,
        )
        raise
    except Exception as exc:
        await _cancel_task(task)
        timed_out = isinstance(exc, ModelCallTimeoutError)
        await _publish(
            {
                **base_event,
                "status": "failed",
                "elapsed_seconds": elapsed(),
                "timed_out": timed_out,
                "error": str(exc)[:1000],
            },
            emit,
            flush,
        )
        raise


async def _complete_model_call(
    *,
    answer: str,
    metadata: dict[str, Any],
    base_event: dict[str, Any],
    call_id: str,
    purpose: str,
    timeout_seconds: float,
    elapsed_seconds: float,
    emit: EventEmitter | None,
    flush: EventFlusher | None,
) -> tuple[str, dict[str, Any]]:
    normalized_metadata = dict(metadata or {})
    lifecycle = {
        "schema_version": MODEL_CALL_SCHEMA_VERSION,
        "call_id": call_id,
        "purpose": purpose,
        "status": "completed",
        "elapsed_seconds": elapsed_seconds,
        "timeout_seconds": timeout_seconds,
    }
    normalized_metadata["model_call"] = lifecycle
    await _publish(
        {
            **base_event,
            "status": "completed",
            "elapsed_seconds": elapsed_seconds,
            "provider": normalized_metadata.get("provider"),
            "api_model": normalized_metadata.get("api_model"),
            "usage": normalized_metadata.get("usage"),
        },
        emit,
        flush,
    )
    return answer, normalized_metadata


async def _cancel_task(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _publish(
    payload: dict[str, Any],
    emit: EventEmitter | None,
    flush: EventFlusher | None,
) -> None:
    """避免观察过程失败改变模型调用结果。"""

    try:
        if emit is not None:
            emitted = emit(payload)
            if inspect.isawaitable(emitted):
                await emitted
        if flush is not None:
            flushed = flush()
            if inspect.isawaitable(flushed):
                await flushed
    except Exception:
        return
