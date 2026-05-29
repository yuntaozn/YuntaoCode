"""Memory tools for AI to save and recall long-term memories."""

from __future__ import annotations

import uuid
from typing import Any

from runtime.tool_registry import ToolRegistry, ToolSpec


async def _memory_save_handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    """AI saves a memory item."""
    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}

    tags_raw = args.get("tags")
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = []

    from runtime.memory_store import MemoryItem

    item = MemoryItem(
        id=f"mem_{uuid.uuid4().hex[:10]}",
        text=text[:500],
        tags=tags[:6],
        enabled=True,
        source="conversation",
    )
    store = context.settings.memory_store
    saved = store.add(item)
    return {
        "success": True,
        "id": saved.id,
        "text": saved.text,
        "message": f"已保存记忆: {saved.text[:80]}",
    }


async def _memory_recall_handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    """AI recalls relevant memories."""
    query = str(args.get("query") or "").strip()
    limit = min(int(args.get("limit") or 10), 50)

    store = context.settings.memory_store
    all_memories = store.list()
    enabled = [m for m in all_memories if m.enabled and m.text]

    if not enabled:
        return {"memories": [], "message": "暂无可用记忆"}

    if not query:
        # Return most recently used/created
        selected = sorted(enabled, key=lambda m: m.updated_at, reverse=True)[:limit]
    else:
        # Simple keyword matching
        import re
        query_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
        query_tokens = {t for t in query_tokens if len(t) >= 2}

        scored = []
        for m in enabled:
            score = 0.0
            text_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", m.text.lower()))
            tag_tokens = set(t.lower() for t in m.tags)
            overlap = (text_tokens | tag_tokens) & query_tokens
            score += len(overlap) * 2.0
            if m.usage_count > 5:
                score += 1.0
            scored.append((m, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [m for m, _ in scored[:limit]]

    results = []
    for m in selected:
        results.append({
            "id": m.id,
            "text": m.text,
            "tags": m.tags,
            "source": m.source,
            "usage_count": m.usage_count,
        })

    # Record usage
    store.batch_record_usage([m.id for m in selected])

    return {
        "memories": results,
        "count": len(results),
    }


def register_memory_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="memory.save",
            name="保存记忆",
            description=(
                "保存一条值得长期记住的信息到用户记忆库。"
                "适合保存用户偏好、项目知识、重要决策等。"
                "每条记忆应只包含一个事实，用一句话概括。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "记忆内容，一句话概括（最多500字）",
                    },
                    "tags": {
                        "type": "string",
                        "description": "分类标签，逗号分隔，如: preference, coding, project",
                    },
                },
                "required": ["text"],
            },
            requires_confirmation=False,
        ),
        _memory_save_handler,
    )

    registry.register(
        ToolSpec(
            id="memory.recall",
            name="回忆记忆",
            description=(
                "从用户记忆库中检索相关记忆。"
                "可以按关键词搜索，也可以不传 query 获取最近使用的记忆。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数上限，默认 10",
                    },
                },
            },
            requires_confirmation=False,
        ),
        _memory_recall_handler,
    )
