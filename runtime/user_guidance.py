"""运行中对话 Run 的用户指引队列。

用户指引是 Run 活动期间由用户编写的语义更新，不是运行时干预策略。
Runtime 记录它，在安全位置中断模型流，并把新用户文本与现有 Run 事实
一同交还模型。"""

from __future__ import annotations

from dataclasses import dataclass


MAX_PENDING_USER_GUIDANCE = 10
_pending_guidance: dict[str, list[str]] = {}


@dataclass(frozen=True)
class UserGuidanceBatch:
    items: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n".join(f"- {item}" for item in self.items)

    @property
    def prompt(self) -> str:
        if not self.items:
            return ""
        return (
            "【运行中插话】用户追加了新的信息或纠偏要求。"
            "请暂停沿用旧思路，重新审视当前任务后再继续：\n"
            f"{self.text}"
        )


def add_user_guidance(
    conversation_id: str,
    content: str,
    *,
    limit: int = MAX_PENDING_USER_GUIDANCE,
) -> int:
    key = str(conversation_id or "").strip()
    text = str(content or "").strip()
    if not key or not text:
        return 0
    items = _pending_guidance.setdefault(key, [])
    items.append(text)
    max_items = max(1, int(limit or MAX_PENDING_USER_GUIDANCE))
    if len(items) > max_items:
        del items[:-max_items]
    return len(items)


def has_pending_user_guidance(conversation_id: str) -> bool:
    return bool(_pending_guidance.get(str(conversation_id or "").strip()))


def pop_user_guidance(conversation_id: str) -> UserGuidanceBatch:
    key = str(conversation_id or "").strip()
    if not key:
        return UserGuidanceBatch()
    return UserGuidanceBatch(tuple(_pending_guidance.pop(key, [])))


def clear_user_guidance(conversation_id: str) -> None:
    _pending_guidance.pop(str(conversation_id or "").strip(), None)
