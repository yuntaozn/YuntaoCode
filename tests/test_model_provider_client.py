from __future__ import annotations

from runtime.model_providers.client import (
    build_request_body,
    extract_direct_stream_event,
    extract_stream_event,
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


def test_low_level_request_options_override_declared_output_budget() -> None:
    body = build_request_body(
        provider_id="custom",
        provider={},
        model_config={
            "max_output_tokens": 32768,
            "output_token_param": "max_tokens",
            "request_options": {"max_tokens": 8192},
        },
        model="any-model",
        messages=[{"role": "user", "content": "edit"}],
        stream=True,
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )

    assert body["max_tokens"] == 8192


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
