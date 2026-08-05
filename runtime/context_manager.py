"""使用 tiktoken 计算 token 并采用混合压缩的上下文窗口管理。

当上下文总量超过模型上限时，混合策略会完整保留近期消息，
并将较早消息汇总为紧凑摘要。"""

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
# 模型上下文窗口上限（以 token 计）
# ---------------------------------------------------------------------------

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # 火山引擎 / 豆包（Volcengine / Doubao）
    "doubao-seed-2-0-pro-260215": 256_000,
    "doubao-seed-2-0-code-preview-260215": 256_000,
    "doubao-seed-1-6-251015": 128_000,
    "doubao-seed-1-8-251228": 128_000,
    # 通义千问 / 百炼（Qwen / DashScope）
    "qwen3.6-flash": 983_000,
    "qwen3.6-max-preview": 1_000_000,
    "qwen3.7-max": 1_000_000,
    "qwen3.7-max-preview": 1_000_000,

    # 通过 DashScope 调用 DeepSeek
    "deepseek-v4-flash": 1_000_000,
}

DEFAULT_CONTEXT_LIMIT = 128_000

# 为模型响应预留 token，避免完全占满上下文窗口。
RESPONSE_RESERVE = 8_000

# 始终不参与压缩的近期消息数量。
RECENT_MESSAGES_KEEP = 6

# 生成摘要本身允许使用的最大 token 数。
SUMMARY_MAX_TOKENS = 1_200

# ---------------------------------------------------------------------------
# 编码器：延迟初始化的单例
# ---------------------------------------------------------------------------

_encoding: tiktoken.Encoding | None = None
_encoding_error: str | None = None


def _get_encoding() -> tiktoken.Encoding:
    global _encoding, _encoding_error
    if _encoding is None:
        if _encoding_error is not None:
            raise RuntimeError(_encoding_error)
        try:
            _encoding = tiktoken.get_encoding("cl100k_base")
            _encoding_error = None
        except Exception as exc:
            _encoding_error = _safe_error_text(exc)
            raise
    return _encoding


def tokenizer_ready() -> bool:
    return _encoding is not None


def tokenizer_error() -> str | None:
    return _encoding_error


def _safe_error_text(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return " ".join(text.split())[:300]


async def warm_context_tokenizer() -> None:
    """在请求路径之外预热分词器。

    tiktoken 会延迟加载编码。如果在首次获取对话详情时才加载，
    启动后第一次打开对话会显得很慢，尽管此时 token 用量只是 UI 提示。"""
    try:
        await asyncio.to_thread(_get_encoding)
    except Exception as exc:
        logger.warning("Context tokenizer warmup failed; using fast estimate fallback: %s", _safe_error_text(exc))


# ---------------------------------------------------------------------------
# token 计数辅助函数
# ---------------------------------------------------------------------------


def count_tokens(text: str) -> int:
    """使用 cl100k_base 返回 *text* 中的 token 数量。"""
    if not text:
        return 0
    try:
        return len(_get_encoding().encode(text))
    except Exception as exc:
        logger.warning("Context tokenizer unavailable; using fast estimate fallback: %s", _safe_error_text(exc))
        return _estimate_text_tokens_fast(text)


def count_message_tokens(message: dict[str, Any]) -> int:
    """估算一条 Chat Completion 消息的 token 数量。

    每条消息都有少量固定开销（角色与分隔符约 4 个 token）。
    内容可以是普通字符串，也可以是多模态内容片段列表。"""
    overhead = 4  # 角色与分隔符开销
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
                    total += 85  # 图片 token 估算（低细节）
        return total
    return overhead


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """返回消息列表的 token 总数。"""
    return sum(count_message_tokens(m) for m in messages) + 3  # 回复起始开销


def estimate_messages_tokens_fast(messages: list[dict[str, Any]]) -> int:
    """在分词器尚未预热时，为 UI 显示提供低成本 token 估算。"""
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
# 上下文上限查询
# ---------------------------------------------------------------------------


def get_context_limit(model: str, settings: Any | None = None) -> int:
    """返回 *model* 的上下文窗口大小（以 token 计）。"""
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
    """返回扣除响应预留后的上下文可用上限。"""
    return max(get_context_limit(model, settings) - RESPONSE_RESERVE, 4_096)


# ---------------------------------------------------------------------------
# 上下文压缩
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
    """当 *messages* 的 token 总量超过模型上限时压缩上下文。

    返回 ``(compressed_messages, summary_meta)``。其中 *summary_meta*
    是适合保存到 ``conversation.metadata`` 的字典；无需压缩时为 ``None``。

    混合策略如下：
    1. 保留系统提示（``messages[0]``）。
    2. 完整保留最后 ``RECENT_MESSAGES_KEEP`` 条非系统消息。
    3. 汇总系统提示与近期窗口之间的全部消息。
    4. 如果缓存摘要已经覆盖某段前缀，则将其合并进来。"""
    usable = get_usable_limit(model, settings)
    total = count_messages_tokens(messages)

    if not force and total <= usable:
        return messages, None  # 无需压缩

    if force:
        logger.info("Context compression forced: %d tokens (model=%s)", total, model)
    else:
        logger.info(
            "Context compression triggered: %d tokens > %d limit (model=%s)",
            total, usable, model,
        )

    # 拆分为：system_prompt | 较早消息 | 近期消息
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    non_system = messages[1:] if system_msg else messages

    keep_count = min(RECENT_MESSAGES_KEEP, len(non_system))
    older = non_system[:-keep_count] if keep_count < len(non_system) else []
    recent = non_system[-keep_count:] if keep_count else non_system

    if not older:
        # 没有可压缩内容：所有消息都属于近期窗口。
        return messages, None

    # --- 构建较早消息摘要 ---------------------------------
    # 上下文卫生层会动态压缩历史任务轮次，因此清理后消息列表中的索引
    # 不是稳定的摘要游标。只有持久来源前缀仍具有相同摘要值时，
    # 才复用缓存摘要。
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
    """返回可安全写入长期对话摘要的消息。

    面向模型的运行时脚手架只应服务于单次调用，不应成为持久摘要材料。
    否则边界提示、Context Pack 提示或历史任务标记可能在后续请求中
    作为陈旧指令重新进入上下文。"""

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
    """返回持久摘要来源序列的稳定摘要值。"""
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
    """调用模型生成 *older_messages* 的摘要。"""
    # 构建用于摘要的紧凑对话表示。
    lines: list[str] = []
    if cached_summary:
        lines.append(f"[已有摘要] {cached_summary}")
        lines.append("")
    for msg in older_messages:
        role = msg.get("role", "unknown")
        content = _summary_message_content(msg.get("content", ""))
        # 截断过长消息，避免摘要请求体膨胀。
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

    # 回退：模型调用失败时进行机械截断。
    fallback = _fallback_summary(older_messages)
    if cached_summary and fallback:
        return f"{cached_summary}\n{fallback}"
    return cached_summary or fallback


def _fallback_summary(messages: list[dict[str, Any]]) -> str:
    """模型调用失败时生成简单的抽取式摘要。"""
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
