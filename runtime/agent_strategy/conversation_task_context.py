from __future__ import annotations

from typing import Any

from runtime.agent_strategy import classifiers as _clf
from runtime.agent_strategy import task_lineage as _lineage


def is_user_guidance_message(message: Any) -> bool:
    metadata = getattr(message, "metadata", {}) or {}
    return bool(metadata.get("guidance") and metadata.get("during_run"))


def has_recent_task_context(conversation: Any | None, current_content: str) -> bool:
    """返回短请求是否属于现有对话任务。"""
    if conversation is None:
        return False
    current = current_content.strip()
    diagnostic_feedback = _clf.looks_like_diagnostic_feedback(current)
    for message in reversed(getattr(conversation, "messages", [])[-12:]):
        if is_user_guidance_message(message):
            continue
        role = str(getattr(message, "role", "") or "")
        previous_content = str(getattr(message, "content", "") or "").strip()
        metadata = getattr(message, "metadata", {}) or {}
        if diagnostic_feedback and role == "assistant" and isinstance(metadata, dict):
            contract = metadata.get("task_contract")
            if isinstance(contract, dict) and (
                contract.get("goal")
                or contract.get("intent") not in {None, "", "answer_only"}
                or contract.get("raw_model_contract")
            ):
                return True
        if role == "user" and previous_content and previous_content != current:
            return True
        if role != "assistant":
            continue
        if not isinstance(metadata, dict):
            continue
        contract = metadata.get("task_contract")
        if isinstance(contract, dict) and (
            contract.get("goal")
            or contract.get("intent") not in {None, "", "answer_only"}
        ):
            return True
    return False


def task_lineage_candidates(
    conversation: Any | None,
    current_content: str,
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    return _lineage.collect_task_lineage_candidates(
        conversation,
        current_content,
        limit=limit,
    )


def task_lineage_availability(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> dict[str, Any]:
    """返回不暴露历史目标的中性任务血缘可用性信息。

    Runtime 可以知道存在历史任务候选，但不应判断当前请求是否为续接。只有模型侧
    任务契约要求血缘事实后，才暴露候选详情。"""

    candidate_count = len([item for item in candidates or [] if isinstance(item, dict)])
    return {
        "schema_version": "task_lineage_availability.v1",
        "kind": "task_lineage_availability",
        "available": candidate_count > 0,
        "candidate_count": candidate_count,
        "candidate_content_exposure": "model_requested",
        "rule": (
            "Historical task candidates exist as auditable facts, but their content is "
            "intentionally withheld until the model task contract requests lineage. "
            "If the current request depends on prior actions, state, artifacts, objects, "
            "or omitted references and cannot stand alone, request lineage before "
            "finalizing the goal instead of weakening or guessing it."
        ),
    }


def referenced_task_candidate_contract(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    candidate_id: Any,
) -> dict[str, Any] | None:
    return _lineage.referenced_candidate_contract(candidates, candidate_id)
