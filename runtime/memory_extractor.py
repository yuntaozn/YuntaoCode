"""从对话中提取候选记忆。"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from .memory_store import MemoryItem, MemoryStore

logger = logging.getLogger(__name__)

# 保存时必须拒绝的标签：这些标签表示项目范围事实。
_BLOCKED_TAGS = frozenset({
    "project_knowledge", "project-knowledge", "project knowledge",
    "项目知识", "项目知识 - 技术栈",
    "project_structure", "project-info",
    "architecture_decision",
    "technical_selection", "tech_stack", "technology_stack",
    "技术选型", "技术栈",
})

# 允许自动提升为全局记忆的标签。自动提取有意保持狭窄：
# 项目事实必须以工作区范围显式保存，
# 避免泄漏到全局记忆。
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
    """为提取模型构建紧凑的对话表示。"""
    lines: list[str] = []
    # 只包含近期用户和助手消息
    relevant = [m for m in messages if m.get("role") in ("user", "assistant")]
    # 最多取最后 20 条消息
    for msg in relevant[-20:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = "\n".join(text_parts)
        # 截断过长消息
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
    """将模型的提取结果解析为记忆条目。"""
    text = raw.strip()
    # 尝试在响应中查找 JSON 数组
    if "[" in text:
        start = text.index("[")
        # 查找匹配的闭合方括号
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

    # 模型返回 [] 或空响应时
    if text in ("[]", ""):
        return []

    logger.warning("Failed to parse extraction result: %s", text[:200])
    return []


async def extract_memories_from_conversation(
    messages: list[dict[str, Any]],
    model: str,
    settings: Any,
) -> list[dict[str, Any]]:
    """从对话历史中提取记忆候选。

    返回 ``{"text": ..., "tags": [...]}`` 字典列表；没有候选时返回空列表。"""
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
    """为去重规范化文本：转小写、合并空白并去除标点。"""
    text = text.lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    text = " ".join(text.split())
    return text


def _is_similar_to_existing(new_text: str, existing_normalized: set[str], threshold: float = 0.7) -> bool:
    """检查 new_text 是否与任一现有记忆文本相似。

    使用规范化精确匹配、子串包含和词元重叠三种方法。"""
    norm = _normalize_text(new_text)
    if not norm:
        return True

    # 1. 规范化后的精确匹配
    if norm in existing_normalized:
        return True

    # 2. 子串包含：新文本被现有文本包含或包含现有文本
    for existing in existing_normalized:
        if len(norm) > 3 and len(existing) > 3:
            if norm in existing or existing in norm:
                return True

    # 3. 字符二元组重叠（适合中日韩文本）
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
    """检查是否有标签位于项目范围黑名单中。"""
    for tag in tags:
        normalized_tag = tag.strip().lower().replace("_", " ").replace("-", " ")
        for blocked in _BLOCKED_TAGS:
            blocked_normalized = blocked.lower().replace("_", " ").replace("-", " ")
            if normalized_tag == blocked_normalized:
                return True
    return False


def _has_allowed_global_tags(tags: list[str]) -> bool:
    """检查标签是否明确描述用户级全局记忆。"""
    for tag in tags:
        normalized_tag = tag.strip().lower().replace("_", " ").replace("-", " ")
        for allowed in _ALLOWED_GLOBAL_TAGS:
            allowed_normalized = allowed.lower().replace("_", " ").replace("-", " ")
            if normalized_tag == allowed_normalized:
                return True
    return False


def _global_memory_texts_for_dedup(store: MemoryStore) -> set[str]:
    """返回供自动提取去重使用的规范化全局记忆文本。"""
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
    """提取并保存记忆，返回新保存的条目列表。"""
    candidates = await extract_memories_from_conversation(messages, model, settings)
    if not candidates:
        return []

    stored: list[MemoryItem] = []
    # 自动提取只写入全局记忆，因此工作区记忆不应
    # 影响用户级全局偏好能否保存。
    existing_normalized = _global_memory_texts_for_dedup(store)

    for candidate in candidates:
        text = str(candidate.get("text") or "").strip()
        if not text:
            continue

        tags = candidate.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        tags = [str(t).strip() for t in tags if str(t).strip()][:6]

        # 根据标签拒绝项目范围记忆
        if _has_blocked_tags(tags):
            logger.debug("Rejected project-scoped memory (blocked tag): %s", text[:80])
            continue

        if not _has_allowed_global_tags(tags):
            logger.debug("Rejected memory without allowed global tag: %s", text[:80])
            continue

        # 与现有记忆进行模糊去重
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
