"""Conversation context hygiene before model execution.

The UI and run audit keep full history.  The model-facing context should not
replay noisy historical failures, textual tool-call examples, or old task goals
as if they were current instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.agent_strategy.context_noise import (
    classify_context_noise,
    historical_failure_summary,
    historical_process_summary,
    historical_user_feedback_summary,
    strip_tool_markup_like_text,
    truncate,
)
from runtime.agent_strategy.model_context_boundary import (
    current_request_boundary_notice,
    historical_task_candidate_marker,
    historical_task_turns_marker,
    historical_user_request_marker,
    insert_current_request_boundary,
    insert_hygiene_notice,
    is_historical_task_marker,
    latest_user_index_in,
    marker_candidate_id,
    model_context_hygiene_notice,
)
from runtime.agent_strategy.task_lineage import task_candidate_from_message


DEFAULT_MAX_ASSISTANT_CHARS = 1800
DEFAULT_MAX_PRIOR_USER_LOG_CHARS = 1200


@dataclass
class ContextHygieneReport:
    """Summary of model-context cleanup performed for one request."""

    sanitized_messages: int = 0
    dropped_messages: int = 0
    truncated_messages: int = 0
    tool_markup_messages: int = 0
    failed_run_messages: int = 0
    process_log_messages: int = 0
    task_candidate_messages: int = 0
    task_user_anchor_messages: int = 0
    compacted_task_marker_messages: int = 0
    current_request_boundary_inserted: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any((
            self.sanitized_messages,
            self.dropped_messages,
            self.truncated_messages,
            self.tool_markup_messages,
            self.failed_run_messages,
            self.process_log_messages,
            self.task_candidate_messages,
            self.task_user_anchor_messages,
            self.compacted_task_marker_messages,
            self.current_request_boundary_inserted,
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "context_hygiene.v1",
            "changed": self.changed,
            "sanitized_messages": self.sanitized_messages,
            "dropped_messages": self.dropped_messages,
            "truncated_messages": self.truncated_messages,
            "tool_markup_messages": self.tool_markup_messages,
            "failed_run_messages": self.failed_run_messages,
            "process_log_messages": self.process_log_messages,
            "task_candidate_messages": self.task_candidate_messages,
            "task_user_anchor_messages": self.task_user_anchor_messages,
            "compacted_task_marker_messages": self.compacted_task_marker_messages,
            "current_request_boundary_inserted": self.current_request_boundary_inserted,
            "notes": list(self.notes),
        }


def sanitize_model_context(
    messages: list[dict[str, Any]],
    *,
    max_assistant_chars: int = DEFAULT_MAX_ASSISTANT_CHARS,
    max_prior_user_log_chars: int = DEFAULT_MAX_PRIOR_USER_LOG_CHARS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return model-facing messages plus a hygiene report."""

    report = ContextHygieneReport()
    latest_user_index = latest_user_index_in(messages)
    historical_user_links = _historical_task_user_links(messages, latest_user_index)
    result: list[dict[str, Any]] = []

    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        content = _message_text(message.get("content"))
        if not content:
            result.append(_public_message(message))
            continue

        if role == "assistant":
            cleaned = _sanitize_assistant_message(
                content,
                report,
                metadata=_message_metadata(message),
                index=index,
            )
            if cleaned is None:
                report.dropped_messages += 1
                continue
            result.append(_cleaned_message(role, content, cleaned, report, max_assistant_chars))
            continue

        if role == "user" and index != latest_user_index:
            if index in historical_user_links:
                cleaned = _historical_user_request_marker(historical_user_links[index])
                report.task_user_anchor_messages += 1
            else:
                cleaned = _sanitize_prior_user_message(
                    content,
                    report,
                    max_chars=max_prior_user_log_chars,
                )
            result.append(_cleaned_message(role, content, cleaned, report, max_prior_user_log_chars))
            continue

        result.append(_public_message(message))

    result, compacted_markers = _compact_historical_task_markers(result)
    if compacted_markers:
        report.compacted_task_marker_messages += compacted_markers

    if report.changed:
        report.notes.append(
            "Earlier noisy run/process messages were condensed before model execution; "
            "UI history and audit records are unchanged."
        )
        result = insert_hygiene_notice(result)
        result, inserted_boundary = insert_current_request_boundary(result)
        report.current_request_boundary_inserted = inserted_boundary
    return result, report.to_dict()


