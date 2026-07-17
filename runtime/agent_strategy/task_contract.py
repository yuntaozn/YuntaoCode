"""Task contract normalization and validation.

The model may judge what the task is, but the runtime owns the contract shape,
security overrides, and completion checks.  This module keeps that boundary
pure and testable.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.agent_strategy import classifiers as _clf
from runtime.agent_strategy import contract_evolution as _contract_evolution
from runtime.agent_strategy import project_context as _project_context
from runtime.agent_strategy.document_completion import (
    contract_expects_text_output as _document_contract_expects_text_output,
)


VALID_INTENTS: frozenset[str] = frozenset({
    "answer_only",
    "read_only_analysis",
    "write_required",
    "document_export",
    "paper_workflow",
})

WRITE_INTENTS: frozenset[str] = frozenset({
    "write_required",
    "document_export",
})

VALID_FIRST_ACTIONS: frozenset[str] = frozenset({
    "answer",
    "read",
    "search",
    "plan",
    "write",
    "verify",
    "ask_user",
    "use_tool",
})

VALID_SCOPE_RELATIONS: frozenset[str] = frozenset({
    "new",
    "continue",
    "revise",
    "replace",
})

VALID_PATH_POLICIES: frozenset[str] = frozenset({
    "hint",
    "exact",
})

VALID_VERIFICATION_MODALITIES: frozenset[str] = frozenset({
    "structural",
    "visual",
    "behavioral",
    "content",
})


def extract_task_contract_json(raw: str) -> dict[str, Any] | None:
    """Extract a JSON object from a model response."""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def default_task_contract(
    *,
    task_intent: str,
    mode: str | None,
    planning_policy: str,
    confirmation_policy: str,
    workspace_path: str,
    access_scope: str,
    expected_document_coverage: bool = False,
    expected_min_output_chars: int = 0,
    source: str = "policy",
) -> dict[str, Any]:
    """Build the fallback contract used when the model proposal is missing."""
    intent = _intent_or_default(task_intent)
    requires_write = intent in WRITE_INTENTS
    requires_state_change = requires_write
    requires_verification = requires_state_change
    requires_plan = planning_policy == "always"
    contract = {
        "schema_version": "task_contract.v1",
        "source": source,
        "intent": intent,
        "goal": "",
        "routing_strategy": "model_first_task_contract",
        "planning_policy": planning_policy,
        "confirmation_policy": confirmation_policy,
        "access_scope": access_scope,
        "workspace_path": workspace_path,
        "requires_write": requires_write,
        "requires_state_change": requires_state_change,
        "requires_verification": requires_verification,
        "required_verification_modalities": [],
        "requires_plan": requires_plan,
        "expected_document_coverage": bool(expected_document_coverage),
        "expected_min_output_chars": _safe_int(expected_min_output_chars),
        "capability_ids": [],
        "deliverables": [],
        "first_action": "plan" if requires_plan else ("write" if requires_write else "answer"),
        "blockers": [],
        "confidence": 0.0,
        "scope_relation": "new",
        "scope_relation_source": "default",
        "referenced_task_candidate_id": "",
        "focus_relation": "unresolved",
        "focus_relation_source": "default",
        "focus": {},
        "referenced_focus_candidate_id": "",
        "revision_request": "",
        "system_overrides": [],
        "execution_advisories": [],
    }
    contract["success_conditions"] = success_conditions_for_contract(contract)
    return contract


def merge_model_task_contract(
    raw_contract: dict[str, Any] | None,
    fallback_contract: dict[str, Any],
) -> dict[str, Any]:
    """Normalize a model contract without replacing its semantic judgment.

    The runtime owns field shape and safe defaults.  It does not turn one
    intent, deliverable, target, or first action into another after the model
    has selected them.
    """
    if not isinstance(raw_contract, dict):
        contract = dict(fallback_contract)
        contract["source"] = fallback_contract.get("source") or "policy"
        contract["raw_model_contract"] = None
    else:
        contract = dict(fallback_contract)
        contract["source"] = "model"
        contract["raw_model_contract"] = _truncate_raw_contract(raw_contract)
        contract["model_explicit_fields"] = sorted(str(key) for key in raw_contract)
        intent = _intent_or_default(raw_contract.get("intent"), fallback_contract.get("intent"))
        requires_write = _bool_or_default(
            raw_contract.get("requires_write"),
            bool(fallback_contract.get("requires_write")) or intent in WRITE_INTENTS,
        )
        requires_state_change = _bool_or_default(
            raw_contract.get("requires_state_change"),
            requires_write,
        )
        # A local write is observably a state change.  This is field ontology,
        # not a task-routing decision; intent and first_action remain untouched.
        if requires_write:
            requires_state_change = True
        requires_verification = _bool_or_default(
            raw_contract.get("requires_verification"),
            requires_state_change,
        )

        contract.update({
            "intent": intent,
            "goal": _clean_text(raw_contract.get("goal"), 240),
            "requires_write": requires_write,
            "requires_state_change": requires_state_change,
            "requires_verification": requires_verification,
            "required_verification_modalities": _normalize_verification_modalities(
                raw_contract.get("required_verification_modalities")
                or raw_contract.get("verification_modalities")
                or raw_contract.get("verification_requirements")
            ),
            "requires_plan": _bool_or_default(
                raw_contract.get("requires_plan"),
                bool(fallback_contract.get("requires_plan")),
            ),
            "expected_document_coverage": _bool_or_default(
                raw_contract.get("expected_document_coverage"),
                False,
            ),
            "expected_min_output_chars": _safe_int(raw_contract.get("expected_min_output_chars")),
            "capability_ids": _normalize_string_list(
                raw_contract.get("capability_ids") or raw_contract.get("target_capability_ids"),
                limit=6,
                item_limit=120,
            ),
            "deliverables": _normalize_deliverables(raw_contract.get("deliverables")),
            "first_action": _normalize_first_action(
                raw_contract.get("first_action"),
                requires_write or requires_state_change,
            ),
            "blockers": _normalize_string_list(raw_contract.get("blockers"), limit=6, item_limit=180),
            "execution_advisories": _normalize_advisories(
                raw_contract.get("execution_advisories")
                or raw_contract.get("advisories")
                or raw_contract.get("strategy_advisories")
            ),
            "confidence": _normalize_confidence(raw_contract.get("confidence")),
            "scope_relation": _normalize_scope_relation(raw_contract.get("scope_relation")),
            "scope_relation_source": (
                "model"
                if str(raw_contract.get("scope_relation") or "").strip().lower() in VALID_SCOPE_RELATIONS
                else "default"
            ),
            "referenced_task_candidate_id": _clean_text(
                raw_contract.get("referenced_task_candidate_id")
                or raw_contract.get("task_candidate_id")
                or raw_contract.get("previous_task_candidate_id"),
                160,
            ),
            "focus_relation": _project_context.normalize_focus_relation(
                raw_contract.get("focus_relation")
            ),
            "focus_relation_source": (
                "model"
                if str(raw_contract.get("focus_relation") or "").strip().lower()
                in _project_context.VALID_FOCUS_RELATIONS
                else "default"
            ),
            "focus": _project_context.normalize_focus_reference(raw_contract.get("focus")),
            "referenced_focus_candidate_id": _clean_text(
                raw_contract.get("referenced_focus_candidate_id")
                or raw_contract.get("focus_candidate_id"),
                160,
            ),
        })

    contract["scope_relation"] = _normalize_scope_relation(contract.get("scope_relation"))
    contract.setdefault("scope_relation_source", "default")
    contract["referenced_task_candidate_id"] = _clean_text(
        contract.get("referenced_task_candidate_id"),
        160,
    )
    contract["focus_relation"] = _project_context.normalize_focus_relation(
        contract.get("focus_relation")
    )
    contract.setdefault("focus_relation_source", "default")
    contract["focus"] = _project_context.normalize_focus_reference(contract.get("focus"))
    contract["referenced_focus_candidate_id"] = _clean_text(
        contract.get("referenced_focus_candidate_id"),
        160,
    )
    contract.setdefault("revision_request", "")
    contract.setdefault("model_explicit_fields", [])
    contract["execution_advisories"] = _normalize_advisories(contract.get("execution_advisories"))
    contract["expected_document_coverage"] = bool(
        contract.get("expected_document_coverage")
    )
    contract["expected_min_output_chars"] = _safe_int(
        contract.get("expected_min_output_chars")
    )

    overrides = list(contract.get("system_overrides") or [])

    if contract.get("expected_document_coverage"):
        overrides.append("expected_document_coverage")
    if _safe_int(contract.get("expected_min_output_chars")) > 0:
        overrides.append("expected_min_output_chars")

    if contract.get("requires_verification"):
        contract["required_verification_modalities"] = _normalize_verification_modalities(
            contract.get("required_verification_modalities")
        )
    else:
        contract["required_verification_modalities"] = []

    contract["system_overrides"] = list(dict.fromkeys(str(item) for item in overrides if item))
    contract["success_conditions"] = success_conditions_for_contract(contract)
    return contract


def apply_task_continuity(
    contract: dict[str, Any],
    *,
    previous_contract: dict[str, Any] | None,
    current_user_content: str,
) -> dict[str, Any]:
    return _contract_evolution.apply_task_continuity(
        contract,
        previous_contract=previous_contract,
        current_user_content=current_user_content,
    )


def should_apply_task_continuity(
    contract: dict[str, Any],
    *,
    current_user_content: str,
) -> bool:
    return _contract_evolution.should_apply_task_continuity(
        contract,
        current_user_content=current_user_content,
    )


def task_continuity_anchor(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the stable semantic target carried across continuation turns."""
    return _contract_evolution.task_continuity_anchor(contract)


