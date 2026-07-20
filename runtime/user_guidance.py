"""User guidance queue for in-flight conversation runs.

User guidance is a user-authored semantic update sent while a Run is active.
It is not a runtime intervention strategy.  The runtime records it, interrupts
model streaming at a safe point, and presents the new user text plus existing
run facts back to the model.
"""

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
