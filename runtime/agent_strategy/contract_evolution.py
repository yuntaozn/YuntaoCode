"""任务契约续接辅助函数。

语义任务判断由模型负责。本模块只应用模型明确声明的续接关系，并根据当前契约
派生成功条件事实；不得根据简短用户措辞推断追问路线，不得把工具效果提升为任务意图，
也不得替换模型当前目标。"""

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
    """补齐缺失的续接字段，但不替换当前模型语义。

    上一契约只是历史证据。当前模型一旦选定目标、交付物、能力或状态变更要求，
    当前值优先；锚点只可补齐当前模型提案中遗漏的字段。"""
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
    """返回模型判断后是否可应用上一任务锚点。

    只有模型明确将当前轮次表示为续接或修订时，上一任务才可影响最终契约。"""
    if not isinstance(contract, dict):
        return False
    relation = normalize_scope_relation(contract.get("scope_relation"))
    return bool(
        relation in {"continue", "revise"}
        and contract.get("scope_relation_source") == "model"
    )


def task_continuity_anchor(contract: dict[str, Any]) -> dict[str, Any]:
    """返回跨续接轮次传递的稳定语义目标。"""
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
