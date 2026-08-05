"""模型可调用的本地记忆工具。"""

from __future__ import annotations

import uuid
from typing import Any

from runtime.tool_registry import ToolRegistry, ToolSpec


_PROJECT_SCOPE_TAGS = frozenset({
    "project",
    "project knowledge",
    "project structure",
    "project info",
    "architecture decision",
    "technical selection",
    "tech stack",
    "technology stack",
})


def _parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = raw.replace("，", ",").replace("；", ",").replace(";", ",").split(",")
        tags = [part.strip() for part in parts if part.strip()]
    elif isinstance(raw, list):
        tags = [str(part).strip() for part in raw if str(part).strip()]
    else:
        tags = []
    return tags[:6]


def _normalize_tag(tag: str) -> str:
    return tag.strip().lower().replace("_", " ").replace("-", " ")


def _memory_scope(args: dict[str, Any], tags: list[str]) -> str:
    requested = str(args.get("scope") or "").strip().lower()
    if requested in {"workspace", "project"}:
        return "workspace"
    if requested in {"global", "user"}:
        return "global"
    if any(_normalize_tag(tag) in _PROJECT_SCOPE_TAGS for tag in tags):
        return "workspace"
    return "global"


async def _memory_save_handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    """由 AI 保存记忆条目。"""
    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "text is required"}

    tags = _parse_tags(args.get("tags"))
    scope = _memory_scope(args, tags)
    workspace_id = str(getattr(context, "workspace_id", "") or "")
    if scope == "workspace" and not workspace_id:
        return {
            "error": True,
            "message": "workspace-scoped memory requires a current workspace context",
        }

    from runtime.memory_store import MemoryItem

    item = MemoryItem(
        id=f"mem_{uuid.uuid4().hex[:10]}",
        text=text[:500],
        tags=tags,
        enabled=True,
        source="conversation",
        scope=scope,
        workspace_id=workspace_id if scope == "workspace" else "",
    )
    store = context.settings.memory_store
    saved = store.add(item)
    return {
        "success": True,
        "id": saved.id,
        "text": saved.text,
        "scope": saved.scope,
        "workspace_id": saved.workspace_id,
        "message": f"saved memory: {saved.text[:80]}",
    }


async def _memory_recall_handler(args: dict[str, Any], context: Any) -> dict[str, Any]:
    """由 AI 召回相关记忆。"""
    query = str(args.get("query") or "").strip()
    limit = min(int(args.get("limit") or 10), 50)

    store = context.settings.memory_store
    all_memories = store.list_applicable(getattr(context, "workspace_id", ""))
    enabled = [m for m in all_memories if m.enabled and m.text]

    if not enabled:
        return {"memories": [], "message": "no available memories"}

    if not query:
        selected = sorted(enabled, key=lambda m: m.updated_at, reverse=True)[:limit]
    else:
        import re

        query_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
        query_tokens = {t for t in query_tokens if len(t) >= 2}

        scored = []
        for memory in enabled:
            score = 0.0
            text_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", memory.text.lower()))
            tag_tokens = set(tag.lower() for tag in memory.tags)
            overlap = (text_tokens | tag_tokens) & query_tokens
            score += len(overlap) * 2.0
            if memory.usage_count > 5:
                score += 1.0
            scored.append((memory, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        selected = [memory for memory, _ in scored[:limit]]

    results = []
    for memory in selected:
        results.append({
            "id": memory.id,
            "text": memory.text,
            "tags": memory.tags,
            "source": memory.source,
            "scope": memory.scope,
            "workspace_id": memory.workspace_id,
            "usage_count": memory.usage_count,
        })

    store.batch_record_usage([memory.id for memory in selected])

    return {
        "memories": results,
        "count": len(results),
    }


def register_memory_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="memory.save",
            name="Save memory",
            description=(
                "Save one long-term memory. Use global scope only for user "
                "preferences, communication style, identity, and cross-project "
                "habits. Use workspace scope for project facts, tech stack, "
                "architecture decisions, paths, and task-specific knowledge. "
                "Each memory should contain one concise fact."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Memory text, summarized as one concise fact.",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags, for example: preference, coding, project",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["global", "workspace"],
                        "description": "global for user-level memory; workspace for project-specific facts",
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
            name="Recall memory",
            description=(
                "Recall relevant memories. Results are automatically limited to "
                "global memories plus memories from the current workspace."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keywords",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of memories to return, default 10",
                    },
                },
            },
            requires_confirmation=False,
        ),
        _memory_recall_handler,
    )
