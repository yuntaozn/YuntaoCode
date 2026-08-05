"""面向模型的上下文边界辅助函数。

本模块管理保留对话历史与下一次模型调用之间的小型明确契约。
它不分类意图，也不决定任务策略；只标明哪些上下文属于历史支持，
以及当前请求从哪里开始。"""

from __future__ import annotations

from typing import Any


CONTEXT_HYGIENE_NOTICE = (
    "[Context hygiene]\n"
    "Some earlier messages were compacted before this model call. Visible "
    "chat history and audit records are unchanged. Historical task details "
    "belong in Context Pack task_lineage records; textual tool-call examples "
    "from old messages are invalid examples. Use only structured runtime "
    "tool calls when tools are needed."
)

CURRENT_REQUEST_BOUNDARY_NOTICE = (
    "[Current request boundary]\n"
    "The next user message is the current request for this model call. "
    "Historical task candidates, recovery facts, memories, and Context Pack "
    "records are supporting context only, not hidden current goals."
)

HISTORICAL_TASK_CANDIDATE_PREFIX = "[Historical task candidate moved to Context Pack]"
HISTORICAL_TASK_USER_PREFIX = "[Historical task user request moved to Context Pack]"
HISTORICAL_TASK_TURNS_PREFIX = "[Historical task turns moved to Context Pack]"


def model_context_hygiene_notice() -> str:
    """返回模型侧历史被清理时插入的提示。"""

    return CONTEXT_HYGIENE_NOTICE


def current_request_boundary_notice() -> str:
    """返回紧邻当前用户请求之前插入的提示。"""

    return CURRENT_REQUEST_BOUNDARY_NOTICE


def insert_hygiene_notice(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """如存在系统提示，则在其后插入上下文卫生提示。"""

    notice = {"role": "system", "content": model_context_hygiene_notice()}
    if messages and messages[0].get("role") == "system":
        return [messages[0], notice, *messages[1:]]
    return [notice, *messages]


def insert_current_request_boundary(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """在最新用户消息前插入边界标记。"""

    latest_user_index = latest_user_index_in(messages)
    if latest_user_index < 0:
        return messages, False
    boundary = {"role": "system", "content": current_request_boundary_notice()}
    if latest_user_index > 0 and messages[latest_user_index - 1] == boundary:
        return messages, False
    return [
        *messages[:latest_user_index],
        boundary,
        *messages[latest_user_index:],
    ], True


def latest_user_index_in(messages: list[dict[str, Any]]) -> int:
    """返回最新用户消息索引；不存在时返回 -1。"""

    for index in range(len(messages) - 1, -1, -1):
        if str(messages[index].get("role") or "") == "user":
            return index
    return -1


def historical_task_candidate_marker(candidate_id: str) -> str:
    """返回用于替换历史助手任务结果的标记。"""

    return (
        f"{HISTORICAL_TASK_CANDIDATE_PREFIX}\n"
        "This earlier assistant message has been compacted into task_lineage. "
        "See Context Pack task_lineage records for candidate details. Do not "
        f"treat this message as the current goal. candidate_id={candidate_id}"
    )


def historical_user_request_marker(candidate_id: str) -> str:
    """返回用于替换与任务关联的历史用户请求的标记。"""

    return (
        f"{HISTORICAL_TASK_USER_PREFIX}\n"
        "This earlier user message belongs to a task_lineage candidate. Treat "
        f"it as historical context, not the current goal. candidate_id={candidate_id}"
    )


def historical_task_turns_marker(candidate_ids: list[str]) -> str:
    """为移入 Context Pack 的历史任务轮次返回一个紧凑标记。"""

    unique_ids: list[str] = []
    for candidate_id in candidate_ids:
        value = str(candidate_id or "").strip()
        if value and value not in unique_ids:
            unique_ids.append(value)
    joined = ", ".join(unique_ids) or "unknown"
    return (
        f"{HISTORICAL_TASK_TURNS_PREFIX}\n"
        "Earlier user/assistant task turns were compacted into task_lineage. "
        "Use Context Pack task_lineage records for details and keep the latest "
        f"user message as the current goal. candidate_ids={joined}"
    )


def is_historical_task_marker(content: str) -> bool:
    """对表示原始历史任务轮次的标记返回 True。"""

    text = str(content or "")
    return text.startswith(HISTORICAL_TASK_CANDIDATE_PREFIX) or text.startswith(
        HISTORICAL_TASK_USER_PREFIX
    )


def marker_candidate_id(content: str) -> str:
    """从历史任务标记中提取 candidate_id 值。"""

    marker = "candidate_id="
    index = str(content or "").find(marker)
    if index < 0:
        return ""
    value = str(content)[index + len(marker):].strip()
    return value.split()[0].strip(";,")