def task_contract_prompt(
    workspace_path: str,
    fallback_contract: dict[str, Any],
    *,
    capability_context: str = "",
    workspace_context: str = "",
    previous_contract: dict[str, Any] | None = None,
) -> str:
    """Prompt used for the model-side task contract judgment.

    Keep this prompt schema-oriented. Scenario playbooks belong to model
    judgment or optional capability packs, not the runtime contract layer.
    """
    capability_block = ""
    if str(capability_context or "").strip():
        capability_block = (
            "\nRuntime capability context for this contract judgment:\n"
            f"{str(capability_context).strip()}\n"
            "These are current capability facts, not a required execution route.\n"
        )
    workspace_block = ""
    if str(workspace_context or "").strip():
        workspace_block = (
            "\nRuntime workspace context for this contract judgment:\n"
            f"{str(workspace_context).strip()}\n"
        )
    continuity_block = ""
    if isinstance(previous_contract, dict):
        continuity_block = (
            "\nPrevious task semantic anchor:\n"
            f"{json.dumps(task_continuity_anchor(previous_contract), ensure_ascii=False)}\n"
            "This is historical evidence only. The current request has priority; decide "
            "the relationship and target yourself.\n"
        )
    return capability_block + workspace_block + continuity_block + (
        "请先判断本轮用户请求的任务契约，只输出 JSON，不要调用工具，不要解释。\n"
        f"当前项目目录：{workspace_path}\n"
        "当前用户请求是任务语义的第一依据；工作区快照、历史任务、记忆和能力清单都只是证据。\n"
        "你负责选择 goal、intent、目标产物、能力、关系、首动作、计划和验证需求。"
        "系统不会根据关键词替你改写这些字段。请让字段彼此一致："
        "requires_write 仅表示需要创建、修改或删除本地文件；requires_state_change 表示需要改变任何"
        "可观察状态；requires_verification 表示目标完成后仍需要证据。\n"
        "scope_relation 描述当前目标与历史任务的关系；focus_relation 独立描述当前工作对象的来源。"
        "只有确实沿用历史目标或工作对象时才引用候选 id；证据不足时使用 unresolved。\n"
        "required_verification_modalities 可使用 structural、visual、behavioral、content；"
        "由目标所需证据决定，不绑定具体工具。execution_advisories 只能记录非约束性提醒。\n"
        "JSON 字段：\n"
        "{\n"
        '  "goal": "用户真实目标的简短描述",\n'
        '  "intent": "answer_only | read_only_analysis | write_required | document_export | paper_workflow",\n'
        '  "requires_write": true,\n'
        '  "requires_state_change": true,\n'
        '  "requires_verification": true,\n'
        '  "required_verification_modalities": [],\n'
        '  "requires_plan": false,\n'
        '  "capability_ids": ["optional capability id from the runtime facts"],\n'
        '  "deliverables": [{"kind": "file|answer|document|code|external_state", "path_hint": "", "path_policy": "hint|exact", "capability_id": "", "description": ""}],\n'
        '  "scope_relation": "new|continue|revise|replace",\n'
        '  "referenced_task_candidate_id": "",\n'
        '  "focus_relation": "explicit|inherit|switch|unresolved",\n'
        '  "focus": {"kind": "workspace|project|subproject|directory|file|artifact|external_state|other", "name": "", "path_hint": "", "description": ""},\n'
        '  "referenced_focus_candidate_id": "",\n'
        '  "expected_document_coverage": false,\n'
        '  "expected_min_output_chars": 0,\n'
        '  "execution_advisories": [{"code": "optional-short-code", "message": "non-binding execution note", "suggested_first_action": "read|write|verify|use_tool"}],\n'
        '  "first_action": "answer|read|search|plan|write|verify|ask_user|use_tool",\n'
        '  "blockers": [],\n'
        '  "confidence": 0.0\n'
        "}\n"
    )


