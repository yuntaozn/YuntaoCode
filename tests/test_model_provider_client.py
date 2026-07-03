from __future__ import annotations

import pytest

from runtime.model_providers import client as provider_client
from runtime.model_providers.client import (
    build_request_body,
    context_limit_from_models,
    context_limit_from_props,
    estimate_request_tokens,
    extract_direct_stream_event,
    extract_message_parts,
    extract_stream_event,
    fit_request_body_to_context,
    format_provider_error,
    provider_root_url,
    stream_chat_completion,
)


def test_extract_stream_event_accepts_legacy_function_call() -> None:
    event = extract_stream_event({
        "choices": [
            {
                "delta": {
                    "function_call": {
                        "name": "filesystem__scan_folder",
                        "arguments": '{"path":"."}',
                    }
                }
            }
        ]
    })

    assert event["tool_calls"] == [
        {
            "index": 0,
            "id": None,
            "type": "function",
            "function": {
                "name": "filesystem__scan_folder",
                "arguments": '{"path":"."}',
            },
        }
    ]


def test_extract_stream_event_preserves_finish_reason() -> None:
    event = extract_stream_event({
        "choices": [{"delta": {}, "finish_reason": "length"}],
    })

    assert event["finish_reason"] == "length"


def test_extract_stream_event_accepts_choice_level_content_and_reasoning() -> None:
    event = extract_stream_event({
        "choices": [
            {
                "content": "hello",
                "reasoning": "thinking",
                "finish_reason": "stop",
            }
        ],
    })

    assert event["message"] == "hello"
    assert event["reasoning"] == "thinking"
    assert event["finish_reason"] == "stop"


def test_extract_direct_stream_event_accepts_legacy_function_call() -> None:
    event = extract_direct_stream_event({
        "function_call": {
            "name": "filesystem__scan_folder",
            "arguments": '{"path":"."}',
        }
    })

    assert event["tool_calls"][0]["function"]["name"] == "filesystem__scan_folder"
    assert event["tool_calls"][0]["function"]["arguments"] == '{"path":"."}'


def test_extract_direct_stream_event_preserves_finish_reason() -> None:
    event = extract_direct_stream_event({"finish_reason": "max_output_tokens"})

    assert event["finish_reason"] == "max_output_tokens"


def test_build_request_body_includes_model_output_budget() -> None:
    body = build_request_body(
        provider_id="volcengine",
        provider={},
        model_config={
            "max_output_tokens": 32768,
            "output_token_param": "max_completion_tokens",
        },
        model="any-model",
        messages=[{"role": "user", "content": "edit"}],
        stream=True,
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )

    assert body["max_completion_tokens"] == 32768


def test_build_request_body_does_not_guess_output_token_parameter() -> None:
    body = build_request_body(
        provider_id="custom",
        provider={},
        model_config={"max_output_tokens": 32768, "output_token_param": ""},
        model="any-model",
        messages=[{"role": "user", "content": "edit"}],
        stream=True,
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )

    assert "max_tokens" not in body
    assert "max_completion_tokens" not in body
    assert "max_output_tokens" not in body


def test_agent_plan_openai_provider_uses_responses_body() -> None:
    body = build_request_body(
        provider_id="volcengine_agent_plan",
        provider={"kind": "openai", "wire_api": "responses"},
        model_config={"thinking_mode": "", "supports_tools": True},
        model="ark-code-latest",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        enable_thinking=True,
        reasoning_effort="high",
        tools=[{"type": "function", "function": {"name": "demo", "description": "", "parameters": {}}}],
    )

    assert body["model"] == "ark-code-latest"
    assert body["input"] == [{"role": "user", "content": "hi"}]
    assert body["stream"] is True
    assert body["tools"] == [{
        "type": "function",
        "name": "demo",
        "description": "",
        "parameters": {},
    }]
    assert "thinking" not in body
    assert "reasoning_effort" not in body
    assert "messages" not in body


