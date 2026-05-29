"""Memory prompt building with relevance scoring.

This module builds the memory prompt that gets injected into the system prompt.
It uses relevance scoring to select the most relevant memories for each conversation.
"""

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

# Re-export for backward compatibility
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


# ----- Legacy compat (kept for settings migration) -----

def normalize_memory_item(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize a legacy memory item dict (for settings migration)."""
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


# ----- Legacy prompt builder (kept for backward compat) -----

def build_memory_prompt(memory_settings: dict[str, Any] | None) -> str:
    """Legacy prompt builder for when MemoryStore is not yet initialized."""
    memories = normalize_memory_settings(memory_settings)
    if not memories.get("enabled"):
        return "未启用用户记忆。"
    max_active = int(memories.get("max_active") or 0)
    if max_active <= 0:
        return "用户记忆已启用，但当前注入上限为 0。"
    return "暂无已启用用户记忆。"


# ----- Relevance-based prompt builder -----

# Simple Chinese/English tokenization
_WORD_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    """Extract word tokens from text (supports Chinese and English)."""
    return set(m.lower() for m in _WORD_PATTERN.findall(text) if len(m) >= 2)


def _score_memory(
    item: MemoryItem,
    message_tokens: set[str],
    message_tags: set[str],
    now: datetime,
) -> float:
    """Score a memory's relevance to the current user message.

    Higher score = more relevant.
    """
    score = 0.0

    # 1. Tag matching (+3 per matched tag)
    item_tags = set(t.lower() for t in item.tags)
    tag_overlap = item_tags & message_tags
    score += len(tag_overlap) * 3.0

    # 2. Text keyword overlap (+1 per matched word)
    item_tokens = _tokenize(item.text)
    text_overlap = item_tokens & message_tokens
    score += len(text_overlap) * 1.0

    # 3. Recency bonus
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

    # 4. Usage frequency bonus
    if item.usage_count > 5:
        score += 1.0
    elif item.usage_count > 15:
        score += 2.0

    # 5. Base score for enabled memories (ensures some always show)
    score += 0.5

    return score


def build_memory_prompt_from_store(
    store: MemoryStore,
    *,
    enabled: bool = True,
    max_active: int = DEFAULT_ACTIVE_MEMORIES,
    user_message: str = "",
    max_prompt_chars: int = MAX_MEMORY_PROMPT_CHARS,
) -> tuple[str, list[str]]:
    """Build memory prompt with relevance filtering.

    Returns (prompt_text, list_of_used_memory_ids).
    """
    if not enabled:
        return "未启用用户记忆。", []

    if max_active <= 0:
        return "用户记忆已启用，但当前注入上限为 0。", []

    all_memories = store.list()
    enabled_items = [m for m in all_memories if m.enabled and m.text]

    if not enabled_items:
        return "暂无已启用用户记忆。", []

    now = datetime.now(timezone.utc)

    # Tokenize user message for relevance scoring
    message_tokens = _tokenize(user_message) if user_message else set()
    # Also extract potential tags from message (words that look like tags)
    message_tags = message_tokens  # Simple: use all tokens as potential tags

    # Score and sort
    scored = [
        (item, _score_memory(item, message_tokens, message_tags, now))
        for item in enabled_items
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Select top-N within char budget
    selected: list[MemoryItem] = []
    selected_ids: list[str] = []
    total_chars = 0

    for item, _ in scored:
        if len(selected) >= max_active:
            break
        line = item.text
        if item.tags:
            line = f"[{', '.join(item.tags)}] {line}"
        line_len = len(line) + 2  # "- " prefix + newline
        if total_chars + line_len > max_prompt_chars:
            continue  # Skip this one, try shorter ones
        selected.append(item)
        selected_ids.append(item.id)
        total_chars += line_len

    if not selected:
        return "暂无已启用用户记忆。", []

    # Build prompt
    lines = []
    for item in selected:
        tags = item.tags or []
        tag_text = f"[{', '.join(tags)}] " if tags else ""
        lines.append(f"- {tag_text}{item.text}")

    prompt = "\n".join(lines)
    if len(prompt) > max_prompt_chars:
        prompt = prompt[:max_prompt_chars] + "\n- ...记忆过长，已截断"

    # Record usage for selected memories
    store.batch_record_usage(selected_ids)

    return prompt, selected_ids
