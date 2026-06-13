"""Automatic memory extraction from conversation history."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from .memory_store import MemoryItem, MemoryStore

logger = logging.getLogger(__name__)

# Tags that must be rejected at storage time — these indicate project-scoped facts.
_BLOCKED_TAGS = frozenset({
    "project_knowledge", "project-knowledge", "project knowledge",
    "项目知识", "项目知识 - 技术栈",
    "project_structure", "project-info",
    "architecture_decision",
    "technical_selection", "tech_stack", "technology_stack",
    "技术选型", "技术栈",
})

# Tags allowed for automatically promoted global memory. Auto extraction is
# intentionally narrow: project facts must be saved explicitly with workspace
# scope instead of leaking into global memory.
_ALLOWED_GLOBAL_TAGS = frozenset({
    "user_preference", "user-preference", "user preference",
    "preference", "preferences",
    "communication", "communication_preference", "communication-preference",
    "tool_usage", "tool-usage", "workflow_preference", "workflow-preference",
    "ui_preference", "ui-preference", "user_identity", "user-identity",
    "user identity", "identity", "role",
    "language_preference", "language-preference",
})

EXTRACTION_SYSTEM_PROMPT = """你是一个记忆提取助手。从对话中提取值得长期记住的**用户级**信息。

只提取以下类别:
- 用户偏好 (代码风格、沟通方式、工具使用习惯、界面偏好、工作习惯)
- 用户身份 (角色、团队、专业领域、语言偏好)

绝对不要提取:
- 特定项目的结构、技术栈、部署信息、文件路径
- 特定项目的架构决策或技术选型
- 特定项目的依赖库、版本号、配置地址
- 一次性的任务细节或临时操作

规则:
1. 只提取跨项目通用的个人偏好和身份信息
2. 每条记忆只包含一个事实，用一句简洁的中文概括
3. 为每条记忆标注 1-2 个分类标签（英文），如 user_preference, user_identity
4. 如果无法确定是否为跨项目通用信息，不要提取
5. 如果没有值得提取的内容，返回空数组

输出 JSON 格式:
[{"text": "记忆内容", "tags": ["标签1", "标签2"]}]

如果无需提取，输出: []"""


def _build_extraction_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a compact conversation representation for the extraction model."""
    lines: list[str] = []
    # Only include recent user/assistant messages
    relevant = [m for m in messages if m.get("role") in ("user", "assistant")]
    # Take last 20 messages max
    for msg in relevant[-20:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = "\n".join(text_parts)
        # Truncate very long messages
        if len(content) > 1500:
            content = content[:1500] + "...(截断)"
        if content.strip():
            lines.append(f"[{role}] {content}")

    conversation_text = "\n\n".join(lines)
    if not conversation_text.strip():
        return []

    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"请从以下对话中提取值得记住的信息:\n\n{conversation_text}"},
    ]


def _parse_extraction_result(raw: str) -> list[dict[str, Any]]:
    """Parse the model's extraction output into memory items."""
    text = raw.strip()
    # Try to find JSON array in the response
    if "[" in text:
        start = text.index("[")
        # Find matching closing bracket
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            json_str = text[start:end]
            try:
                result = json.loads(json_str)
                if isinstance(result, list):
                    items = []
                    for item in result:
                        if not isinstance(item, dict):
                            continue
                        text_val = str(item.get("text") or "").strip()
                        if not text_val:
                            continue
                        tags = item.get("tags")
                        if isinstance(tags, list):
                            tags = [str(t).strip() for t in tags if str(t).strip()][:3]
                        elif isinstance(tags, str):
                            tags = [t.strip() for t in tags.split(",") if t.strip()][:3]
                        else:
                            tags = []
                        items.append({"text": text_val[:500], "tags": tags})
                    return items
            except json.JSONDecodeError:
                pass

    # If the model returned [] or empty response
    if text in ("[]", ""):
        return []

    logger.warning("Failed to parse extraction result: %s", text[:200])
    return []


async def extract_memories_from_conversation(
    messages: list[dict[str, Any]],
    model: str,
    settings: Any,
) -> list[dict[str, Any]]:
    """Extract memory candidates from conversation history.

    Returns a list of {"text": ..., "tags": [...]} dicts, or empty list.
    """
    extraction_messages = _build_extraction_messages(messages)
    if not extraction_messages:
        return []

    try:
        from .model_providers.client import generate_chat_completion

        result, _ = await generate_chat_completion(
            settings=settings,
            model=model,
            messages=extraction_messages,
            enable_thinking=False,
            reasoning_effort="low",
            tools=None,
        )
        return _parse_extraction_result(result)
    except Exception:
        logger.exception("Memory extraction failed")
        return []