def test_responses_body_preserves_user_image_parts() -> None:
    body = build_request_body(
        provider_id="openai",
        provider={"kind": "openai", "wire_api": "responses"},
        model_config={"supports_tools": True},
        model="vision-model",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "look at this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        stream=True,
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )

    assert body["input"] == [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "look at this"},
            {"type": "input_image", "image_url": "data:image/png;base64,abc"},
        ],
    }]


def test_request_token_estimate_counts_image_data_url_as_placeholder() -> None:
    small = {
        "model": "vision",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
    }
    large = {
        "model": "vision",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "a" * 100_000}},
            ],
        }],
    }

    assert estimate_request_tokens(large) == estimate_request_tokens(small)


def test_extract_stream_event_accepts_responses_text_delta() -> None:
    event = extract_stream_event({
        "type": "response.output_text.delta",
        "delta": "hello",
    })

    assert event == {"message": "hello"}


def test_extract_stream_event_accepts_responses_function_call() -> None:
    event = extract_stream_event({
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "call_id": "call_1",
            "name": "filesystem__read_file",
            "arguments": "{\"path\":\"README.md\"}",
        },
    })

    assert event["tool_calls"] == [{
        "index": 0,
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "filesystem__read_file",
            "arguments": "{\"path\":\"README.md\"}",
        },
    }]


def test_extract_message_parts_accepts_responses_output_text() -> None:
    answer, reasoning = extract_message_parts({
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "done"}],
            }
        ]
    })

    assert answer == "done"
    assert reasoning == ""


def test_provider_error_includes_request_url_and_model_for_empty_body() -> None:
    message = format_provider_error(
        {},
        404,
        "https://ark.cn-beijing.volces.com/api/plan/v3/responses",
        api_model="auto",
    )

    assert "https://ark.cn-beijing.volces.com/api/plan/v3/responses" in message
    assert "模型：auto" in message


def test_provider_error_classifies_401_as_api_key_issue() -> None:
    message = format_provider_error(
        {},
        401,
        "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions",
        api_model="doubao-seed-2.0-code",
    )

    assert "HTTP 401" in message
    assert "API Key" in message
    assert "认证失败" in message
    assert "路径、模型名或请求参数" not in message


def test_provider_error_classifies_403_as_permission_issue() -> None:
    message = format_provider_error(
        {},
        403,
        "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions",
        api_model="doubao-seed-2.0-code",
    )

    assert "HTTP 403" in message
    assert "权限不足" in message
    assert "Agent Plan" in message


def test_request_options_cannot_override_runtime_owned_fields() -> None:
    body = build_request_body(
        provider_id="custom",
        provider={
            "request_options": {
                "model": "wrong-model",
                "tools": [],
                "temperature": 0.2,
            },
        },
        model_config={
            "max_output_tokens": 32768,
            "output_token_param": "max_tokens",
            "thinking_mode": "volcengine",
            "supports_reasoning_effort": True,
            "request_options": {
                "max_tokens": 8192,
                "reasoning_effort": "low",
                "thinking": {"type": "disabled"},
                "top_p": 0.9,
            },
        },
        model="any-model",
        messages=[{"role": "user", "content": "edit"}],
        stream=True,
        enable_thinking=True,
        reasoning_effort="high",
        tools=[{"type": "function", "function": {"name": "demo", "description": "", "parameters": {}}}],
    )

    assert body["model"] == "any-model"
    assert body["max_tokens"] == 32768
    assert body["reasoning_effort"] == "high"
    assert body["thinking"] == {"type": "enabled"}
    assert body["tools"]
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.9


def test_build_request_body_uses_volcengine_thinking_adapter() -> None:
    body = build_request_body(
        provider_id="volcengine",
        provider={},
        model_config={"thinking_mode": "volcengine", "supports_reasoning_effort": True},
        model="doubao",
        messages=[{"role": "user", "content": "think"}],
        stream=True,
        enable_thinking=True,
        reasoning_effort="high",
        tools=None,
    )

    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


