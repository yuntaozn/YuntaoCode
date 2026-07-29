from __future__ import annotations

from typing import Any

from runtime.agent_strategy import classifiers as _clf
from runtime.agent_strategy import task_lineage as _lineage


def is_user_guidance_message(message: Any) -> bool:
    metadata = getattr(message, "metadata", {}) or {}
    return bool(metadata.get("guidance") and metadata.get("during_run"))


def has_recent_task_context(conversation: Any | None, current_content: str) -> bool:
    """Return whether a short request belongs to an existing conversation task."""
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
    """Return neutral lineage availability without exposing historical goals.

    The runtime may know that historical task candidates exist, but it should
    not decide whether the current request is a continuation.  Candidate details
    are exposed only after the model-side task contract asks for lineage facts.
    """

    candidate_count = len([item for item in candidates or [] if isinstance(item, dict)])
    return {
        "schema_version": "task_lineage_availability.v1",
        "kind": "task_lineage_availability",
        "available": candidate_count > 0,
        "candidate_count": candidate_count,
        "candidate_content_exposure": "model_requested",
        "rule": (
            "Historical task candidates exist as auditable facts. Their goals "
            "are not included until the model task contract asks for lineage."
        ),
    }


def referenced_task_candidate_contract(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    candidate_id: Any,
) -> dict[str, Any] | None:
    return _lineage.referenced_candidate_contract(candidates, candidate_id)