_PUNCT_RE = re.compile(r"[,.;:!?\"'()\[\]{}<>,.;:\s，。、；：\u201c\u201d\u2018\u2019【】（）]+")


def _normalize_text(text: str) -> str:
    """Normalize text for dedup: lowercase, collapse whitespace, strip punctuation."""
    text = text.lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    text = " ".join(text.split())
    return text


def _is_similar_to_existing(new_text: str, existing_normalized: set[str], threshold: float = 0.7) -> bool:
    """Check if new_text is similar to any existing memory text.

    Uses normalized exact match + substring containment + token overlap.
    """
    norm = _normalize_text(new_text)
    if not norm:
        return True

    # 1. Exact normalized match
    if norm in existing_normalized:
        return True

    # 2. Substring containment: if new text is contained in or contains existing
    for existing in existing_normalized:
        if len(norm) > 3 and len(existing) > 3:
            if norm in existing or existing in norm:
                return True

    # 3. Character bigram overlap (works well for CJK text)
    new_bigrams = set(norm[i:i+2] for i in range(len(norm) - 1)) if len(norm) >= 2 else set()
    if new_bigrams:
        for existing in existing_normalized:
            existing_bigrams = set(existing[i:i+2] for i in range(len(existing) - 1)) if len(existing) >= 2 else set()
            if not existing_bigrams:
                continue
            intersection = new_bigrams & existing_bigrams
            union = new_bigrams | existing_bigrams
            if union and len(intersection) / len(union) >= threshold:
                return True

    return False


def _has_blocked_tags(tags: list[str]) -> bool:
    """Check if any tag is in the project-scoped blacklist."""
    for tag in tags:
        normalized_tag = tag.strip().lower().replace("_", " ").replace("-", " ")
        for blocked in _BLOCKED_TAGS:
            blocked_normalized = blocked.lower().replace("_", " ").replace("-", " ")
            if normalized_tag == blocked_normalized:
                return True
    return False


def _has_allowed_global_tags(tags: list[str]) -> bool:
    """Check if tags clearly describe user-level global memory."""
    for tag in tags:
        normalized_tag = tag.strip().lower().replace("_", " ").replace("-", " ")
        for allowed in _ALLOWED_GLOBAL_TAGS:
            allowed_normalized = allowed.lower().replace("_", " ").replace("-", " ")
            if normalized_tag == allowed_normalized:
                return True
    return False


def _global_memory_texts_for_dedup(store: MemoryStore) -> set[str]:
    """Return normalized global memory texts for auto-extraction dedup."""
    return {
        _normalize_text(item.text)
        for item in store.list()
        if item.scope != "workspace"
    }


async def extract_and_store_memories(
    store: MemoryStore,
    messages: list[dict[str, Any]],
    model: str,
    settings: Any,
    *,
    conversation_id: str = "",
    workspace_id: str = "",
) -> list[MemoryItem]:
    """Extract memories and store them. Returns list of newly stored items."""
    candidates = await extract_memories_from_conversation(messages, model, settings)
    if not candidates:
        return []

    stored: list[MemoryItem] = []
    # Auto extraction writes global memories only, so workspace memories should
    # not affect whether a user-level global preference can be stored.
    existing_normalized = _global_memory_texts_for_dedup(store)

    for candidate in candidates:
        text = str(candidate.get("text") or "").strip()
        if not text:
            continue

        tags = candidate.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        tags = [str(t).strip() for t in tags if str(t).strip()][:6]

        # Reject project-scoped memories by tag
        if _has_blocked_tags(tags):
            logger.debug("Rejected project-scoped memory (blocked tag): %s", text[:80])
            continue

        if not _has_allowed_global_tags(tags):
            logger.debug("Rejected memory without allowed global tag: %s", text[:80])
            continue

        # Fuzzy dedup against existing memories
        if _is_similar_to_existing(text, existing_normalized):
            logger.debug("Rejected duplicate memory: %s", text[:80])
            continue

        existing_normalized.add(_normalize_text(text))

        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            text=text[:500],
            tags=[str(t).strip()[:24] for t in tags],
            enabled=True,
            source="auto",
            scope="global",
            workspace_id="",
            conversation_id=conversation_id,
        )
        try:
            store.add(item)
            stored.append(item)
        except ValueError:
            continue

    if stored:
        logger.info("Extracted %d new memories from conversation %s", len(stored), conversation_id)

    return stored
