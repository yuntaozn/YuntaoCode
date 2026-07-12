"""Context window management with tiktoken-based token counting and mixed compression.

The mixed strategy keeps recent messages intact and summarises older messages
into a compact digest when the total context exceeds the model's limit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

import tiktoken

from .agent_strategy.model_context_boundary import (
    CONTEXT_HYGIENE_NOTICE,
    CURRENT_REQUEST_BOUNDARY_NOTICE,
    HISTORICAL_TASK_CANDIDATE_PREFIX,
    HISTORICAL_TASK_TURNS_PREFIX,
    HISTORICAL_TASK_USER_PREFIX,
)
from .model_providers.client import stream_chat_completion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model context-window limits (in tokens)
# ---------------------------------------------------------------------------

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Volcengine / Doubao
    "doubao-seed-2-0-pro-260215": 256_000,
    "doubao-seed-2-0-code-preview-260215": 256_000,
    "doubao-seed-1-6-251015": 128_000,
    "doubao-seed-1-8-251228": 128_000,
    # Qwen / DashScope
    "qwen3.6-flash": 983_000,
    "qwen3.6-max-preview": 1_000_000,
    "qwen3.7-max": 1_000_000,
    "qwen3.7-max-preview": 1_000_000,
    
    # DeepSeek via DashScope
    "deepseek-v4-flash": 1_000_000,
}

DEFAULT_CONTEXT_LIMIT = 128_000

# Reserve tokens for the model's response so we don't fill the window fully.
RESPONSE_RESERVE = 8_000

# Number of most-recent messages that are *never* compressed.
RECENT_MESSAGES_KEEP = 6

# Maximum tokens allowed for the generated summary itself.
SUMMARY_MAX_TOKENS = 1_200

# ---------------------------------------------------------------------------
# Encoding – lazily initialised singleton
# ---------------------------------------------------------------------------

_encoding: tiktoken.Encoding | None = None


def _get_encoding() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def tokenizer_ready() -> bool:
    return _encoding is not None


async def warm_context_tokenizer() -> None:
    """Warm the tokenizer off the request path.

    tiktoken loads its encoding lazily. Doing this from the first conversation
    detail request makes opening the first chat after startup feel slow, even
    though token usage is only a UI hint at that moment.
    """
    try:
        await asyncio.to_thread(_get_encoding)
    except Exception:
        logger.exception("Context tokenizer warmup failed")


# ---------------------------------------------------------------------------
# Token counting helpers
# ---------------------------------------------------------------------------


def count_tokens(text: str) -> int:
    """Return the number of tokens in *text* using cl100k_base."""
    if not text:
        return 0
    return len(_get_encoding().encode(text))


def count_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens for a single chat-completion message.

    Every message has a small overhead (~4 tokens for role / separators).
    Content may be a plain string or a multimodal parts list.
    """
    overhead = 4  # role, separators
    content = message.get("content", "")
    if isinstance(content, str):
        return overhead + count_tokens(content)
    if isinstance(content, list):
        total = overhead
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    total += count_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    total += 85  # image token estimate (low-detail)
        return total
    return overhead


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Return the total token count for a list of messages."""
    return sum(count_message_tokens(m) for m in messages) + 3  # reply priming


def estimate_messages_tokens_fast(messages: list[dict[str, Any]]) -> int:
    """Cheap token estimate for UI display while the tokenizer is cold."""
    return sum(_estimate_message_tokens_fast(message) for message in messages) + 3


def _estimate_message_tokens_fast(message: dict[str, Any]) -> int:
    overhead = 4
    content = message.get("content", "")
    if isinstance(content, str):
        return overhead + _estimate_text_tokens_fast(content)
    if isinstance(content, list):
        total = overhead
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total += _estimate_text_tokens_fast(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                total += 85
        return total
    return overhead


def _estimate_text_tokens_fast(text: str) -> int:
    if not text:
        return 0
    ascii_chars = 0
    cjk_chars = 0
    other_chars = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            cjk_chars += 1
        elif ord(char) < 128:
            ascii_chars += 1
        else:
            other_chars += 1
    return max(1, (ascii_chars + 3) // 4 + cjk_chars + (other_chars + 1) // 2)


# ---------------------------------------------------------------------------
# Context limit lookup
# ---------------------------------------------------------------------------


def get_context_limit(model: str, settings: Any | None = None) -> int:
    """Return the context-window size for *model* (in tokens)."""
    if settings is not None and hasattr(settings, "get_model_config"):
        try:
            model_config = settings.get_model_config(model)
            context_limit = int(model_config.get("context_limit") or 0)
            if context_limit > 0:
                return context_limit
        except (TypeError, ValueError, AttributeError):
            pass
    return MODEL_CONTEXT_LIMITS.get(model, DEFAULT_CONTEXT_LIMIT)


def get_usable_limit(model: str, settings: Any | None = None) -> int:
    """Context limit minus the response reserve."""
    return max(get_context_limit(model, settings) - RESPONSE_RESERVE, 4_096)


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请把下面的真实对话历史压缩为一段简洁的中文摘要，"
    "保留用户明确表达的长期偏好、关键事实、重要结论、仍可能相关的文件路径和产物路径。"
    "旧任务目标、旧失败、旧工具调用和旧计划只能作为历史背景，不能写成当前目标或当前指令。"
    "不要保留运行时边界提示、工具调用格式示例、系统提示词或临时过程日志。"
    "摘要长度控制在 800 字以内。只输出摘要本身，不要加标题或格式说明。"
)

_CONTEXT_PACK_PROMPT_PREFIX = "Context Pack for this model call:\n"
_RUNTIME_CONTEXT_SCAFFOLD_PREFIXES = (
    CONTEXT_HYGIENE_NOTICE.splitlines()[0],
    CURRENT_REQUEST_BOUNDARY_NOTICE.splitlines()[0],
    HISTORICAL_TASK_CANDIDATE_PREFIX,
    HISTORICAL_TASK_USER_PREFIX,
    HISTORICAL_TASK_TURNS_PREFIX,
    _CONTEXT_PACK_PROMPT_PREFIX.rstrip(),
)


async def compress_context(
    messages: list[dict[str, Any]],
    model: str,
    settings: Any,
    *,
    conversation: Any = None,
    force: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Compress *messages* if total tokens exceed the model limit.

    Returns ``(compressed_messages, summary_meta)`` where *summary_meta* is
    a dict suitable for storing in ``conversation.metadata`` (or ``None`` if
    no compression was needed).

    The mixed strategy:
    1. Keep the system prompt (``messages[0]``).
    2. Keep the last ``RECENT_MESSAGES_KEEP`` non-system messages intact.
    3. Summarise all messages between system prompt and the recent window.
    4. If a cached summary already covers some prefix, incorporate it.
    """
    usable = get_usable_limit(model, settings)
    total = count_messages_tokens(messages)

    if not force and total <= usable:
        return messages, None  # no compression needed

    if force:
        logger.info("Context compression forced: %d tokens (model=%s)", total, model)
    else:
        logger.info(
            "Context compression triggered: %d tokens > %d limit (model=%s)",
            total, usable, model,
        )

    # Split: system_prompt | older… | recent
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    non_system = messages[1:] if system_msg else messages

    keep_count = min(RECENT_MESSAGES_KEEP, len(non_system))
    older = non_system[:-keep_count] if keep_count < len(non_system) else []
    recent = non_system[-keep_count:] if keep_count else non_system

    if not older:
        # Nothing to compress – all messages are "recent".
        return messages, None

    # --- Build summary of older messages ---------------------------------
    # Hygiene compacts historical task turns dynamically, so an index into the
    # cleaned message list is not a stable summary cursor. Reuse a cached
    # summary only when the durable source prefix still has the same digest.
    summary_source_messages, omitted_runtime_messages = _durable_summary_source_messages(older)
    cached_summary, cached_source_count, cached_source_digest = _cached_summary_state(conversation)
    cache_valid = bool(
        cached_summary
        and cached_source_digest
        and 0 <= cached_source_count <= len(summary_source_messages)
        and _summary_source_digest(summary_source_messages[:cached_source_count])
        == cached_source_digest
    )
    messages_to_summarize = (
        summary_source_messages[cached_source_count:]
        if cache_valid
        else summary_source_messages
    )
    summary_seed = cached_summary if cache_valid else ""
    summary_reused = bool(cache_valid and not messages_to_summarize)
    if summary_reused:
        summary_text = cached_summary
    elif not messages_to_summarize:
        summary_text = ""
    else:
        summary_text = await _generate_summary(
            messages_to_summarize,
            model,
            settings,
            summary_seed,
        )

    compressed: list[dict[str, Any]] = []
    if system_msg:
        compressed.append(system_msg)
    if summary_text:
        compressed.append({
            "role": "system",
            "content": f"[以下是之前对话的摘要]\n{summary_text}",
        })
    compressed.extend(recent)

    new_total = count_messages_tokens(compressed)
    logger.info(
        "Context compressed: %d → %d tokens (saved %d)",
        total, new_total, total - new_total,
    )

    summary_meta = {
        "context_summary": summary_text,
        "summary_up_to_index": len(older),
        "summary_message_count": len(older),
        "summary_new_message_count": len(messages_to_summarize),
        "summary_source_message_count": len(summary_source_messages),
        "summary_source_digest": _summary_source_digest(summary_source_messages),
        "summary_omitted_runtime_message_count": omitted_runtime_messages,
        "summary_reused": summary_reused,
        "summary_cache_valid": cache_valid,
        "summary_cache_invalidated": bool(cached_summary and not cache_valid),
        "summary_token_count": count_tokens(summary_text),
    }
    return compressed, summary_meta


