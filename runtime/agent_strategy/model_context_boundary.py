"""Model-facing context boundary helpers.

This module owns the small, explicit contract between preserved conversation
history and the next model call.  It does not classify intent or decide task
strategy; it only names which context is historical support and where the
current request begins.
"""

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
    """Return the notice inserted when model-facing history was sanitized."""

    return CONTEXT_HYGIENE_NOTICE


def current_request_boundary_notice() -> str:
    """Return the notice inserted immediately before the current user request."""

    return CURRENT_REQUEST_BOUNDARY_NOTICE


def insert_hygiene_notice(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert the hygiene notice after an existing system prompt when present."""

    notice = {"role": "system", "content": model_context_hygiene_notice()}
    if messages and messages[0].get("role") == "system":
        return [messages[0], notice, *messages[1:]]
    return [notice, *messages]


def insert_current_request_boundary(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Insert a boundary marker immediately before the latest user message."""

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
    """Return the latest user-message index, or -1 when none exists."""

    for index in range(len(messages) - 1, -1, -1):
        if str(messages[index].get("role") or "") == "user":
            return index
    return -1


def historical_task_candidate_marker(candidate_id: str) -> str:
    """Return a marker replacing a historical assistant task result."""

    return (
        f"{HISTORICAL_TASK_CANDIDATE_PREFIX}\n"
        "This earlier assistant message has been compacted into task_lineage. "
        "See Context Pack task_lineage records for candidate details. Do not "
        f"treat this message as the current goal. candidate_id={candidate_id}"
    )


def historical_user_request_marker(candidate_id: str) -> str:
    """Return a marker replacing a historical user request linked to a task."""

    return (
        f"{HISTORICAL_TASK_USER_PREFIX}\n"
        "This earlier user message belongs to a task_lineage candidate. Treat "
        f"it as historical context, not the current goal. candidate_id={candidate_id}"
    )


def historical_task_turns_marker(candidate_ids: list[str]) -> str:
    """Return one compact marker for historical task turns moved to Context Pack."""

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
    """Return True for markers that represent original historical task turns."""

    text = str(content or "")
    return text.startswith(HISTORICAL_TASK_CANDIDATE_PREFIX) or text.startswith(
        HISTORICAL_TASK_USER_PREFIX
    )


def marker_candidate_id(content: str) -> str:
    """Extract a candidate_id value from a historical task marker."""

    marker = "candidate_id="
    index = str(content or "").find(marker)
    if index < 0:
        return ""
    value = str(content)[index + len(marker):].strip()
    return value.split()[0].strip(";,")
