"""Task contract continuity helpers.

The model owns semantic task judgment.  This module only applies explicit
model-declared continuity and derives success-condition facts from the current
contract.  It must not infer a follow-up route from short user wording, promote
tool effects into task intent, or replace the model's current target.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.agent_strategy.document_completion import (
    contract_expects_text_output as _document_contract_expects_text_output,
)


VALID_SCOPE_RELATIONS: frozenset[str] = frozenset({
    "new",
    "continue",
    "revise",
    "replace",
})


def apply_task_continuity(
    contract: dict[str, Any],
    *,
    previous_contract: dict[str, Any] | None,
    current_user_content: str,
) -> dict[str, Any]:
    """Fill missing continuation fields without replacing current model semantics.

    The previous contract is historical evidence. Once the current model has
    selected a goal, deliverable, capability, or state-change requirement, that
    current value wins. The anchor may only fill fields omitted by the current
    model proposal.
    """
    result = dict(contract)
    if not isinstance(previous_contract, dict):
        result["scope_relation"] = normalize_scope_relation(result.get("scope_relation"))
        result.setdefault("revision_request", "")
        return result

    relation = normalize_scope_relation(result.get("scope_relation"))
    result["scope_relation"] = relation
    if relation not in {"continue", "revise"}:
        result.setdefault("revision_request", "")
        return result

    anchor = task_continuity_anchor(previous_contract)
    explicit_fields = {
        str(item)
        for item in result.get("model_explicit_fields") or []
        if str(item or "").strip()
    }

    for key in ("goal", "capability_ids", "deliverables"):
        if key not in explicit_fields and key in anchor:
            result[key] = deepcopy(anchor[key])

    for key in (
        "intent",
        "requires_write",
        "requires_state_change",
        "requires_verification",
        "required_verification_modalities",
        "expected_document_coverage",
        "expected_min_output_chars",
    ):
        if key not in explicit_fields and key in anchor:
            result[key] = deepcopy(anchor[key])

    result.pop("continuity_anchor", None)
    result["continuity_anchor"] = task_continuity_anchor(result)
    result["revision_request"] = _clean_text(current_user_content, 500)
    result["source"] = "model_with_task_anchor"
    result["success_conditions"] = success_conditions_for_contract(result)
    return result


def should_apply_task_continuity(
    contract: dict[str, Any],
    *,
    current_user_content: str,
) -> bool:
    """Return whether a prior task anchor may be applied after model judgment.

    The previous task may affect the final contract only after the model has
    explicitly represented the current turn as a continuation or revision.
    """
    if not isinstance(contract, dict):
        return False
    relation = normalize_scope_relation(contract.get("scope_relation"))
    return bool(
        relation in {"continue", "revise"}
        and contract.get("scope_relation_source") == "model"
    )


def task_continuity_anchor(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the stable semantic target carried across continuation turns."""
    inherited = contract.get("continuity_anchor")
    source = inherited if isinstance(inherited, dict) else contract
    return {
        key: deepcopy(source[key])
        for key in (
            "intent",
            "goal",
            "requires_write",
            "requires_state_change",
            "requires_verification",
            "required_verification_modalities",
            "expected_document_coverage",
            "expected_min_output_chars",
            "capability_ids",
            "deliverables",
        )
        if key in source
    }


def success_conditions_for_contract(contract: dict[str, Any]) -> list[str]:
    required_modalities = {
        str(item or "").strip().lower()
        for item in contract.get("required_verification_modalities") or []
        if str(item or "").strip()
    }
    conditions = [
        "target_deliverable_success"
        if contract.get("requires_write") or contract.get("requires_state_change")
        else "",
        "target_deliverable_verification" if contract.get("requires_verification") else "",
        "target_visual_verification"
        if contract.get("requires_verification") and "visual" in required_modalities
        else "",
        "document_output_coverage" if contract.get("expected_document_coverage") else "",
        "document_min_output_chars"
        if _safe_int(contract.get("expected_min_output_chars")) > 0
        and _contract_expects_document_output(contract)
        else "",
        "final_answer_with_evidence",
    ]
    return [condition for condition in conditions if condition]


def normalize_scope_relation(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SCOPE_RELATIONS else "new"


def _contract_expects_document_output(contract: dict[str, Any]) -> bool:
    return _document_contract_expects_text_output(contract)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]
