"""单个模型工具轮次的 Provider 协议循环。

本模块管理模型流式执行一个轮次时产生的传输事实：内容与推理增量、
工具调用参数片段、请求预算、心跳、Provider 错误、空闲超时和运行时指引中断。
它不判断任务意图、工具路线、完成状态或验证结论。"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, AsyncIterator, Awaitable, Callable

from runtime.agent_strategy.classifiers import (
    ToolCallProtocolError,
    merge_tool_call_chunks,
    tool_call_arguments_size,
    extract_declared_text_tool_calls,
)
from runtime.model_harness import ModelHarness, default_model_harness, image_context_refs
from runtime.model_providers.client import stream_chat_completion


StreamFactory = Callable[..., AsyncIterator[dict[str, Any]]]
EmitEvent = Callable[[dict[str, Any]], None]
FlushEvents = Callable[[], Awaitable[None]]
GuidancePending = Callable[[], bool]


@dataclass
class ModelRoundResult:
    """从一次 Provider 流中观察到的事实。"""

    content_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    tool_call_chunks: list[dict[str, Any]] = field(default_factory=list)
    finish_reasons: list[str] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    request_budget: dict[str, Any] | None = None
    model_error: str = ""
    protocol_error: str = ""
    idle_timeout: bool = False
    fatal: bool = False
    interrupted_by_guidance: bool = False
    consecutive_idle_timeouts: int = 0
    large_argument_observations: int = 0
    visual_context_fallback: bool = False
    visual_context_delivery: dict[str, str] = field(default_factory=dict)
    visual_context_error: str = ""
    text_tool_call_recovered: bool = False
    text_tool_protocol: str = "none"

    @property
    def finish_reason(self) -> str:
        return self.finish_reasons[-1] if self.finish_reasons else ""


class ToolCallLoop:
    """流式执行一个模型轮次，但不作语义执行决策。"""

    def __init__(
        self,
        *,
        emit: EmitEvent,
        flush: FlushEvents,
        guidance_pending: GuidancePending,
        stream_factory: StreamFactory = stream_chat_completion,
        harness: ModelHarness | None = None,
    ) -> None:
        self._emit = emit
        self._flush = flush
        self._guidance_pending = guidance_pending
        self._stream_factory = stream_factory
        self._harness = harness or default_model_harness()

    async def run_model_round(
        self,
        *,
        settings: Any,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        enable_thinking: bool,
        reasoning_effort: str | None,
        consecutive_idle_timeouts: int,
        argument_observation_threshold: int,
        large_argument_observations: int,
        round_index: int = 0,
    ) -> ModelRoundResult:
        started_at = monotonic()
        result = ModelRoundResult(
            consecutive_idle_timeouts=consecutive_idle_timeouts,
            large_argument_observations=large_argument_observations,
        )
        large_arguments_reported = False
        visual_fallback_attempted = False
        wire_tool_call_items: int | None = None
        tool_call_fragment_count = 0
        request = self._harness.prepare_round_request(
            settings=settings,
            model=model,
            messages=messages,
            tools=tools or None,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            tool_choice=None,
        )
        result.text_tool_protocol = request.harness.text_tool_protocol
        requested_images = image_context_refs(request.messages)

        while True:
            retry_without_visual_context = False
            async for event in self._stream_factory(**request.to_stream_kwargs()):
                budget = event.get("request_budget")
                if budget:
                    budget_info = budget if isinstance(budget, dict) else {}
                    result.request_budget = budget_info
                    await self._publish({"event": "request_budget", "budget": budget_info})
                    if budget_info.get("tools_pruned"):
                        await self._publish({
                            "event": "status",
                            "status": "request_budget_adjusted",
                            "message": (
                                f"本地模型上下文为 {budget_info.get('context_limit')} tokens，"
                                f"已裁剪 {budget_info.get('tools_pruned')} 个工具说明以适配请求。"
                            ),
                            "request_budget": budget_info,
                        })
                    continue

                if event.get("heartbeat"):
                    await self._publish({
                        "event": "heartbeat",
                        "message": event.get("message") or "模型仍在处理，请稍候",
                        "idle_seconds": event.get("idle_seconds"),
                        "phase": event.get("phase") or "model_stream",
                        "connection_alive": event.get("connection_alive", True),
                    })
                    continue

                if event.get("error"):
                    if event.get("idle_timeout"):
                        result.idle_timeout = True
                        result.consecutive_idle_timeouts += 1
                        if result.consecutive_idle_timeouts >= 2:
                            result.fatal = True
                            result.model_error = str(event.get("error") or "")
                            await self._publish({
                                "event": "error",
                                "error": result.model_error,
                                "terminal": False,
                            })
                        else:
                            await self._publish({
                                "event": "status",
                                "status": "idle_timeout",
                                "message": "模型响应超时，正在重试...",
                                "error": str(event.get("error") or ""),
                            })
                        break

                    if (
                        not visual_fallback_attempted
                        and self._harness.has_visual_context(request)
                        and self._harness.is_visual_transport_error(event.get("error"))
                    ):
                        visual_fallback_attempted = True
                        result.visual_context_fallback = True
                        result.visual_context_error = str(event.get("error") or "")[:500]
                        request = self._harness.downgrade_visual_context(request)
                        result.tool_call_chunks.clear()
                        result.content_parts.clear()
                        result.reasoning_parts.clear()
                        result.protocol_error = ""
                        retry_without_visual_context = True
                        await self._publish({
                            "event": "status",
                            "status": "visual_context_text_fallback",
                            "message": (
                                "携带图片的请求未成功，已保留视觉证据的文字事实并尝试文字请求。"
                            ),
                        })
                        break

                    result.model_error = str(event.get("error") or "")
                    result.fatal = True
                    await self._publish({
                        "event": "error",
                        "error": result.model_error,
                        "terminal": False,
                    })
                    break

                emitted_delta = False
                if isinstance(event.get("wire_tool_call_items"), int):
                    wire_tool_call_items = (wire_tool_call_items or 0) + event["wire_tool_call_items"]
                if event.get("message"):
                    result.consecutive_idle_timeouts = 0
                    result.content_parts.append(str(event["message"]))
                    self._emit({"event": "message", "message": event["message"]})
                    emitted_delta = True
                if event.get("reasoning"):
                    result.consecutive_idle_timeouts = 0
                    result.reasoning_parts.append(str(event["reasoning"]))
                    self._emit({"event": "reasoning", "reasoning": event["reasoning"]})
                    emitted_delta = True
                if "tool_calls" in event:
                    chunks = event["tool_calls"]
                    tool_call_fragment_count += len(chunks) if isinstance(chunks, list) else 1
                    result.consecutive_idle_timeouts = 0
                    if not result.protocol_error:
                        try:
                            merge_tool_call_chunks(result.tool_call_chunks, chunks)
                        except ToolCallProtocolError as exc:
                            # 一次无效片段使整轮调用失效，不能执行此前已累积的部分批次。
                            result.protocol_error = str(exc)
                            result.tool_call_chunks.clear()
                    argument_size = tool_call_arguments_size(result.tool_call_chunks)
                    if (
                        argument_size > argument_observation_threshold
                        and not large_arguments_reported
                    ):
                        large_arguments_reported = True
                        result.large_argument_observations += 1
                        self._emit({
                            "event": "status",
                            "status": "tool_argument_stream_observed_large",
                            "message": "检测到工具参数较大，运行时继续等待模型完成；若最终参数不完整，将作为事实反馈给模型自行修正。",
                            "argument_chars": argument_size,
                            "observation_threshold_chars": argument_observation_threshold,
                            "observation_count": result.large_argument_observations,
                        })
                        emitted_delta = True
                if event.get("usage") and isinstance(event.get("usage"), dict):
                    result.usage = event["usage"]
                if event.get("finish_reason") is not None:
                    result.finish_reasons.append(str(event["finish_reason"]))

                if emitted_delta or event.get("usage") or event.get("finish_reason") is not None:
                    await self._flush()
                if self._guidance_pending():
                    result.interrupted_by_guidance = True
                    await self._publish({
                        "event": "status",
                        "status": "user_guidance_interrupt",
                        "message": "收到插话，正在暂停当前输出并重新审视任务",
                        "legacy_status": "runtime_intervention",
                    })
                    break

            if retry_without_visual_context:
                continue
            break

        if not result.protocol_error and not result.model_error and not result.idle_timeout and not result.interrupted_by_guidance and not result.tool_call_chunks:
            calls = extract_declared_text_tool_calls(
                "".join(result.content_parts), request.harness.text_tool_protocol, round_index,
            )
            if calls:
                result.tool_call_chunks = calls
                result.text_tool_call_recovered = True
        if (
            not result.model_error
            and not result.protocol_error
            and not result.idle_timeout
            and not result.interrupted_by_guidance
            and result.finish_reason in {"tool_calls", "function_call"}
            and not any(
                str((chunk.get("function") or {}).get("name") or "").strip()
                for chunk in result.tool_call_chunks
            )
        ):
            result.protocol_error = "missing_tool_call_payload"
        if not result.protocol_error and any(
            not str((chunk.get("function") or {}).get("name") or "").strip()
            for chunk in result.tool_call_chunks
        ):
            result.protocol_error = "incomplete_tool_call_batch"
        if result.protocol_error:
            result.tool_call_chunks.clear()
        delivery_status = (
            "omitted_transport_fallback" if result.visual_context_fallback else
            "unconfirmed" if result.model_error or result.idle_timeout or result.interrupted_by_guidance
            or not (result.finish_reasons or result.content_parts or result.reasoning_parts or tool_call_fragment_count or result.usage)
            else "accepted"
        )
        result.visual_context_delivery = {ref: delivery_status for ref in requested_images}
        await self._publish({
            "event": "model_round", "schema_version": "model_round.v1",
            "round": round_index, "model": model, "provider": request.harness.provider_id,
            "finish_reason": result.finish_reason, "usage": result.usage,
            "elapsed_seconds": round(monotonic() - started_at, 3),
            "content_chars": sum(map(len, result.content_parts)),
            "reasoning_chars": sum(map(len, result.reasoning_parts)),
            "tool_call_chunk_count": len(result.tool_call_chunks),
            "tool_call_fragment_count": tool_call_fragment_count,
            "wire_tool_call_items": wire_tool_call_items,
            "named_tool_call_count": sum(bool((c.get("function") or {}).get("name")) for c in result.tool_call_chunks),
            "tool_call_source": "text_protocol" if result.text_tool_call_recovered else "structured" if result.tool_call_chunks else "none",
            "protocol_error": result.protocol_error, "model_error": result.model_error[:500],
            "idle_timeout": result.idle_timeout, "interrupted_by_guidance": result.interrupted_by_guidance,
            "requested_tool_count": len(tools or []), "request_budget": result.request_budget,
            "visual_context_delivery": result.visual_context_delivery,
            "visual_context_error": result.visual_context_error,
        })
        return result

    async def _publish(self, payload: dict[str, Any]) -> None:
        self._emit(payload)
        await self._flush()
