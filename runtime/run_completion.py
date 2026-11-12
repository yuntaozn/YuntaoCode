"""完成证据兼容辅助函数。

主执行循环不再插入独立完成审查。本模块保留旧版完成声明的解析和决策记录结构，
供已存 Run、RunEvidence、Replay 与 Evaluation 兼容读取。完成证据包的构建放在
``completion_evidence_pack`` 中。"""

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


def build_outcome_facts(
    *,
    task_contract: dict[str, Any] | None,
    assessment: dict[str, Any],
    model_error: bool,
    stopped: bool,
    verification_required: bool,
    verification_missing: bool,
) -> dict[str, str]:
    """分开记录执行结束、模型目标声明和验证证据，不从自然语言猜测完成。"""
    contract = task_contract or {}
    task_known = bool(contract) and contract.get("source") != "main_execution_pending" and (
        contract.get("intent") != "undetermined" or contract.get("source") == "model_execution"
    )
    goal_status = "unknown"
    if assessment and (not assessment.get("goal_closed") or assessment.get("remaining_work")):
        goal_status = "incomplete"
    elif assessment.get("goal_closed"):
        # 这是模型的明确声明，不替代独立的执行状态与验证证据。
        goal_status = "complete"
    return {
        "execution_status": "failed" if model_error else "stopped" if stopped else "completed",
        "goal_status": goal_status,
        "verification_status": (
            "unknown" if not task_known else "not_required" if not verification_required
            else "missing" if verification_missing else "satisfied"
        ),
    }


def extract_completion_self_assessment(
    content: str,
) -> tuple[str, dict[str, Any] | None]:
    """提取由模型明确作出的完成自评。

    旧版提示允许模型在首行使用紧凑 JSON 头。本函数仅供显式兼容读取；
    主执行循环不调用它，也不从普通答案正文提取任务状态。"""

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
    """描述模型可观察到的完成选择。

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