def context_hygiene_notice() -> str:
    """Backward-compatible public name for the model hygiene notice."""
    return model_context_hygiene_notice()


def _sanitize_assistant_message(
    content: str,
    report: ContextHygieneReport,
    *,
    metadata: dict[str, Any] | None = None,
    index: int = 0,
) -> str | None:
    candidate = task_candidate_from_message(
        role="assistant",
        content=content,
        metadata=metadata,
        index=index,
    )
    if candidate:
        report.task_candidate_messages += 1
        return _historical_task_candidate_marker(candidate)

    noise = classify_context_noise(content)

    if noise.has_tool_markup:
        report.tool_markup_messages += 1
    if noise.has_failed_run:
        report.failed_run_messages += 1
    if noise.has_process_log:
        report.process_log_messages += 1

    if noise.has_tool_markup or noise.has_failed_run:
        return historical_failure_summary(content, noise)
    if noise.has_process_log and len(content) > 800:
        return historical_process_summary()
    return content


def _sanitize_prior_user_message(
    content: str,
    report: ContextHygieneReport,
    *,
    max_chars: int,
) -> str:
    noise = classify_context_noise(content)

    if noise.has_tool_markup:
        report.tool_markup_messages += 1
    if noise.has_process_log:
        report.process_log_messages += 1

    if noise.has_tool_markup and noise.has_process_log:
        return historical_user_feedback_summary()
    if noise.has_tool_markup:
        return strip_tool_markup_like_text(content, max_chars)
    if noise.has_process_log and len(content) > max_chars:
        return truncate(content, max_chars)
    return content


def _cleaned_message(
    role: str,
    original: str,
    cleaned: str,
    report: ContextHygieneReport,
    max_chars: int,
) -> dict[str, Any]:
    value = cleaned
    if len(value) > max_chars:
        value = truncate(value, max_chars)
        report.truncated_messages += 1
    if value != original:
        report.sanitized_messages += 1
        role = "system" if is_historical_task_marker(value) else role
        return {"role": role, "content": value}
    return {"role": role, "content": original}


def _historical_task_user_links(
    messages: list[dict[str, Any]],
    latest_user_index: int,
) -> dict[int, dict[str, str]]:
    links: dict[int, dict[str, str]] = {}
    for index, message in enumerate(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        candidate = task_candidate_from_message(
            role="assistant",
            content=_message_text(message.get("content")),
            metadata=_message_metadata(message),
            index=index,
        )
        if not candidate:
            continue
        for previous_index in range(index - 1, -1, -1):
            if previous_index == latest_user_index:
                break
            previous = messages[previous_index]
            if str(previous.get("role") or "") != "user":
                continue
            links.setdefault(previous_index, {
                "candidate_id": str(candidate.get("candidate_id") or ""),
            })
            break
    return links


def _historical_task_candidate_marker(candidate: dict[str, Any]) -> str:
    candidate_id = str(candidate.get("candidate_id") or "")
    return historical_task_candidate_marker(candidate_id)


def _historical_user_request_marker(link: dict[str, str]) -> str:
    candidate_id = str(link.get("candidate_id") or "")
    return historical_user_request_marker(candidate_id)


def _compact_historical_task_markers(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    marker_ids: list[str] = []
    marker_index: int | None = None
    marker_count = 0
    result: list[dict[str, Any]] = []
    for message in messages:
        content = str(message.get("content") or "")
        if str(message.get("role") or "") == "system" and is_historical_task_marker(content):
            marker_count += 1
            candidate_id = marker_candidate_id(content)
            if candidate_id and candidate_id not in marker_ids:
                marker_ids.append(candidate_id)
            if marker_index is None:
                marker_index = len(result)
            continue
        result.append(message)
    if marker_index is None:
        return messages, 0
    compact = {
        "role": "system",
        "content": historical_task_turns_marker(marker_ids),
    }
    result.insert(min(marker_index, len(result)), compact)
    return result, max(0, marker_count - 1)


def _message_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def _message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("_yuntao_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _public_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": message.get("role"),
        "content": message.get("content"),
    }

