"""Task contract evolution helpers.

The model owns the first semantic task judgment, while the runtime owns how a
contract evolves when the user follows up, an execution plan reveals a write
target, or tool facts prove that local state changed.  Keeping these rules here
prevents the base contract schema module from becoming another policy sink.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


VALID_INTENTS: frozenset[str] = frozenset({
    "answer_only",
    "read_only_analysis",
    "write_required",
    "document_export",
    "paper_workflow",
})

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
    """Apply a continuation relationship to a task contract."""
    result = dict(contract)
    if "hard_no_write_lock" in set(result.get("system_overrides") or []):
        result["scope_relation"] = normalize_scope_relation(result.get("scope_relation"))
        result.setdefault("revision_request", "")
        return result
    if not isinstance(previous_contract, dict):
        result["scope_relation"] = normalize_scope_relation(result.get("scope_relation"))
        result.setdefault("revision_request", "")
        return result

    relation = normalize_scope_relation(result.get("scope_relation"))
    if (
        relation == "new"
        and result.get("scope_relation_source") != "model"
        and looks_like_task_revision_followup(current_user_content)
    ):
        relation = "revise"
        result["scope_relation_source"] = "runtime_continuity_fallback"
    result["scope_relation"] = relation
    if relation not in {"continue", "revise"}:
        result.setdefault("revision_request", "")
        return result

    anchor = task_continuity_anchor(previous_contract)
    if _anchor_has_state_target(anchor) and _looks_like_observation_followup(current_user_content):
        _annotate_observation_followup(
            result,
            anchor=anchor,
            current_user_content=current_user_content,
        )

    anchored_deliverables = anchor.get("deliverables") if isinstance(anchor.get("deliverables"), list) else []
    proposed_deliverables = result.get("deliverables") if isinstance(result.get("deliverables"), list) else []
    preserve_external_state_target = _preserve_external_state_target(anchor, result)
    retargets_local_file_state = _retargets_local_file_state(result)
    retargets_read_only_answer = _retargets_read_only_answer(result)
    preserve_anchor_target = not (retargets_local_file_state or retargets_read_only_answer)

    if "goal" in anchor and preserve_anchor_target:
        result["goal"] = deepcopy(anchor["goal"])
    if "capability_ids" in anchor and preserve_anchor_target:
        result["capability_ids"] = _merge_capability_ids(
            anchor.get("capability_ids"),
            result.get("capability_ids"),
        )
    if (
        anchored_deliverables
        and preserve_anchor_target
        and not _deliverables_are_answer_only(anchored_deliverables)
    ):
        result["deliverables"] = deepcopy(anchored_deliverables)
    elif proposed_deliverables:
        result["deliverables"] = deepcopy(proposed_deliverables)
    elif anchored_deliverables:
        result["deliverables"] = deepcopy(anchored_deliverables)

    if retargets_local_file_state:
        result["requires_write"] = bool(result.get("requires_write")) or bool(result.get("requires_state_change"))
    elif retargets_read_only_answer:
        result["requires_write"] = False
    elif preserve_external_state_target:
        result["requires_write"] = bool(anchor.get("requires_write"))
    else:
        result["requires_write"] = bool(anchor.get("requires_write")) or bool(result.get("requires_write"))
    if retargets_local_file_state:
        result["requires_state_change"] = bool(result.get("requires_state_change")) or bool(result.get("requires_write"))
    elif retargets_read_only_answer:
        result["requires_state_change"] = False
    else:
        result["requires_state_change"] = (
            bool(anchor.get("requires_state_change"))
            or bool(result.get("requires_state_change"))
            or bool(result.get("requires_write"))
        )
    if result.get("requires_write"):
        result["requires_state_change"] = True
    if retargets_local_file_state:
        result["requires_verification"] = bool(result.get("requires_verification")) or bool(result.get("requires_state_change"))
        result["intent"] = _continuity_intent(
            None,
            result.get("intent"),
            requires_state_change=bool(result.get("requires_state_change")),
        )
    elif retargets_read_only_answer:
        result["requires_verification"] = bool(result.get("requires_verification"))
        result["intent"] = _intent_or_default(result.get("intent"), "read_only_analysis")
    else:
        result["requires_verification"] = (
            bool(anchor.get("requires_verification"))
            or bool(result.get("requires_verification"))
            or bool(result.get("requires_state_change"))
        )
        result["intent"] = _continuity_intent(
            anchor.get("intent"),
            result.get("intent"),
            requires_state_change=bool(result.get("requires_state_change")),
        )
    result["required_verification_modalities"] = _merge_verification_modalities(
        result.get("required_verification_modalities")
        if retargets_read_only_answer
        else anchor.get("required_verification_modalities"),
        result.get("required_verification_modalities"),
    )
    result["continuity_anchor"] = (
        task_continuity_anchor(result)
        if retargets_local_file_state or retargets_read_only_answer
        else anchor
    )
    result["revision_request"] = _clean_text(current_user_content, 500)
    result["source"] = "model_with_task_anchor"
    result["success_conditions"] = success_conditions_for_contract(result)
    return result


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
            "capability_ids",
            "deliverables",
        )
        if key in source
    }


def inherit_task_contract_for_followup(
    previous_contract: dict[str, Any],
    fallback_contract: dict[str, Any],
) -> dict[str, Any]:
    """Carry a previous task contract into an explicit execute-follow-up turn."""
    inherited = deepcopy(previous_contract) if isinstance(previous_contract, dict) else {}
    contract = dict(fallback_contract)
    for key in (
        "intent",
        "goal",
        "requires_write",
        "requires_state_change",
        "requires_verification",
        "required_verification_modalities",
        "expected_document_coverage",
        "capability_ids",
        "deliverables",
        "blockers",
        "confidence",
    ):
        if key in inherited:
            contract[key] = deepcopy(inherited[key])
    if _contract_expects_document_output(inherited):
        contract["expected_min_output_chars"] = deepcopy(
            inherited.get("expected_min_output_chars", 0)
        )
    else:
        contract["expected_min_output_chars"] = 0
    contract.update({
        "source": "conversation_context",
        "raw_model_contract": None,
        "scope_relation": "continue",
        "scope_relation_source": "runtime_explicit_followup",
        "continuity_anchor": task_continuity_anchor(inherited),
        "revision_request": "",
        "requires_plan": False,
        "first_action": _followup_first_action(contract),
    })
    if contract.get("requires_write"):
        contract["requires_state_change"] = True
    overrides = list(contract.get("system_overrides") or [])
    overrides.append("inherited_task_contract")
    contract["system_overrides"] = list(dict.fromkeys(str(item) for item in overrides if item))
    contract["success_conditions"] = success_conditions_for_contract(contract)
    return contract


def promote_task_contract_for_write_intent(
    contract: dict[str, Any],
    *,
    reason: str,
    path_hint: str = "",
    deliverable_kind: str = "code",
    description: str = "",
) -> bool:
    """Promote a contract when runtime facts show a write is now intended."""
    if not isinstance(contract, dict):
        return False
    if "hard_no_write_lock" in set(contract.get("system_overrides") or []):
        return False

    before = json.dumps(contract, ensure_ascii=False, sort_keys=True, default=str)
    kind = _normalize_deliverable_kind(deliverable_kind, path_hint=path_hint)
    _promote_deliverables_for_write(
        contract,
        kind=kind,
        path_hint=path_hint,
        description=description,
    )
    if contract.get("intent") not in {"document_export", "paper_workflow"}:
        contract["intent"] = "write_required"
    contract["requires_write"] = True
    contract["requires_state_change"] = True
    contract["requires_verification"] = True
    if str(contract.get("first_action") or "") in {"", "answer"}:
        contract["first_action"] = "write"

    overrides = list(contract.get("system_overrides") or [])
    if reason:
        overrides.append(str(reason))
    contract["system_overrides"] = list(dict.fromkeys(str(item) for item in overrides if item))
    contract["success_conditions"] = success_conditions_for_contract(contract)
    after = json.dumps(contract, ensure_ascii=False, sort_keys=True, default=str)
    return before != after


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


def looks_like_task_revision_followup(content: str) -> bool:
    """Return whether a short request revises or retries the active task."""
    text = str(content or "").strip().lower()
    if not text or len(text) > 120:
        return False
    terms = (
        "再试一次",
        "再来一次",
        "再做一次",
        "重新做",
        "重做",
        "继续做",
        "继续完成",
        "不理想",
        "没做好",
        "没有完成",
        "没有成功",
        "try again",
        "redo it",
        "do it again",
        "continue it",
        "continue the task",
        "improve it",
        "not good enough",
    )
    return any(term in text for term in terms)


def _looks_like_observation_followup(content: str) -> bool:
    """Return whether a follow-up asks to inspect/evaluate the current result.

    This is a continuity rule, not a scenario rule: the previous task anchor
    may identify what to inspect, but the current user wording decides whether
    this turn should change state again.
    """
    text = str(content or "").strip().lower()
    if not text or len(text) > 180:
        return False
    state_change_terms = (
        "redo",
        "do it again",
        "try again",
        "rebuild",
        "regenerate",
        "modify",
        "change",
        "fix",
        "optimize",
        "create",
        "generate",
        "run",
        "execute",
        "\u91cd\u65b0\u505a",
        "\u91cd\u505a",
        "\u518d\u505a",
        "\u518d\u6765\u4e00\u6b21",
        "\u4fee\u6539",
        "\u6539\u4e00\u4e0b",
        "\u8c03\u6574",
        "\u4f18\u5316",
        "\u4fee\u590d",
        "\u521b\u5efa",
        "\u751f\u6210",
        "\u6267\u884c",
        "\u5efa\u4e00\u4e2a",
        "\u5efa\u4e2a",
        "\u7ee7\u7eed\u505a",
    )
    if any(term in text for term in state_change_terms):
        return False
    observation_terms = (
        "look",
        "see",
        "inspect",
        "check",
        "review",
        "evaluate",
        "assess",
        "what does it look like",
        "can you see",
        "looks",
        "\u770b",
        "\u770b\u770b",
        "\u770b\u4e0b",
        "\u770b\u5230",
        "\u68c0\u67e5",
        "\u5206\u6790",
        "\u8bc4\u4ef7",
        "\u8bc4\u4f30",
        "\u5224\u65ad",
        "\u662f\u5426",
        "\u662f\u4e0d\u662f",
        "\u50cf\u4e0d\u50cf",
        "\u6548\u679c",
        "\u770b\u8d77\u6765",
        "\u770b\u4e0a\u53bb",
        "\u6563\u5f00",
    )
    return any(term in text for term in observation_terms)


def _annotate_observation_followup(
    contract: dict[str, Any],
    *,
    anchor: dict[str, Any],
    current_user_content: str,
) -> None:
    """Attach non-binding continuity guidance for model/tool strategy."""
    anchor_goal = _clean_text(anchor.get("goal") or contract.get("goal") or "previous task", 180)
    needs_visual = _observation_needs_visual_evidence(anchor, current_user_content)
    advisories = contract.get("continuity_advisories")
    if not isinstance(advisories, list):
        advisories = []
    advisories.append({
        "code": "possible_observation_followup",
        "message": (
            "The current follow-up may be asking to inspect or evaluate the "
            "previous result rather than repeat the previous state-changing "
            "action. This is guidance only; use the current user intent to "
            "choose whether to verify, answer, ask, or modify."
        ),
        "previous_goal": anchor_goal,
        "suggested_first_action": "verify" if needs_visual else "read",
        "verification_modalities_hint": ["visual"] if needs_visual else [],
    })
    contract["continuity_advisories"] = _dedupe_advisories(advisories)


def _observation_needs_visual_evidence(anchor: dict[str, Any], content: str) -> bool:
    modalities = {
        str(item or "").strip().lower()
        for item in anchor.get("required_verification_modalities") or []
        if str(item or "").strip()
    }
    if "visual" in modalities:
        return True
    text = str(content or "").strip().lower()
    visual_terms = (
        "visual",
        "screenshot",
        "render",
        "appearance",
        "looks",
        "see",
        "\u89c6\u89c9",
        "\u622a\u56fe",
        "\u6e32\u67d3",
        "\u6548\u679c",
        "\u770b\u5230",
        "\u770b\u8d77\u6765",
        "\u770b\u4e0a\u53bb",
        "\u50cf\u4e0d\u50cf",
        "\u6563\u5f00",
    )
    return any(term in text for term in visual_terms)


def _anchor_has_state_target(anchor: dict[str, Any]) -> bool:
    if bool(anchor.get("requires_write")) or bool(anchor.get("requires_state_change")):
        return True
    return "external_state" in _deliverable_kinds(anchor.get("deliverables"))


def _merge_capability_ids(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value or []:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
    return result[:6]


def _merge_verification_modalities(*values: Any) -> list[str]:
    allowed = {"structural", "visual", "behavioral", "content"}
    result: list[str] = []
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            text = str(item or "").strip().lower()
            if text in allowed and text not in result:
                result.append(text)
    return result[:4]


def _dedupe_advisories(values: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        message = str(item.get("message") or "").strip()
        if not code and not message:
            continue
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result[:6]


def _deliverables_are_answer_only(deliverables: list[Any]) -> bool:
    if not deliverables:
        return True
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "answer").strip().lower()
        if kind and kind != "answer":
            return False
    return True


def _deliverable_kinds(deliverables: Any) -> set[str]:
    if not isinstance(deliverables, list):
        return set()
    return {
        str(item.get("kind") or "").strip().lower()
        for item in deliverables
        if isinstance(item, dict) and str(item.get("kind") or "").strip()
    }


def _preserve_external_state_target(anchor: dict[str, Any], proposed: dict[str, Any]) -> bool:
    anchor_kinds = _deliverable_kinds(anchor.get("deliverables"))
    proposed_kinds = _deliverable_kinds(proposed.get("deliverables"))
    return (
        "external_state" in anchor_kinds
        and not bool(anchor.get("requires_write"))
        and bool(proposed.get("requires_write"))
        and bool(proposed_kinds)
        and proposed_kinds <= {"code", "file"}
    )


def _retargets_local_file_state(proposed: dict[str, Any]) -> bool:
    overrides = {str(item) for item in proposed.get("system_overrides") or []}
    if "normalized_local_file_state" in overrides:
        return True
    capability_ids = {
        str(item or "").strip()
        for item in proposed.get("capability_ids") or []
        if str(item or "").strip()
    }
    if "filesystem.local_state" not in capability_ids:
        return False
    return _has_delete_term(_contract_text(proposed))


def _retargets_read_only_answer(proposed: dict[str, Any]) -> bool:
    if bool(proposed.get("requires_write")) or bool(proposed.get("requires_state_change")):
        return False
    intent = _intent_or_default(proposed.get("intent"))
    if intent not in {"answer_only", "read_only_analysis"}:
        return False
    deliverables = proposed.get("deliverables") if isinstance(proposed.get("deliverables"), list) else []
    return _deliverables_are_answer_only(deliverables)


def _continuity_intent(
    anchor_intent: Any,
    proposed_intent: Any,
    *,
    requires_state_change: bool,
) -> str:
    proposed = _intent_or_default(proposed_intent)
    anchor = _intent_or_default(anchor_intent)
    if proposed in {"document_export", "paper_workflow"}:
        return proposed
    if anchor in {"document_export", "paper_workflow"}:
        return anchor
    if requires_state_change:
        return "write_required"
    return anchor


def _promote_deliverables_for_write(
    contract: dict[str, Any],
    *,
    kind: str,
    path_hint: str,
    description: str,
) -> None:
    current = contract.get("deliverables") if isinstance(contract.get("deliverables"), list) else []
    promoted: list[dict[str, Any]] = []
    source_path_hint = path_hint
    source_description = description
    for item in current:
        if not isinstance(item, dict):
            continue
        item_kind = str(item.get("kind") or "answer").strip().lower()
        if not source_path_hint:
            source_path_hint = str(item.get("path_hint") or item.get("path") or "").strip()
        if not source_description:
            source_description = str(item.get("description") or "").strip()
        if item_kind in {"file", "code", "document"}:
            copy = deepcopy(item)
            copy["kind"] = item_kind
            copy.setdefault("path_policy", "hint")
            if path_hint and not str(copy.get("path_hint") or copy.get("path") or "").strip():
                copy["path_hint"] = path_hint
            promoted.append(copy)
    if not promoted:
        promoted.append({
            "kind": kind,
            "path_hint": source_path_hint,
            "path_policy": "hint",
            "capability_id": "",
            "description": source_description or "Runtime-observed local write target",
        })
    elif path_hint and not any(
        _normalize_path_hint(path_hint) == _normalize_path_hint(item.get("path_hint") or item.get("path"))
        for item in promoted
        if isinstance(item, dict)
    ):
        promoted.append({
            "kind": kind,
            "path_hint": path_hint,
            "path_policy": "hint",
            "capability_id": "",
            "description": description or "Runtime-observed local write target",
        })
    contract["deliverables"] = promoted[:6]


def _normalize_deliverable_kind(value: Any, *, path_hint: str = "") -> str:
    text = str(value or "").strip().lower()
    if text in {"file", "code", "document", "spreadsheet"}:
        return text
    suffix = str(path_hint or "").strip().lower().rsplit(".", 1)
    ext = suffix[-1] if len(suffix) == 2 else ""
    if ext in {"xls", "xlsx", "csv", "tsv"}:
        return "spreadsheet"
    if ext in {"doc", "docx", "pdf", "ppt", "pptx", "md"}:
        return "document"
    if ext in {
        "py", "js", "jsx", "ts", "tsx", "vue", "html", "css", "json", "toml",
        "yaml", "yml", "rs", "go", "java", "cs", "cpp", "c", "h", "hpp",
        "php", "rb", "sh", "ps1", "bat", "sql",
    }:
        return "code"
    return "file"


def _normalize_path_hint(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


def _contract_text(contract: dict[str, Any]) -> str:
    parts = [
        str(contract.get("goal") or ""),
        str(contract.get("first_action") or ""),
    ]
    raw = contract.get("raw_model_contract")
    if isinstance(raw, dict):
        parts.append(str(raw.get("goal") or ""))
    for source in (contract, raw if isinstance(raw, dict) else {}):
        deliverables = source.get("deliverables") if isinstance(source.get("deliverables"), list) else []
        for item in deliverables:
            if not isinstance(item, dict):
                continue
            parts.extend(
                str(item.get(key) or "")
                for key in ("kind", "path_hint", "path", "description")
            )
    return " ".join(parts).lower()


def _has_delete_term(text: str) -> bool:
    terms = (
        "delete",
        "remove",
        "unlink",
        "\u5220\u9664",
        "\u5220\u6389",
        "\u79fb\u9664",
        "\u53bb\u6389",
    )
    return any(term in text for term in terms)


def _contract_expects_document_output(contract: dict[str, Any]) -> bool:
    if str(contract.get("intent") or "") in {"document_export", "paper_workflow"}:
        return True
    if contract.get("expected_document_coverage"):
        return True
    deliverables = contract.get("deliverables") if isinstance(contract.get("deliverables"), list) else []
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() in {"document", "markdown", "docx"}:
            return True
    return False


def _intent_or_default(value: Any, default: Any = "answer_only") -> str:
    intent = str(value or default or "answer_only").strip()
    return intent if intent in VALID_INTENTS else "answer_only"


def _followup_first_action(contract: dict[str, Any]) -> str:
    if contract.get("requires_write"):
        return "write"
    if contract.get("requires_state_change"):
        return "use_tool"
    return "answer"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]
