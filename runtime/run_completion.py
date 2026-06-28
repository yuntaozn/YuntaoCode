"""Completion-loop evidence helpers.

The completion loop lets the model decide whether to finish honestly or keep
working from runtime facts. This module does not choose tools or block model
decisions; it records the model's observable choice so RunEvidence, Workbench,
Replay, and Evaluation can inspect what happened.
"""

from __future__ import annotations

from typing import Any


COMPLETION_DECISION_SCHEMA_VERSION = "completion_decision.v1"


def build_completion_decision(
    *,
    review_count: int,
    run_result: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]] | None,
    content: str = "",
    finish_reason: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Describe the model's next-step choice after a completion review.

    The returned value is audit evidence. It intentionally avoids an
    imperative recommendation such as "must_stop" or "must_continue".
    """

    calls = [item for item in (tool_calls or []) if isinstance(item, dict)]
    text = str(content or "").strip()
    result = run_result if isinstance(run_result, dict) else {}
    action = _observable_action(calls, text, reason)
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
    }


def _observable_action(tool_calls: list[dict[str, Any]], content: str, reason: str) -> str:
    if tool_calls:
        return "continue_with_tools"
    if reason in {"malformed_tool_call", "dangling_action"}:
        return "repair_protocol"
    if content.strip():
        return "final_answer_candidate"
    return "no_observable_decision"
