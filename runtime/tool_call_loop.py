"""Provider-facing protocol loop for one model/tool round.

This module owns transport facts produced while a model streams one round:
content and reasoning deltas, tool-call argument chunks, request budgets,
heartbeats, provider errors, idle timeouts, and runtime-guidance interruption.
It does not decide task intent, tool routes, completion, or verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from runtime.agent_strategy.classifiers import (
    merge_tool_call_chunks,
    tool_call_arguments_size,
)
from runtime.model_providers.client import stream_chat_completion


StreamFactory = Callable[..., AsyncIterator[dict[str, Any]]]
EmitEvent = Callable[[dict[str, Any]], None]
FlushEvents = Callable[[], Awaitable[None]]
GuidancePending = Callable[[], bool]


@dataclass
class ModelRoundResult:
    """Facts observed from one provider stream."""

    content_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    tool_call_chunks: list[dict[str, Any]] = field(default_factory=list)
    finish_reasons: list[str] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    request_budget: dict[str, Any] | None = None
    model_error: str = ""
    idle_timeout: bool = False
    fatal: bool = False
    interrupted_by_guidance: bool = False
    consecutive_idle_timeouts: int = 0
    large_argument_observations: int = 0
    visual_context_fallback: bool = False

    @property
    def finish_reason(self) -> str:
        return self.finish_reasons[-1] if self.finish_reasons else ""


class ToolCallLoop:
    """Stream one model round without making semantic execution decisions."""

    def __init__(
        self,
        *,
        emit: EmitEvent,
        flush: FlushEvents,
        guidance_pending: GuidancePending,
        stream_factory: StreamFactory = stream_chat_completion,
    ) -> None:
        self._emit = emit
        self._flush = flush
        self._guidance_pending = guidance_pending
        self._stream_factory = stream_factory

    async def run_model_round(
        self,
        *,
        settings: Any,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        enable_thinking: bool,
        reasoning_effort: str | None,
        has_runtime_facts: bool,
        consecutive_idle_timeouts: int,
        argument_observation_threshold: int,
        large_argument_observations: int,
    ) -> ModelRoundResult:
        result = ModelRoundResult(
            consecutive_idle_timeouts=consecutive_idle_timeouts,
            large_argument_observations=large_argument_observations,
        )
        large_arguments_reported = False
        messages_for_attempt = messages
        visual_fallback_attempted = False

        while True:
            retry_without_visual_context = False
            async for event in self._stream_factory(
                settings=settings,
                model=model,
                messages=messages_for_attempt,
                enable_thinking=enable_thinking,
                reasoning_effort=reasoning_effort,
                tools=tools or None,
                tool_choice=None,
            ):
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
                            await self._publish({
                                "event": "error",
                                "error": "模型服务连续超时，请检查网络连接或稍后重试",
                            })
                        else:
                            await self._publish({
                                "event": "status",
                                "status": "idle_timeout",
                                "message": "模型响应超时，正在重试...",
                            })
                        break

                    if (
                        not visual_fallback_attempted
                        and _contains_image_context(messages_for_attempt)
                        and _looks_like_visual_transport_error(event.get("error"))
                    ):
                        visual_fallback_attempted = True
                        result.visual_context_fallback = True
                        messages_for_attempt = _downgrade_image_context(messages_for_attempt)
                        retry_without_visual_context = True
                        await self._publish({
                            "event": "status",
                            "status": "visual_context_text_fallback",
                            "message": (
                                "模型服务不接受图片上下文，已保留视觉证据的文字事实并重新连接模型。"
                            ),
                        })
                        break

                    result.model_error = str(event.get("error") or "")
                    result.fatal = not has_runtime_facts
                    await self._publish({
                        "event": "error",
                        "error": result.model_error,
                        "terminal": result.fatal,
                        "recoverable": not result.fatal,
                    })
                    break

                emitted_delta = False
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
                if event.get("tool_calls"):
                    result.consecutive_idle_timeouts = 0
                    merge_tool_call_chunks(result.tool_call_chunks, event["tool_calls"])
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
                        "status": "runtime_intervention",
                        "message": "收到插话，正在暂停当前输出并重新审视任务",
                    })
                    break

            if retry_without_visual_context:
                continue
            break

        return result

    async def _publish(self, payload: dict[str, Any]) -> None:
        self._emit(payload)
        await self._flush()


def _contains_image_context(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "") in {"image_url", "input_image"}:
                return True
    return False


def _looks_like_visual_transport_error(error: Any) -> bool:
    text = str(error or "").lower()
    if not text:
        return False
    if "image" in text or "vision" in text or "multimodal" in text:
        return True
    return any(code in text for code in ("http 400", "http 404", "status 400", "status 404"))


def _downgrade_image_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    downgraded: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            downgraded.append(message)
            continue
        text_parts: list[str] = []
        image_count = 0
        for part in content:
            if not isinstance(part, dict):
                text = str(part or "").strip()
                if text:
                    text_parts.append(text)
                continue
            part_type = str(part.get("type") or "").strip()
            if part_type == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    text_parts.append(text)
            elif part_type in {"image_url", "input_image"}:
                image_count += 1
        if image_count:
            text_parts.append(
                f"[{image_count} image artifact(s) omitted because the model transport rejected image input. "
                "Use the accompanying artifact path, dimensions, console/page errors, and other text evidence.]"
            )
        downgraded.append({**message, "content": "\n\n".join(text_parts)})
    return downgraded
