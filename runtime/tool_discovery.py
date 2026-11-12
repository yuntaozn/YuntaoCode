"""按模型显式查询加载原始工具定义；不读取用户消息或判断任务意图。"""

from __future__ import annotations

import json
import re
from collections import Counter
from math import fsum
from typing import Any, Callable

from runtime.agent_strategy.classifiers import finish_reason_indicates_truncation, parse_tool_arguments_strict


DISCOVERY_TOOL_ID = "runtime.discover_tools"
DISCOVERY_TOOL_NAME = "runtime__discover_tools"


def discovery_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": DISCOVERY_TOOL_NAME,
            "description": (
                "Find and load available tool definitions for the next model round. "
                "Search tool IDs/descriptions using query (ranked lexical matches, including CJK character pairs), "
                "or load exact tool_ids. Empty arguments list namespaces. "
                "Includes local files, shell, web, configured MCP services, and optional "
                "runtime.update_task bookkeeping. Loading does not execute tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": 300},
                    "tool_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "additionalProperties": False,
            },
        },
    }


class ToolDiscovery:
    """只维护本次 Run 已加载的定义，权限仍由原执行入口校验。"""

    def __init__(
        self, load_catalog: Callable[[], tuple[list[dict[str, Any]], dict[str, str]]],
        *, emit: Callable[[dict[str, Any]], None],
    ) -> None:
        self._load_catalog = load_catalog
        self._catalog: dict[str, dict[str, Any]] = {}
        self._aliases: dict[str, str] = {}
        self._loaded: dict[str, None] = {}
        self._emit = emit

    def model_tools(self) -> list[dict[str, Any]]:
        return [discovery_tool(), *(self._catalog[key] for key in self._loaded)]

    async def handle_call(
        self, tool_call: dict[str, Any], tool_id: str,
        arguments: dict[str, Any], finish_reason: str,
    ) -> dict[str, Any] | None:
        if tool_id != DISCOVERY_TOOL_ID:
            return None
        try:
            if finish_reason_indicates_truncation(finish_reason):
                raise ValueError("Discovery arguments were truncated; no definitions loaded.")
            arguments, error = parse_tool_arguments_strict(tool_call["function"].get("arguments") or "{}")
            if error:
                raise ValueError("Discovery arguments must be a complete JSON object.")
            result = self._discover(arguments)
        except ValueError as exc:
            result = {"status": "rejected", "error": str(exc)}
        self._emit({"event": "tool_discovery", "tool_call_id": tool_call["id"], **result})
        return {
            "role": "tool", "tool_call_id": tool_call["id"],
            "name": tool_call["function"]["name"],
            "content": json.dumps(result, ensure_ascii=False),
        }

    def _discover(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict) or set(arguments) - {"query", "tool_ids", "offset", "limit"}:
            raise ValueError("Expected query, tool_ids, offset, or limit.")
        query = arguments.get("query", "")
        ids = arguments.get("tool_ids", [])
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 5)
        if not isinstance(query, str) or len(query) > 300:
            raise ValueError("query must be a string of at most 300 characters.")
        if not isinstance(ids, list) or len(ids) > 10 or any(not isinstance(key, str) or not key.strip() for key in ids):
            raise ValueError("tool_ids must contain at most 10 non-empty tool IDs.")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("offset must be non-negative and limit must be between 1 and 10.")
        if query.strip() and ids:
            raise ValueError("Use query or tool_ids, not both.")
        # 显式发现时读取当前目录，允许本轮新连接的 MCP 出现；已失效定义也随之移除。
        tools, names = self._load_catalog()
        self._catalog = {names[tool["function"]["name"]]: tool for tool in tools}
        self._aliases = names
        self._loaded = {key: None for key in self._loaded if key in self._catalog}
        if not query.strip() and not ids:
            counts = Counter(key.split(".")[0] for key in self._catalog)
            namespaces = sorted(counts)
            page = namespaces[offset:offset + limit]
            return {
                "status": "catalog", "namespaces": {key: counts[key] for key in page},
                "total": len(namespaces),
                "next_offset": offset + limit if offset + limit < len(namespaces) else None,
            }
        if ids:
            selected = list(dict.fromkeys(self._aliases.get(key, key) for key in ids))
            missing = [key for key in selected if key not in self._catalog]
            if missing:
                raise ValueError(f"Unknown or unavailable tools: {', '.join(missing)}")
            total, next_offset = len(selected), None
        else:
            terms = _query_terms(query)
            name_terms = {
                key: set(re.findall(r"[^\W_]+", key.casefold().rpartition(".")[2]))
                for key in self._catalog
            }
            frequencies = Counter(term for words in name_terms.values() for term in words)
            descriptions = {
                key: str(tool["function"].get("description") or "").casefold()
                for key, tool in self._catalog.items()
            }
            # 降低通用词和字对的权重，保留具体查询的区分度。
            description_frequencies = Counter(
                term for description in descriptions.values() for term in terms if term in description
            )
            scored = []
            for key in self._catalog:
                normalized = key.casefold()
                description = descriptions[key]
                if not any(term in normalized or term in description for term in terms):
                    continue
                namespace, _, name = normalized.rpartition(".")
                name_words = name_terms[key]
                namespace_words = set(re.findall(r"[^\W_]+", namespace))
                # 只排序模型给出的查询，不读取任务；同分时用 ID 保证分页稳定。
                score = (
                    sum(term == normalized or term == name for term in terms),
                    len(terms & name_words),
                    len(terms & name_words) / len(name_words) if name_words else 0,
                    fsum(1 / frequencies[term] for term in terms & name_words),
                    len(terms & namespace_words),
                    sum(term in normalized for term in terms),
                    sum(term in description for term in terms),
                    fsum(1 / description_frequencies[term] for term in terms if term in description),
                )
                scored.append((score, key))
            matches = [key for _, key in sorted(scored, key=lambda item: (tuple(-n for n in item[0]), item[1]))]
            total = len(matches)
            selected = matches[offset:offset + limit]
            next_offset = offset + limit if offset + limit < total else None
        for key in selected:
            self._loaded[key] = None
        return {
            "status": "loaded", "query": query,
            "tools": [{"id": key, "name": self._catalog[key]["function"]["name"]} for key in selected],
            "total": total, "next_offset": next_offset,
            "definitions_available_next_round": True,
        }


def _query_terms(query: str) -> set[str]:
    """中文连续文本增加相邻字对，不做意图分类、同义词扩写或工具映射。"""
    normalized = query.casefold()
    terms = set(normalized.split())
    for word in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]+", normalized):
        terms.update(word[index:index + 2] for index in range(len(word) - 1))
    return terms
