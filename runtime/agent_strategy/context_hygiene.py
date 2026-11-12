"""模型执行前的对话上下文卫生处理。

UI 与 Run 审计保留完整历史；模型侧清理失败日志与文本工具调用示例，
保留近期用户原话和助手承诺的角色与时序，不依据任务意图标签删除对话。"""

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
    historical_task_turns_marker,
    insert_current_request_boundary,
    insert_hygiene_notice,
    is_historical_task_marker,
    latest_user_index_in,
    marker_candidate_id,
    model_context_hygiene_notice,
)


DEFAULT_MAX_ASSISTANT_CHARS = 1800
DEFAULT_MAX_PRIOR_USER_LOG_CHARS = 1200


@dataclass
class ContextHygieneReport:
    """一次请求所执行模型上下文清理的摘要。"""

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
    """返回面向模型的消息及上下文卫生报告。"""

    report = ContextHygieneReport()
    latest_user_index = latest_user_index_in(messages)
    result: list[dict[str, Any]] = []
    recent_start = max(0, len(messages) - 8)

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
            )
            if cleaned is None:
                report.dropped_messages += 1
                continue
            result.append(_cleaned_message(
                role, content, cleaned, report, None if index >= recent_start else max_assistant_chars,
            ))
            continue

        if role == "user" and index != latest_user_index:
            cleaned = _sanitize_prior_user_message(
                content, report, max_chars=max_prior_user_log_chars,
            )
            result.append(_cleaned_message(
                role, content, cleaned, report, None if index >= recent_start else max_prior_user_log_chars,
            ))
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
    """模型上下文卫生提示的向后兼容公开名称。"""
    return model_context_hygiene_notice()


def _sanitize_assistant_message(
    content: str,
    report: ContextHygieneReport,
) -> str | None:
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
    max_chars: int | None,
) -> dict[str, Any]:
    value = cleaned
    if max_chars is not None and len(value) > max_chars:
        value = truncate(value, max_chars)
        report.truncated_messages += 1
    if value != original:
        report.sanitized_messages += 1
        return {"role": role, "content": value}
    return {"role": role, "content": original}


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