def test_build_request_body_disables_volcengine_thinking() -> None:
    body = build_request_body(
        provider_id="volcengine",
        provider={},
        model_config={"thinking_mode": "volcengine", "supports_reasoning_effort": True},
        model="doubao",
        messages=[{"role": "user", "content": "summarize"}],
        stream=True,
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )

    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_build_request_body_uses_qwen_thinking_adapter() -> None:
    body = build_request_body(
        provider_id="qwen",
        provider={},
        model_config={"thinking_mode": "qwen"},
        model="qwen",
        messages=[{"role": "user", "content": "think"}],
        stream=True,
        enable_thinking=True,
        reasoning_effort="medium",
        tools=None,
    )

    assert body["enable_thinking"] is True


def test_build_request_body_keeps_qwen_thinking_enabled_by_default() -> None:
    body = build_request_body(
        provider_id="qwen",
        provider={},
        model_config={"thinking_mode": "qwen"},
        model="qwen",
        messages=[{"role": "user", "content": "summarize"}],
        stream=True,
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )

    assert body["enable_thinking"] is True


def test_build_request_body_disables_qwen_thinking_when_allowed() -> None:
    body = build_request_body(
        provider_id="qwen",
        provider={},
        model_config={"thinking_mode": "qwen", "allow_disable_thinking": True},
        model="qwen",
        messages=[{"role": "user", "content": "summarize"}],
        stream=True,
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )

    assert body["enable_thinking"] is False


def test_context_limit_from_llamacpp_props() -> None:
    assert context_limit_from_props({
        "default_generation_settings": {
            "n_ctx": 8192,
        }
    }) == 8192


def test_context_limit_from_openai_models_meta() -> None:
    assert context_limit_from_models({
        "data": [
            {"id": "other", "meta": {"n_ctx": 4096}},
            {"id": "gemma-4-12B", "meta": {"n_ctx": 8192}},
        ]
    }, "gemma-4-12B") == 8192


def test_provider_root_url_strips_openai_v1_suffix() -> None:
    assert provider_root_url({"base_url": "http://127.0.0.1:8080/v1"}) == "http://127.0.0.1:8080"


def test_fit_request_body_to_context_prunes_tools_by_request_budget() -> None:
    def tool(name: str, description: str = "") -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }

    essential = tool("filesystem__read_file", "Read a file.")
    oversized = tool("custom__very_large_optional_tool", "x" * 12000)
    body = {
        "model": "local",
        "messages": [{"role": "user", "content": "read the file"}],
        "stream": True,
        "tools": [oversized, essential],
        "tool_choice": "auto",
    }
    essential_only = dict(body)
    essential_only["tools"] = [essential]
    context_limit = estimate_request_tokens(essential_only) + 300

    fitted, info = fit_request_body_to_context(body, context_limit=context_limit)

    names = [item["function"]["name"] for item in fitted.get("tools", [])]
    assert "filesystem__read_file" in names
    assert "custom__very_large_optional_tool" not in names
    assert info["tools_pruned"] == 1
    assert not info.get("blocked")


def test_fit_request_body_to_context_blocks_oversized_request_without_tools() -> None:
    body = {
        "model": "local",
        "messages": [{"role": "user", "content": "x" * 20000}],
        "stream": True,
    }

    _, info = fit_request_body_to_context(body, context_limit=1024)

    assert info["blocked"] is True
    assert "1024" in info["message"]


@pytest.mark.asyncio
async def test_stream_chat_completion_uses_non_stream_when_model_disables_stream(monkeypatch) -> None:
    class FakeSettings:
        def resolve_model(self, model: str):
            return (
                {"api_model": model, "supports_stream": False},
                {"base_url": "http://127.0.0.1:8080", "api_key_required": False},
                "local",
            )

    async def fake_generate_chat_completion(**kwargs):
        return "hello", {
            "reasoning": "thinking",
            "usage": {"total_tokens": 3},
        }

    monkeypatch.setattr(provider_client, "generate_chat_completion", fake_generate_chat_completion)

    events = [
        event
        async for event in stream_chat_completion(
            settings=FakeSettings(),
            model="local-model",
            messages=[{"role": "user", "content": "hi"}],
        )
    ]

    assert events == [
        {"reasoning": "thinking"},
        {"message": "hello"},
        {"usage": {"total_tokens": 3}, "finish_reason": "stop"},
    ]