def task_contract_context_messages(
    messages: list[dict[str, Any]],
    current_user_content: str,
    *,
    max_messages: int = 4,
    max_chars: int = 600,
    include_history: bool = False,
) -> list[dict[str, str]]:
    """Return bounded user input for model-side contract judgment.

    The model should normally judge the current request from the current user
    message plus structured Context Pack facts.  Raw recent chat history is kept
    as an explicit compatibility option for tests and old call sites, not the
    default contract-decision path.
    """
    current = str(current_user_content or "").strip()
    if not include_history:
        return [{"role": "user", "content": current[:max_chars]}] if current else []

    history: list[dict[str, str]] = []
    skipped_current = False
    history_limit = max(0, max_messages - (1 if current else 0))

    for item in reversed(messages):
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = _message_text(item.get("content"))
        if not content:
            continue
        if role == "user" and current and content == current and not skipped_current:
            skipped_current = True
            continue
        history.append({"role": role, "content": content[:max_chars]})
        if len(history) >= history_limit:
            break

    history.reverse()
    if current:
        history.append({"role": "user", "content": current[:max_chars]})
    return history


def should_use_model_task_contract(
    content: str,
    fallback_intent: str,
    *,
    has_recent_task_context: bool = False,
) -> bool:
    """Return whether semantic task judgment should be delegated to the model.

    This gate should stay intentionally small.  The runtime may skip the model
    only for empty input, hard safety locks, or obvious social chat.  It should
    not use message length or scenario keywords to decide whether a request is
    actionable; that semantic judgment belongs to the model-side contract.
    """
    text = str(content or "").strip()
    if not text:
        return False
    intent = _intent_or_default(fallback_intent)
    if intent != "answer_only":
        return True
    if _clf.looks_like_diagnostic_feedback(text):
        return True
    if has_recent_task_context:
        return True
    return not _looks_like_obvious_chat(text)


