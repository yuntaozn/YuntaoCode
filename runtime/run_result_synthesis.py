"""根据 RunResult 事实进行模型支持的最终答案合成。

本模块管理 Run 结束后的答案合成请求结构，不判断 Run 是否完成、
不选择工具，也不重新解释任务契约。"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from runtime.agent_strategy.prompts import result_synthesis_prompt
from runtime.model_providers import generate_chat_completion


RESULT_SYNTHESIS_REQUEST_CONTEXT_SCHEMA_VERSION = "result_synthesis_request_context.v1"
RESULT_SYNTHESIS_USER_CONTENT_LIMIT = 4000
RESULT_SYNTHESIS_REQUEST_HEAD_CHARS = 1400
RESULT_SYNTHESIS_REQUEST_TAIL_CHARS = 2200
RESULT_SYNTHESIS_MARKER_LINE_LIMIT = 12
RESULT_SYNTHESIS_REFERENCE_LIMIT = 16
RESULT_SYNTHESIS_MARKER_ITEM_CHARS = 260

_REQUEST_MARKERS = (
    "不要",
    "不能",
    "只",
    "必须",
    "需要",
    "请",
    "输出",
    "保存",
    "文件",
    "路径",
    "目标",
    "格式",
    "中文",
    "英文",
    "do not",
    "don't",
    "only",
    "must",
    "need",
    "please",
    "output",
    "save",
    "file",
    "path",
    "target",
    "format",
    "chinese",
    "english",
)

_REFERENCE_PATTERNS = (
    re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE),
    re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|]+"),
    re.compile(
        r"(?<![\w.-])[\w./\\-]+\."
        r"(?:py|js|ts|tsx|jsx|vue|html|css|json|md|docx|pdf|pptx|xlsx|csv|png|jpg|jpeg|gif|glb|blend|mp4)"
        r"(?![\w.-])",
        re.IGNORECASE,
    ),
)


def build_result_synthesis_messages(
    *,
    workspace_path: str,
    user_content: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any],
    previous_answer: str,
    tool_events: list[dict[str, Any]] | None = None,
    completion_decisions: list[dict[str, Any]] | None = None,
    task_route_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """构建用于最终答案合成的有界消息。"""

    prompt = result_synthesis_prompt(
        workspace_path,
        task_contract,
        run_result,
        previous_answer=previous_answer,
        tool_events=tool_events,
        completion_decisions=completion_decisions,
        task_route_evidence=task_route_evidence,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
    ]
    if user_content:
        context = build_result_synthesis_request_context(user_content)
        messages.append({
            "role": "user",
            "content": format_result_synthesis_request_context(context),
        })
    return messages


def build_result_synthesis_request_context(user_content: str) -> dict[str, Any]:
    """根据当前用户消息构建有界参考包。

    此参考包保留请求边界和看似明确的标记，供最终答案措辞使用；它不是任务路由器，
    也不覆盖 RunResult。"""

    text = str(user_content or "").strip()
    head, tail = _head_tail(text)
    return {
        "schema_version": RESULT_SYNTHESIS_REQUEST_CONTEXT_SCHEMA_VERSION,
        "kind": "result_synthesis_request_context",
        "boundary": "presentation_reference_only",
        "source": "current_user_message",
        "budget": {
            "text_chars": RESULT_SYNTHESIS_USER_CONTENT_LIMIT,
            "head_chars": RESULT_SYNTHESIS_REQUEST_HEAD_CHARS,
            "tail_chars": RESULT_SYNTHESIS_REQUEST_TAIL_CHARS,
            "marker_lines": RESULT_SYNTHESIS_MARKER_LINE_LIMIT,
            "references": RESULT_SYNTHESIS_REFERENCE_LIMIT,
        },
        "original_chars": len(text),
        "omitted_chars": _omitted_chars(text, head, tail),
        "head": head,
        "tail": tail,
        "marker_lines": _marker_lines(text),
        "references": _references(text),
    }


def format_result_synthesis_request_context(context: dict[str, Any]) -> str:
    """为答案合成模型轮次渲染请求参考包。"""

    lines = [
        "User request reference for final answer synthesis:",
        f"- schema: {context.get('schema_version') or RESULT_SYNTHESIS_REQUEST_CONTEXT_SCHEMA_VERSION}",
        f"- boundary: {context.get('boundary') or 'presentation_reference_only'}",
        "- source of truth: RunResult, tool events, artifacts, and verification evidence",
        "- note: this reference preserves user wording for final-answer context; it is not a new task request",
        f"- original chars: {context.get('original_chars') or 0}",
    ]
    omitted = int(context.get("omitted_chars") or 0)
    if omitted > 0:
        lines.append(f"- omitted middle chars: {omitted}")

    head = str(context.get("head") or "").strip()
    tail = str(context.get("tail") or "").strip()
    if head:
        lines.extend(["", "Request head:", head])
    if tail:
        lines.extend(["", "Request tail:", tail])

    marker_lines = [str(item) for item in context.get("marker_lines") or [] if str(item).strip()]
    if marker_lines:
        lines.append("")
        lines.append("Explicit request marker lines:")
        lines.extend(f"- {item}" for item in marker_lines)

    references = [str(item) for item in context.get("references") or [] if str(item).strip()]
    if references:
        lines.append("")
        lines.append("Referenced files, paths, or URLs:")
        lines.extend(f"- {item}" for item in references)
    return "\n".join(lines)


async def generate_result_synthesis_answer(
    *,
    settings: Any,
    model: str,
    workspace_path: str,
    user_content: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any],
    previous_answer: str,
    tool_events: list[dict[str, Any]] | None = None,
    completion_decisions: list[dict[str, Any]] | None = None,
    task_route_evidence: dict[str, Any] | None = None,
    model_call: Callable[..., Awaitable[tuple[str, dict[str, Any]]]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """根据已观察到的 RunResult 事实生成最终用户答案。"""

    caller = model_call or generate_chat_completion
    answer, metadata = await caller(
        settings=settings,
        model=model,
        messages=build_result_synthesis_messages(
            workspace_path=workspace_path,
            user_content=user_content,
            task_contract=task_contract,
            run_result=run_result,
            previous_answer=previous_answer,
            tool_events=tool_events,
            completion_decisions=completion_decisions,
            task_route_evidence=task_route_evidence,
        ),
        enable_thinking=False,
        reasoning_effort="low",
        tools=None,
    )
    return answer.strip(), metadata


def _head_tail(text: str) -> tuple[str, str]:
    if len(text) <= RESULT_SYNTHESIS_USER_CONTENT_LIMIT:
        return text, ""
    head = text[:RESULT_SYNTHESIS_REQUEST_HEAD_CHARS].strip()
    tail = text[-RESULT_SYNTHESIS_REQUEST_TAIL_CHARS:].strip()
    return head, tail


def _omitted_chars(text: str, head: str, tail: str) -> int:
    return max(0, len(text) - len(head) - len(tail))


def _marker_lines(text: str) -> list[str]:
    markers = tuple(marker.lower() for marker in _REQUEST_MARKERS)
    lines: list[str] = []
    for unit in _request_units(text):
        lowered = unit.lower()
        if not any(marker in lowered for marker in markers):
            continue
        short = _short(unit, RESULT_SYNTHESIS_MARKER_ITEM_CHARS)
        if short not in lines:
            lines.append(short)
        if len(lines) >= RESULT_SYNTHESIS_MARKER_LINE_LIMIT:
            break
    return lines


def _request_units(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or len(lines[0]) <= RESULT_SYNTHESIS_MARKER_ITEM_CHARS * 2:
        return lines
    return [
        item.strip()
        for item in re.split(r"(?<=[。！？!?；;])\s*", lines[0])
        if item.strip()
    ]


def _references(text: str) -> list[str]:
    refs: list[str] = []
    for pattern in _REFERENCE_PATTERNS:
        for match in pattern.finditer(text):
            ref = _short(match.group(0).rstrip("，。；;,.）)]"), RESULT_SYNTHESIS_MARKER_ITEM_CHARS)
            if ref and ref not in refs:
                refs.append(ref)
            if len(refs) >= RESULT_SYNTHESIS_REFERENCE_LIMIT:
                return refs
    return refs


def _short(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"
