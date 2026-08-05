"""完成循环的证据辅助函数。

完成循环让模型根据运行时事实决定如实结束或继续工作。本模块记录模型可观察的选择，
供 RunEvidence、Workbench、Replay 和 Evaluation 检查。完成证据包的构建放在
``completion_evidence_pack`` 中，使展示预算与格式和决策审计保持分离。"""

from __future__ import annotations

import json
from typing import Any

from runtime.completion_evidence_pack import (
    COMPLETION_EVIDENCE_BUDGET,
    COMPLETION_EVIDENCE_PACK_SCHEMA_VERSION,
    build_completion_evidence_pack,
    format_completion_evidence_pack,
    summarize_completion_evidence_pack_for_decision,
)


COMPLETION_DECISION_SCHEMA_VERSION = "completion_decision.v1"
COMPLETION_SELF_ASSESSMENT_SCHEMA_VERSION = "completion_self_assessment.v1"


def extract_completion_self_assessment(
    content: str,
) -> tuple[str, dict[str, Any] | None]:
    """提取由模型明确作出的完成自评。

    当模型选择结束时，完成审查在首行使用紧凑 JSON 头；面向用户的答案仍以
    普通 Markdown 放在头部下方，避免用大型 JSON 字符串包裹整段答案。
    对于不遵循头部协议的模型，普通文本仍是受支持的回退形式。"""

    original = str(content or "").strip()
    if not original:
        return original, None
    lines = original.splitlines()
    candidate = lines[0].strip()
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return original, None
    if not isinstance(payload, dict):
        return original, None
    if (
        payload.get("schema_version") != COMPLETION_SELF_ASSESSMENT_SCHEMA_VERSION
        or payload.get("kind") != "completion_self_assessment"
        or not isinstance(payload.get("goal_closed"), bool)
    ):
        return original, None
    final_answer = "\n".join(lines[1:]).strip()
    if not final_answer:
        return original, None
    assessment = {
        "schema_version": COMPLETION_SELF_ASSESSMENT_SCHEMA_VERSION,
        "kind": "completion_self_assessment",
        "source": "model_declared",
        "goal_closed": bool(payload["goal_closed"]),
        "remaining_work": _assessment_strings(payload.get("remaining_work")),
        "verification_limits": _assessment_strings(
            payload.get("verification_limits")
        ),
    }
    return final_answer, assessment


def build_completion_decision(
    *,
    review_count: int,
    run_result: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]] | None,
    content: str = "",
    finish_reason: str = "",
    reason: str = "",
    evidence_pack: dict[str, Any] | None = None,
    self_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """描述模型在完成审查后的下一步选择。

    返回值是审计证据，有意避免 ``must_stop`` 或 ``must_continue`` 这类
    命令式建议。"""

    calls = [item for item in (tool_calls or []) if isinstance(item, dict)]
    text = str(content or "").strip()
    result = run_result if isinstance(run_result, dict) else {}
    action = _observable_action(calls, text, reason)
    assessment = (
        dict(self_assessment)
        if isinstance(self_assessment, dict)
        and self_assessment.get("kind") == "completion_self_assessment"
        else {}
    )
    return {
        "schema_version": COMPLETION_DECISION_SCHEMA_VERSION,
        "source": "model_observed_behavior",
        "review_count": max(0, int(review_count or 0)),
        "action": action,
        "reason": str(reason or ""),
        "finish_reason": str(finish_reason or ""),
        "result_status": str(result.get("status") or ""),
        "risks": [str(item) for item in result.get("risks") or [] if str(item or "").strip()],
        "tool_call_count": len(calls),
        "content_chars": len(text),
        "self_assessment": assessment,
        "evidence_pack": summarize_completion_evidence_pack_for_decision(evidence_pack),
    }


def _observable_action(tool_calls: list[dict[str, Any]], content: str, reason: str) -> str:
    if tool_calls:
        return "continue_with_tools"
    if reason in {"malformed_tool_call", "dangling_action"}:
        return "repair_protocol"
    if content.strip():
        return "final_answer_candidate"
    return "no_observable_decision"


def _assessment_strings(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:500])
        if len(result) >= limit:
            break
    return result
