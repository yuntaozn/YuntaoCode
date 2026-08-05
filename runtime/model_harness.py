"""面向模型的请求 Harness。

本模块负责模型调用的传输结构适配，可以描述如何发送一个 Provider 轮次，
以及如何规范化 Provider 传输错误；不得判断任务意图、选择工具、
校验完成状态或选择执行路线。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ModelHarnessSpec:
    harness_id: str = "openai_compatible"
    provider_id: str = ""
    wire_api: str = "chat_completions"
    supports_tools: bool = True
    supports_stream: bool = True
    supports_vision: bool = True
    thinking_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness_id": self.harness_id,
            "provider_id": self.provider_id,
            "wire_api": self.wire_api,
            "supports_tools": self.supports_tools,
            "supports_stream": self.supports_stream,
            "supports_vision": self.supports_vision,
            "thinking_mode": self.thinking_mode,
        }


@dataclass(frozen=True)
class ModelRoundRequest:
    settings: Any
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    enable_thinking: bool
    reasoning_effort: str | None
    tool_choice: Any | None = None
    harness: ModelHarnessSpec = ModelHarnessSpec()

    def to_stream_kwargs(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "model": self.model,
            "messages": self.messages,
            "enable_thinking": self.enable_thinking,
            "reasoning_effort": self.reasoning_effort,
            "tools": self.tools or None,
            "tool_choice": self.tool_choice,
        }

    def with_messages(self, messages: list[dict[str, Any]]) -> "ModelRoundRequest":
        return replace(self, messages=messages)


class ModelHarness:
    """在不改变任务策略的前提下准备模型传输请求。"""

    def prepare_round_request(
        self,
        *,
        settings: Any,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        enable_thinking: bool,
        reasoning_effort: str | None,
        tool_choice: Any | None = None,
    ) -> ModelRoundRequest:
        spec = inspect_model_harness(settings, model)
        return ModelRoundRequest(
            settings=settings,
            model=model,
            messages=messages,
            tools=tools or None,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            harness=spec,
        )

    def has_visual_context(self, request: ModelRoundRequest) -> bool:
        return contains_image_context(request.messages)

    def is_visual_transport_error(self, error: Any) -> bool:
        return looks_like_visual_transport_error(error)

    def downgrade_visual_context(self, request: ModelRoundRequest) -> ModelRoundRequest:
        return request.with_messages(downgrade_image_context(request.messages))


def default_model_harness() -> ModelHarness:
    return ModelHarness()


def inspect_model_harness(settings: Any, model: str) -> ModelHarnessSpec:
    resolve_model = getattr(settings, "resolve_model", None)
    if not callable(resolve_model):
        return ModelHarnessSpec()
    try:
        model_config, provider, provider_id = resolve_model(model)
    except Exception:
        return ModelHarnessSpec()
    if not isinstance(model_config, dict):
        model_config = {}
    if not isinstance(provider, dict):
        provider = {}
    wire_api = str(
        model_config.get("wire_api")
        or provider.get("wire_api")
        or "chat_completions"
    ).strip() or "chat_completions"
    return ModelHarnessSpec(
        harness_id=_normalize_harness_id(
            model_config.get("harness")
            or provider.get("harness")
            or provider.get("kind")
            or wire_api
        ),
        provider_id=str(provider_id or model_config.get("provider") or "").strip(),
        wire_api=wire_api,
        supports_tools=bool(model_config.get("supports_tools", True)),
        supports_stream=bool(model_config.get("supports_stream", True)),
        supports_vision=bool(model_config.get("supports_vision", True)),
        thinking_mode=str(
            model_config.get("thinking_mode")
            or provider.get("thinking_mode")
            or ""
        ).strip(),
    )


def contains_image_context(messages: list[dict[str, Any]]) -> bool:
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


def looks_like_visual_transport_error(error: Any) -> bool:
    text = str(error or "").lower()
    if not text:
        return False
    if "image" in text or "vision" in text or "multimodal" in text:
        return True
    return any(code in text for code in ("http 400", "http 404", "status 400", "status 404"))


def downgrade_image_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _normalize_harness_id(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return "openai_compatible"
    aliases = {
        "openai": "openai_compatible",
        "chat_completions": "openai_compatible",
        "responses": "openai_responses",
    }
    return aliases.get(text, text)