def looks_like_execute_contract_followup(content: str) -> bool:
    """Return whether the user is asking to run the previously agreed task."""
    text = str(content or "").strip().lower()
    if not text or len(text) > 60:
        return False
    normalized = text.strip(" \t\r\n.,!?;:，。！？；：~～")
    exact_terms = {
        "执行",
        "立即执行",
        "开始执行",
        "确认执行",
        "按计划执行",
        "执行计划",
        "执行以上计划",
        "执行上面的计划",
        "按上面的计划执行",
        "就按这个执行",
        "就按计划执行",
        "run",
        "execute",
        "run it",
        "execute it",
        "go ahead",
    }
    if normalized in exact_terms:
        return True
    phrase_terms = (
        "立即执行",
        "按计划执行",
        "执行以上计划",
        "执行上面的计划",
        "按上面的计划",
        "go ahead",
    )
    return any(term in normalized for term in phrase_terms)


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


def inherit_task_contract_for_followup(
    previous_contract: dict[str, Any],
    fallback_contract: dict[str, Any],
) -> dict[str, Any]:
    """Carry a previous task contract into an explicit execute-follow-up turn."""
    return _contract_evolution.inherit_task_contract_for_followup(previous_contract, fallback_contract)


def success_conditions_for_contract(contract: dict[str, Any]) -> list[str]:
    return _contract_evolution.success_conditions_for_contract(contract)


