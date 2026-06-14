"""Context window management with tiktoken-based token counting and mixed compression.

The mixed strategy keeps recent messages intact and summarises older messages
into a compact digest when the total context exceeds the model's limit.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import tiktoken

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
    "你是一个对话摘要助手。请把下面的对话历史压缩为一段简洁的中文摘要，"
    "保留关键事实、用户意图和重要结论。不要遗漏文件路径、代码片段等具体信息。"
    "摘要长度控制在 800 字以内。只输出摘要本身，不要加标题或格式说明。"
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
    # Check if we already have a cached summary that covers part of the older
    # messages.  If so, we include it as context for the new summary.
    cached_summary, cached_up_to = _cached_summary_state(conversation)
    cached_up_to = min(cached_up_to, len(older))
    messages_to_summarize = older[cached_up_to:] if cached_summary else older

    summary_reused = bool(cached_summary and not messages_to_summarize)
    if summary_reused:
        summary_text = cached_summary
    else:
        summary_text = await _generate_summary(messages_to_summarize, model, settings, cached_summary)

    summary_msg: dict[str, Any] = {
        "role": "system",
        "content": f"[以下是之前对话的摘要]\n{summary_text}",
    }

    compressed: list[dict[str, Any]] = []
    if system_msg:
        compressed.append(system_msg)
    compressed.append(summary_msg)
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
        "summary_reused": summary_reused,
        "summary_token_count": count_tokens(summary_text),
    }
    return compressed, summary_meta


def _cached_summary_state(conversation: Any | None) -> tuple[str, int]:
    if not conversation or not hasattr(conversation, "metadata"):
        return "", 0
    metadata = conversation.metadata if isinstance(conversation.metadata, dict) else {}
    summary = str(metadata.get("context_summary") or "").strip()
    try:
        up_to = int(metadata.get("summary_up_to_index") or 0)
    except (TypeError, ValueError):
        up_to = 0
    return summary, max(0, up_to)


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
        content = msg.get("content", "")
        if isinstance(content, list):
            # multimodal – extract text parts only
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = "\n".join(text_parts)
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
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = "\n".join(text_parts)
        preview = content[:200] + "…" if len(content) > 200 else content
        lines.append(f"[{role}] {preview}")
    return "\n".join(lines)
