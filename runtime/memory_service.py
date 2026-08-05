"""使用相关性评分构建记忆提示。

本模块构建注入系统提示的记忆内容，并通过相关性评分为每次对话
选择最相关的记忆。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .memory_store import (
    DEFAULT_ACTIVE_MEMORIES,
    MAX_ACTIVE_MEMORIES,
    MAX_MEMORY_PROMPT_CHARS,
    MAX_MEMORY_TEXT_CHARS,
    MAX_STORED_MEMORIES,
    MemoryItem,
    MemoryStore,
)

# 为向后兼容重新导出
__all__ = [
    "DEFAULT_MEMORY_SETTINGS",
    "DEFAULT_ACTIVE_MEMORIES",
    "MAX_ACTIVE_MEMORIES",
    "MAX_MEMORY_PROMPT_CHARS",
    "MAX_MEMORY_TEXT_CHARS",
    "MAX_STORED_MEMORIES",
    "normalize_memory_item",
    "normalize_memory_settings",
    "update_memory_settings",
    "build_memory_prompt",
    "build_memory_prompt_from_store",
]

DEFAULT_MEMORY_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "max_active": DEFAULT_ACTIVE_MEMORIES,
    "auto_extract": True,
}


# ----- 旧版兼容（供设置迁移保留）-----

def normalize_memory_item(value: dict[str, Any]) -> dict[str, Any]:
    """规范化旧版记忆条目字典，供设置迁移使用。"""
    text = " ".join(str(value.get("text") or value.get("content") or "").split())
    text = text[:MAX_MEMORY_TEXT_CHARS]
    raw_tags = value.get("tags")
    if isinstance(raw_tags, str):
        raw_tags = [item.strip() for item in raw_tags.replace("，", ",").split(",")]
    if not isinstance(raw_tags, list):
        raw_tags = []
    tags: list[str] = []
    for tag in raw_tags:
        tag_text = " ".join(str(tag).strip().split())[:24]
        if tag_text and tag_text not in tags:
            tags.append(tag_text)
        if len(tags) >= 6:
            break
    item_id = str(value.get("id") or "").strip() or f"mem_{__import__('uuid').uuid4().hex[:10]}"
    return {
        "id": item_id,
        "text": text,
        "tags": tags,
        "enabled": bool(value.get("enabled", True)),
    }


def normalize_memory_settings(value: dict[str, Any] | None) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    try:
        max_active = int(source.get("max_active") or DEFAULT_ACTIVE_MEMORIES)
    except (TypeError, ValueError):
        max_active = DEFAULT_ACTIVE_MEMORIES
    return {
        "enabled": bool(source.get("enabled", True)),
        "max_active": max(0, min(max_active, MAX_ACTIVE_MEMORIES)),
        "auto_extract": bool(source.get("auto_extract", True)),
    }


def update_memory_settings(
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(normalize_memory_settings(current))
    if "enabled" in incoming:
        merged["enabled"] = bool(incoming["enabled"])
    if "max_active" in incoming:
        try:
            max_active = int(incoming["max_active"])
        except (TypeError, ValueError):
            max_active = DEFAULT_ACTIVE_MEMORIES
        merged["max_active"] = max(0, min(max_active, MAX_ACTIVE_MEMORIES))
    if "auto_extract" in incoming:
        merged["auto_extract"] = bool(incoming["auto_extract"])
    return merged


# ----- 旧版提示构建器（为向后兼容保留）-----

def build_memory_prompt(memory_settings: dict[str, Any] | None) -> str:
    """在 MemoryStore 尚未初始化时使用的旧版提示构建器。"""
    memories = normalize_memory_settings(memory_settings)
    if not memories.get("enabled"):
        return "未启用用户记忆。"
    max_active = int(memories.get("max_active") or 0)
    if max_active <= 0:
        return "用户记忆已启用，但当前注入上限为 0。"
    return "暂无已启用用户记忆。"


# ----- 基于相关性的提示构建器 -----

# 简单的中英文分词；中文文本同时表示为
# short n-grams so "用中文回答" can match memories containing "中文回复".
_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", re.UNICODE)

_STABLE_GLOBAL_TAGS = frozenset({
    "communication",
    "communication_preference",
    "communication-preference",
    "communication_style",
    "communication-style",
    "language",
    "language_preference",
    "language-preference",
})

_STABLE_GLOBAL_TEXT_HINTS = (
    "concise replies",
    "concise answers",
    "structured summaries",
    "language preference",
    "communication preference",
    "中文回复",
    "英文回复",
    "使用中文",
    "使用英文",
    "交流语言",
    "简洁回复",
    "简洁回答",
)

MAX_BROAD_GLOBAL_MEMORIES = 2


def _tokenize(text: str) -> set[str]:
    """从文本提取词元，支持中文和英文。"""
    tokens: set[str] = set()
    for match in _WORD_PATTERN.findall(text):
        value = match.lower().strip()
        if len(value) < 2:
            continue
        if all("\u4e00" <= char <= "\u9fff" for char in value):
            tokens.add(value)
            for size in (2, 3):
                if len(value) < size:
                    continue
                for index in range(0, len(value) - size + 1):
                    tokens.add(value[index:index + size])
            continue
        tokens.add(value)
    return tokens


def _normalized_tag(value: str) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _has_direct_relevance(
    item: MemoryItem,
    message_tokens: set[str],
    message_tags: set[str],
) -> bool:
    item_tags = set(t.lower() for t in item.tags)
    if item_tags & message_tags:
        return True
    return bool(_tokenize(item.text) & message_tokens)


def _is_stable_global_memory(item: MemoryItem) -> bool:
    """对可安全广泛展示的用户级全局记忆返回 True。"""
    if item.scope == "workspace":
        return False
    normalized_tags = {_normalized_tag(tag) for tag in item.tags}
    stable_tags = {_normalized_tag(tag) for tag in _STABLE_GLOBAL_TAGS}
    if normalized_tags & stable_tags:
        return True
    text = str(item.text or "").strip().lower()
    return any(hint in text for hint in _STABLE_GLOBAL_TEXT_HINTS)


def _score_memory(
    item: MemoryItem,
    message_tokens: set[str],
    message_tags: set[str],
    now: datetime,
) -> float:
    """计算记忆与当前用户消息的相关性分数。

    分数越高表示越相关。"""
    score = 0.0

    # 1. 标签匹配（每个匹配标签加 3 分）
    item_tags = set(t.lower() for t in item.tags)
    tag_overlap = item_tags & message_tags
    score += len(tag_overlap) * 3.0

    # 2. 文本关键词重叠（每个匹配词加 1 分）
    item_tokens = _tokenize(item.text)
    text_overlap = item_tokens & message_tokens
    score += len(text_overlap) * 1.0

    # 3. 新鲜度加分
    if item.created_at:
        try:
            created = datetime.fromisoformat(item.created_at)
            days_old = (now - created).total_seconds() / 86400
            if days_old <= 7:
                score += 2.0
            elif days_old <= 30:
                score += 1.0
        except (ValueError, TypeError):
            pass

    # 4. 使用频率加分
    if item.usage_count > 15:
        score += 2.0
    elif item.usage_count > 5:
        score += 1.0

    # 5. 候选记忆基础分。候选资格由其他逻辑决定；
    # 该基础分只用于稳定当前请求已选记忆之间的排序，
    # 不负责扩大选择范围。
    score += 0.5

    return score


def build_memory_prompt_from_store(
    store: MemoryStore,
    *,
    enabled: bool = True,
    max_active: int = DEFAULT_ACTIVE_MEMORIES,
    user_message: str = "",
    workspace_id: str = "",
    max_prompt_chars: int = MAX_MEMORY_PROMPT_CHARS,
    record_usage: bool = True,
) -> tuple[str, list[str]]:
    """构建带相关性过滤的记忆提示。

    返回 ``(prompt_text, list_of_used_memory_ids)``。"""
    if not enabled:
        return "未启用用户记忆。", []

    if max_active <= 0:
        return "用户记忆已启用，但当前注入上限为 0。", []

    all_memories = store.list_applicable(workspace_id)
    enabled_items = [m for m in all_memories if m.enabled and m.text]

    if not enabled_items:
        return "暂无已启用用户记忆。", []

    now = datetime.now(timezone.utc)

    # 对用户消息分词，供相关性评分使用
    message_tokens = _tokenize(user_message) if user_message else set()
    # 同时从消息中提取可能的标签
    message_tags = message_tokens  # 简化处理：全部词元都作为候选标签

    # 评分并排序。有当前用户消息时，避免把无关工作区事实
    # 注入每次模型调用；稳定的全局偏好或身份记忆
    # 仍可能具有广泛用途。
    scored: list[tuple[MemoryItem, float]] = []
    broad_global_ids: set[str] = set()
    has_current_query = bool(message_tokens)
    for item in enabled_items:
        direct_relevance = _has_direct_relevance(item, message_tokens, message_tags)
        stable_global = _is_stable_global_memory(item)
        if (
            has_current_query
            and not direct_relevance
            and not stable_global
        ):
            continue
        if has_current_query and not direct_relevance and stable_global:
            broad_global_ids.add(item.id)
        scored.append((item, _score_memory(item, message_tokens, message_tags, now)))
    scored.sort(key=lambda x: x[1], reverse=True)

    if has_current_query and not scored:
        return "暂无与当前请求相关的已启用用户记忆。", []

    # 在字符预算内选择前 N 项
    selected: list[MemoryItem] = []
    selected_ids: list[str] = []
    total_chars = 0
    broad_global_count = 0

    for item, _ in scored:
        if len(selected) >= max_active:
            break
        if item.id in broad_global_ids:
            if broad_global_count >= MAX_BROAD_GLOBAL_MEMORIES:
                continue
            broad_global_count += 1
        line = item.text
        if item.tags:
            line = f"[{', '.join(item.tags)}] {line}"
        line_len = len(line) + 2  # “- ”前缀与换行所占字符
        if total_chars + line_len > max_prompt_chars:
            continue  # 跳过当前项，继续尝试更短条目
        selected.append(item)
        selected_ids.append(item.id)
        total_chars += line_len

    if not selected:
        return "暂无已启用用户记忆。", []

    # 构建提示
    lines = []
    for item in selected:
        tags = item.tags or []
        scope_tag = "workspace" if item.scope == "workspace" else "global"
        all_tags = [scope_tag, *tags]
        tag_text = f"[{', '.join(all_tags)}] "
        lines.append(f"- {tag_text}{item.text}")

    prompt = "\n".join(lines)
    if len(prompt) > max_prompt_chars:
        prompt = prompt[:max_prompt_chars] + "\n- ...记忆过长，已截断"

    # 记录已选记忆的使用情况
    if record_usage:
        store.batch_record_usage(selected_ids)

    return prompt, selected_ids