def contract_expects_text_output(contract: dict[str, Any]) -> bool:
    return _contract_expects_text_output(contract)


def _intent_or_default(value: Any, default: Any = "answer_only") -> str:
    intent = str(value or default or "answer_only").strip()
    return intent if intent in VALID_INTENTS else "answer_only"


def _bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return bool(default)


def _normalize_first_action(value: Any, requires_write: bool) -> str:
    action = str(value or "").strip()
    if action in VALID_FIRST_ACTIONS:
        return action
    return "write" if requires_write else "answer"


def _followup_first_action(contract: dict[str, Any]) -> str:
    if contract.get("requires_write"):
        return "write"
    if contract.get("requires_state_change"):
        return "use_tool"
    return "answer"


def _normalize_deliverables(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        result.append({
            "kind": _clean_text(item.get("kind"), 40) or "file",
            "path_hint": _clean_text(item.get("path_hint") or item.get("path"), 180),
            "path_policy": _normalize_path_policy(item.get("path_policy")),
            "capability_id": _clean_text(item.get("capability_id"), 120),
            "description": _clean_text(item.get("description"), 240),
        })
    return result


def _normalize_string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:limit]:
        text = _clean_text(item, item_limit)
        if text:
            result.append(text)
    return result


def _normalize_verification_modalities(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:6]:
        text = str(item or "").strip().lower()
        if text in VALID_VERIFICATION_MODALITIES and text not in result:
            result.append(text)
    return result


def _normalize_advisories(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value[:6]:
        if isinstance(item, str):
            advisory = {
                "code": "",
                "message": _clean_text(item, 240),
                "suggested_first_action": "",
            }
        elif isinstance(item, dict):
            advisory = {
                "code": _clean_text(item.get("code"), 80),
                "message": _clean_text(item.get("message") or item.get("description"), 240),
                "suggested_first_action": _normalize_first_action(
                    item.get("suggested_first_action"),
                    False,
                ),
            }
        else:
            continue
        if not advisory["message"] and advisory["code"]:
            advisory["message"] = advisory["code"]
        if not advisory["message"]:
            continue
        if advisory["suggested_first_action"] == "answer" and not (
            isinstance(item, dict) and item.get("suggested_first_action")
        ):
            advisory["suggested_first_action"] = ""
        key = (advisory["code"], advisory["message"])
        if key in seen:
            continue
        seen.add(key)
        result.append(advisory)
    return result


def _normalize_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(number, 1.0))


def _normalize_scope_relation(value: Any) -> str:
    relation = str(value or "").strip().lower()
    return relation if relation in VALID_SCOPE_RELATIONS else "new"


def _normalize_path_policy(value: Any) -> str:
    policy = str(value or "").strip().lower()
    return policy if policy in VALID_PATH_POLICIES else "hint"


def _contract_expects_text_output(contract: dict[str, Any]) -> bool:
    return _document_contract_expects_text_output(contract)


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:limit]


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
    return "\n".join(parts)


def _looks_like_obvious_chat(value: str) -> bool:
    text = str(value or "").strip().lower()
    text = text.strip(" \t\r\n.,!?;:，。！？；：~～")
    if not text:
        return True
    obvious = {
        "hi",
        "hello",
        "hey",
        "ok",
        "okay",
        "thanks",
        "thank you",
        "你好",
        "您好",
        "早上好",
        "晚上好",
        "谢谢",
        "多谢",
        "辛苦了",
        "好的",
        "好",
        "嗯",
        "收到",
    }
    return text in obvious


def _truncate_raw_contract(value: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= 4000:
        return value
    return {"truncated": True, "preview": text[:4000]}
