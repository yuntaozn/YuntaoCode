"""Automatic memory extraction from conversation history."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from .memory_store import MemoryItem, MemoryStore

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """你是一个记忆提取助手。从下面的对话中提取值得长期记住的信息。

提取类别:
- 用户偏好 (代码风格、沟通方式、工具使用习惯、界面偏好)
- 项目知识 (项目结构、技术栈、约定规范、常用路径)
- 用户身份 (角色、团队、专业领域)
- 重要决策 (架构选择、方案确认、技术选型)

规则:
1. 只提取明确的事实和偏好，不提取临时任务细节
2. 每条记忆只包含一个事实，用一句简洁的中文概括
3. 为每条记忆标注 1-3 个分类标签（英文）
4. 不要提取已经在对话中临时处理的一次性信息
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


async def extract_and_store_memories(
    store: MemoryStore,
    messages: list[dict[str, Any]],
    model: str,
    settings: Any,
    *,
    conversation_id: str = "",
) -> list[MemoryItem]:
    """Extract memories and store them. Returns list of newly stored items."""
    candidates = await extract_memories_from_conversation(messages, model, settings)
    if not candidates:
        return []

    stored: list[MemoryItem] = []
    # Deduplicate against existing memories
    existing_texts = set()
    for item in store.list():
        normalized = " ".join(item.text.lower().split())
        existing_texts.add(normalized)

    for candidate in candidates:
        text = str(candidate.get("text") or "").strip()
        if not text:
            continue
        # Simple dedup check
        normalized = " ".join(text.lower().split())
        if normalized in existing_texts:
            continue
        existing_texts.add(normalized)

        tags = candidate.get("tags") or []
        if not isinstance(tags, list):
            tags = []

        item = MemoryItem(
            id=f"mem_{uuid.uuid4().hex[:10]}",
            text=text,
            tags=[str(t).strip()[:24] for t in tags if str(t).strip()][:6],
            enabled=True,
            source="auto",
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