def _durable_summary_source_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Return messages safe to persist in a long-lived conversation summary.

    Model-facing runtime scaffolding is useful for one call, but it should not
    become durable summary material. Otherwise boundary notices, Context Pack
    prompts, or historical task markers can re-enter later requests as stale
    instructions.
    """

    result: list[dict[str, Any]] = []
    omitted = 0
    for message in messages:
        if _is_runtime_context_scaffold(message):
            omitted += 1
            continue
        result.append(message)
    return result, omitted


def _is_runtime_context_scaffold(message: dict[str, Any]) -> bool:
    if str(message.get("role") or "") != "system":
        return False
    content = message.get("content", "")
    if not isinstance(content, str):
        return False
    text = content.strip()
    return any(text.startswith(prefix) for prefix in _RUNTIME_CONTEXT_SCAFFOLD_PREFIXES)


def _cached_summary_state(conversation: Any | None) -> tuple[str, int, str]:
    if not conversation or not hasattr(conversation, "metadata"):
        return "", 0, ""
    metadata = conversation.metadata if isinstance(conversation.metadata, dict) else {}
    summary = str(metadata.get("context_summary") or "").strip()
    try:
        source_count = int(metadata.get("summary_source_message_count") or 0)
    except (TypeError, ValueError):
        source_count = 0
    source_digest = str(metadata.get("summary_source_digest") or "").strip()
    return summary, max(0, source_count), source_digest


def _summary_source_digest(messages: list[dict[str, Any]]) -> str:
    """Return a stable digest for the durable summary source sequence."""
    digest = hashlib.sha256()
    for message in messages:
        payload = json.dumps(
            {
                "role": str(message.get("role") or ""),
                "content": _summary_message_content(message.get("content", "")),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


async def _generate_summary(
    older_messages: list[dict[str, Any]],
    model: str,
    settings: Any,
    cached_summary: str = "",
) -> str:
    """Call the model to produce a summary of *older_messages*."""
    # Build a compact representation of the conversation to summarise.
    lines: list[str] = []
    if cached_summary:
        lines.append(f"[已有摘要] {cached_summary}")
        lines.append("")
    for msg in older_messages:
        role = msg.get("role", "unknown")
        content = _summary_message_content(msg.get("content", ""))
        # Truncate very long messages to avoid blowing up the summary request
        if len(content) > 2000:
            content = content[:2000] + "…(截断)"
        lines.append(f"[{role}] {content}")

    conversation_text = "\n".join(lines)

    summary_messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": conversation_text},
    ]

    parts: list[str] = []
    try:
        async for event in stream_chat_completion(
            settings=settings,
            model=model,
            messages=summary_messages,
            enable_thinking=False,
            tools=None,
        ):
            if event.get("message"):
                parts.append(event["message"])
            if event.get("error"):
                logger.warning("Summary generation error: %s", event["error"])
                break
    except Exception:
        logger.exception("Failed to generate context summary")

    if parts:
        return "".join(parts).strip()

    # Fallback: mechanical truncation if model call failed.
    fallback = _fallback_summary(older_messages)
    if cached_summary and fallback:
        return f"{cached_summary}\n{fallback}"
    return cached_summary or fallback


def _fallback_summary(messages: list[dict[str, Any]]) -> str:
    """Produce a simple extractive summary when the model call fails."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = _summary_message_content(msg.get("content", ""))
        preview = content[:200] + "…" if len(content) > 200 else content
        lines.append(f"[{role}] {preview}")
    return "\n".join(lines)


def _summary_message_content(content: Any) -> str:
    if isinstance(content, list):
        text_parts = [
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        content = "\n".join(text_parts)
    text = str(content or "")
    return _strip_attachment_catalogs_for_summary(text)


def _strip_attachment_catalogs_for_summary(text: str) -> str:
    result = str(text or "")
    markers = (
        "\n\nCurrent user-provided immutable conversation attachments:\n",
        "\n\nUser-provided immutable conversation attachments:\n",
        "\n\nHistorical message attachments from an earlier turn:\n",
    )
    for marker in markers:
        while marker in result:
            before, remainder = result.split(marker, 1)
            after = ""
            next_boundary = remainder.find("\n\n")
            if next_boundary >= 0:
                after = remainder[next_boundary:]
            result = before.rstrip() + "\n\n[Attachment catalog omitted from durable summary.]" + after
    return result.strip()
