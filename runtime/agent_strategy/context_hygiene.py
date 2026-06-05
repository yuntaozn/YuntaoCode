"""Conversation context hygiene before model execution.

The UI and run audit should keep the full conversation history.  The model
context does not need to replay every failed attempt verbatim, especially when
older assistant messages contain textual tool-call markers or deterministic
failure summaries.  This module keeps that cleanup pure and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TOOL_MARKUP_TERMS: tuple[str, ...] = (
    "<toolcall",
    "</toolcall",
    "<|functioncall",
    "<|functioncallbegin",
    "functioncallbegin",
    "filesystem__",
    "code__",
    "document__",
    "shell__",
)

FAILED_RUN_TERMS: tuple[str, ...] = (
    "未完成：本轮有工具执行失败",
    "系统检测到模型最终回复停在待执行语句",
    "工具调用缺少必填参数",
    "无效调用不会进入人工确认",
    "失败记录：",
    "失败或风险：",
    "未观察到成功写入文件",
    "未观察到成功验证工具调用",
)

PROCESS_LOG_TERMS: tuple[str, ...] = (
    "过程记录",
    "思考过程",
    "已调用",
    "调用失败",
)

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
            "notes": list(self.notes),
        }


def sanitize_model_context(
    messages: list[dict[str, Any]],
    *,
    max_assistant_chars: int = DEFAULT_MAX_ASSISTANT_CHARS,
    max_prior_user_log_chars: int = DEFAULT_MAX_PRIOR_USER_LOG_CHARS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return a cleaner model context and a report.

    The latest user message is preserved exactly.  Older assistant/process
    messages that contain failed textual tool calls are collapsed into neutral
    recovery facts so the model does not learn the broken format as an example.
    """

    report = ContextHygieneReport()
    latest_user_index = _latest_user_index(messages)
    result: list[dict[str, Any]] = []

    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        content = _message_text(message.get("content"))
        if not content:
            result.append(message)
            continue

        if role == "assistant":
            cleaned = _sanitize_assistant_message(content, report)
            if cleaned is None:
                report.dropped_messages += 1
                continue
            if len(cleaned) > max_assistant_chars:
                cleaned = _truncate(cleaned, max_assistant_chars)
                report.truncated_messages += 1
            if cleaned != content:
                report.sanitized_messages += 1
                result.append({"role": role, "content": cleaned})
            else:
                result.append(message)
            continue

        if role == "user" and index != latest_user_index:
            cleaned = _sanitize_prior_user_message(
                content,
                report,
                max_chars=max_prior_user_log_chars,
            )
            if cleaned != content:
                report.sanitized_messages += 1
                result.append({"role": role, "content": cleaned})
            else:
                result.append(message)
            continue

        result.append(message)

    if report.changed:
        report.notes.append(
            "Earlier noisy run/process messages were condensed before model execution; UI history and audit records are unchanged."
        )
        result = _insert_hygiene_notice(result)
    return result, report.to_dict()


def context_hygiene_notice() -> str:
    """System note inserted when prior messages were cleaned."""
    return (
        "上下文卫生提示：部分历史消息包含失败的执行过程、文本式工具标记或半截产物，"
        "已在本轮模型上下文中压缩为恢复事实。不要模仿历史中的文本式工具调用写法；"
        "如需使用工具，必须使用运行时提供的结构化工具调用，并一次性补全必填参数。"
        "界面历史和审计记录没有被删除。"
    )


def _sanitize_assistant_message(content: str, report: ContextHygieneReport) -> str | None:
    has_markup = _contains_any(content, TOOL_MARKUP_TERMS)
    has_failure = _contains_any(content, FAILED_RUN_TERMS)
    has_process = _contains_any(content, PROCESS_LOG_TERMS)

    if has_markup:
        report.tool_markup_messages += 1
    if has_failure:
        report.failed_run_messages += 1
    if has_process:
        report.process_log_messages += 1

    if has_markup or has_failure:
        facts: list[str] = ["[历史运行摘要] 上一轮或更早的任务执行未能稳定完成。"]
        if has_markup:
            facts.append("历史中出现过文本式工具调用标记；这些是失败样本，不能作为本轮调用格式。")
        if "工具调用缺少必填参数" in content or "无效调用不会进入人工确认" in content:
            facts.append("历史中出现过工具参数不完整；本轮若调用工具必须补全必填参数。")
        if "未观察到成功验证工具调用" in content:
            facts.append("历史中缺少成功验证证据；本轮完成写入后需要读取或测试验证。")
        if "新增/变更文件：" in content or "变更文件" in content:
            paths = _extract_path_lines(content)
            if paths:
                facts.append("历史涉及文件：" + "；".join(paths[:4]))
        return "\n".join(facts)

    if has_process and len(content) > 800:
        return "[历史用户反馈摘要] 历史消息包含较长执行过程记录；本轮只应参考用户目标和已验证事实，不应复用其中的失败调用格式。"

    return content


def _sanitize_prior_user_message(
    content: str,
    report: ContextHygieneReport,
    *,
    max_chars: int,
) -> str:
    has_markup = _contains_any(content, TOOL_MARKUP_TERMS)
    has_process = _contains_any(content, PROCESS_LOG_TERMS)

    if has_markup:
        report.tool_markup_messages += 1
    if has_process:
        report.process_log_messages += 1

    if has_markup and has_process:
        return "[历史用户反馈摘要] 用户曾反馈模型输出了错误的工具调用过程；本轮不要复用该历史格式。"
    if has_markup:
        return _strip_tool_markup_like_text(content, max_chars)
    if has_process and len(content) > max_chars:
        return _truncate(content, max_chars)
    return content


def _insert_hygiene_notice(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notice = {"role": "system", "content": context_hygiene_notice()}
    if messages and messages[0].get("role") == "system":
        return [messages[0], notice, *messages[1:]]
    return [notice, *messages]


def _latest_user_index(messages: list[dict[str, Any]]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if str(messages[index].get("role") or "") == "user":
            return index
    return -1


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


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


def _truncate(text: str, max_chars: int) -> str:
    max_chars = max(200, int(max_chars or 0))
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... 历史消息已截断 ..."


def _strip_tool_markup_like_text(text: str, max_chars: int) -> str:
    cleaned = text
    for term in TOOL_MARKUP_TERMS:
        cleaned = cleaned.replace(term, "[历史工具标记]")
        cleaned = cleaned.replace(term.upper(), "[历史工具标记]")
    return _truncate(cleaned, max_chars)


def _extract_path_lines(text: str) -> list[str]:
    paths: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-* ").strip()
        if not line:
            continue
        if "\\" in line or "/" in line or line.endswith((".html", ".py", ".js", ".md", ".docx")):
            if len(line) <= 220:
                paths.append(line)
    return paths
