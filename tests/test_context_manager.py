from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import runtime.context_manager as context_manager


class _Settings:
    def get_model_config(self, model: str) -> dict[str, Any]:
        return {"context_limit": 128000}


def _message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def test_fast_token_estimate_is_available_without_precise_tokenizer() -> None:
    messages = [
        _message("system", "You are helpful."),
        _message("user", "请分析这个项目"),
        {"role": "assistant", "content": [{"type": "text", "text": "好的"}, {"type": "image_url"}]},
    ]

    estimate = context_manager.estimate_messages_tokens_fast(messages)

    assert estimate > 0
    assert isinstance(context_manager.tokenizer_ready(), bool)


@pytest.mark.asyncio
async def test_compress_context_force_builds_real_compressed_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[dict[str, Any]]] = []

    async def fake_summary(
        older_messages: list[dict[str, Any]],
        model: str,
        settings: Any,
        cached_summary: str = "",
    ) -> str:
        del model, settings, cached_summary
        calls.append(older_messages)
        return "forced summary"

    monkeypatch.setattr(context_manager, "_generate_summary", fake_summary)
    monkeypatch.setattr(context_manager, "RECENT_MESSAGES_KEEP", 2)

    messages = [
        _message("system", "system"),
        _message("user", "old user"),
        _message("assistant", "old assistant"),
        _message("user", "recent user"),
        _message("assistant", "recent assistant"),
    ]

    compressed, meta = await context_manager.compress_context(
        messages,
        "demo-model",
        _Settings(),
        force=True,
    )

    assert meta is not None
    assert calls == [[messages[1], messages[2]]]
    assert compressed == [
        messages[0],
        {"role": "system", "content": "[以下是之前对话的摘要]\nforced summary"},
        messages[3],
        messages[4],
    ]
    assert meta["summary_up_to_index"] == 2
    assert meta["summary_new_message_count"] == 2


@pytest.mark.asyncio
async def test_compress_context_summarizes_only_new_older_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[dict[str, Any]], str]] = []

    async def fake_summary(
        older_messages: list[dict[str, Any]],
        model: str,
        settings: Any,
        cached_summary: str = "",
    ) -> str:
        del model, settings
        calls.append((older_messages, cached_summary))
        return f"{cached_summary}\nnew summary".strip()

    monkeypatch.setattr(context_manager, "_generate_summary", fake_summary)
    monkeypatch.setattr(context_manager, "get_usable_limit", lambda model, settings: 10)
    monkeypatch.setattr(context_manager, "RECENT_MESSAGES_KEEP", 2)
    conversation = SimpleNamespace(metadata={
        "context_summary": "old summary",
        "summary_up_to_index": 2,
    })
    messages = [
        _message("system", "system"),
        _message("user", "old user 1 " * 80),
        _message("assistant", "old assistant 1 " * 80),
        _message("user", "new old user " * 80),
        _message("assistant", "new old assistant " * 80),
        _message("user", "recent user " * 80),
        _message("assistant", "recent assistant " * 80),
    ]

    compressed, meta = await context_manager.compress_context(
        messages,
        "demo-model",
        _Settings(),
        conversation=conversation,
    )

    assert meta is not None
    assert calls == [([messages[3], messages[4]], "old summary")]
    assert "old summary" in compressed[1]["content"]
    assert "new summary" in compressed[1]["content"]
    assert meta["summary_up_to_index"] == 4
    assert meta["summary_new_message_count"] == 2
    assert meta["summary_reused"] is False


@pytest.mark.asyncio
async def test_compress_context_reuses_cached_summary_when_no_new_older_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_summary(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("summary generation should not run")

    monkeypatch.setattr(context_manager, "_generate_summary", fail_summary)
    monkeypatch.setattr(context_manager, "get_usable_limit", lambda model, settings: 10)
    monkeypatch.setattr(context_manager, "RECENT_MESSAGES_KEEP", 2)
    conversation = SimpleNamespace(metadata={
        "context_summary": "old summary",
        "summary_up_to_index": 4,
    })
    messages = [
        _message("system", "system"),
        _message("user", "old user 1 " * 80),
        _message("assistant", "old assistant 1 " * 80),
        _message("user", "old user 2 " * 80),
        _message("assistant", "old assistant 2 " * 80),
        _message("user", "recent user " * 80),
        _message("assistant", "recent assistant " * 80),
    ]

    compressed, meta = await context_manager.compress_context(
        messages,
        "demo-model",
        _Settings(),
        conversation=conversation,
    )

    assert meta is not None
    assert compressed[1]["content"] == "[以下是之前对话的摘要]\nold summary"
    assert meta["summary_reused"] is True
    assert meta["summary_new_message_count"] == 0
