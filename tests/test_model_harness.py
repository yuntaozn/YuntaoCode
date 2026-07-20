from __future__ import annotations

from runtime.model_harness import (
    ModelHarness,
    contains_image_context,
    downgrade_image_context,
    inspect_model_harness,
    looks_like_visual_transport_error,
)


class FakeSettings:
    def resolve_model(self, model: str):
        return (
            {
                "id": model,
                "provider": "ark",
                "supports_tools": False,
                "supports_stream": True,
                "supports_vision": False,
                "thinking_mode": "volcengine",
            },
            {
                "kind": "openai",
                "wire_api": "chat_completions",
            },
            "ark",
        )


def test_inspect_model_harness_records_transport_facts() -> None:
    spec = inspect_model_harness(FakeSettings(), "demo")

    assert spec.harness_id == "openai_compatible"
    assert spec.provider_id == "ark"
    assert spec.wire_api == "chat_completions"
    assert spec.supports_tools is False
    assert spec.supports_stream is True
    assert spec.supports_vision is False
    assert spec.thinking_mode == "volcengine"


def test_model_harness_prepares_stream_kwargs_without_strategy_fields() -> None:
    harness = ModelHarness()
    request = harness.prepare_round_request(
        settings=FakeSettings(),
        model="demo",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "filesystem__read_file"}}],
        enable_thinking=True,
        reasoning_effort="low",
        tool_choice=None,
    )

    kwargs = request.to_stream_kwargs()

    assert kwargs["model"] == "demo"
    assert kwargs["messages"][0]["content"] == "hello"
    assert kwargs["tools"][0]["function"]["name"] == "filesystem__read_file"
    assert kwargs["tool_choice"] is None
    assert request.harness.provider_id == "ark"
    assert "goal" not in kwargs
    assert "completion" not in kwargs


def test_visual_context_detection_and_text_downgrade() -> None:
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Screenshot artifact: D:/demo/preview.png"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ],
    }]

    downgraded = downgrade_image_context(messages)

    assert contains_image_context(messages)
    assert not contains_image_context(downgraded)
    assert "Screenshot artifact: D:/demo/preview.png" in downgraded[0]["content"]
    assert "image artifact" in downgraded[0]["content"]


def test_visual_transport_error_detection_is_transport_only() -> None:
    assert looks_like_visual_transport_error("HTTP 400: image input is not accepted")
    assert looks_like_visual_transport_error("vision input unsupported")
    assert not looks_like_visual_transport_error("tool execution failed")
