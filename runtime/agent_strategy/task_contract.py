"""Task contract normalization and validation.

The model may judge what the task is, but the runtime owns the contract shape,
security overrides, and completion checks.  This module keeps that boundary
pure and testable.
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
        "assistant_mode": mode or "terminal",
        "planning_policy": planning_policy,
        "confirmation_policy": confirmation_policy,
        # Deprecated compatibility aliases. Planning and confirmation are now independent.
        "execution_mode": _legacy_execution_mode(planning_policy),
        "plan_mode": planning_policy,
        "access_scope": access_scope,
        "workspace_path": workspace_path,
        "requires_write": requires_write,
        "requires_state_change": requires_state_change,
        "requires_verification": requires_verification,
        "requires_plan": requires_plan,
        "expected_document_coverage": bool(expected_document_coverage),
        "expected_min_output_chars": _safe_int(expected_min_output_chars),
        "deliverables": [],
        "first_action": "plan" if requires_plan else ("write" if requires_write else "answer"),
        "blockers": [],
        "confidence": 0.0,
        "scope_relation": "new",
        "scope_relation_source": "default",
        "revision_request": "",
        "system_overrides": [],
    }
    contract["success_conditions"] = success_conditions_for_contract(contract)
    return contract


def merge_model_task_contract(
    raw_contract: dict[str, Any] | None,
    fallback_contract: dict[str, Any],
    *,
    hard_no_write_lock: bool = False,
    expected_document_coverage: bool = False,
    expected_min_output_chars: int = 0,
) -> dict[str, Any]:
    """Normalize a model contract and apply runtime-owned hard constraints."""
    if not isinstance(raw_contract, dict):
        contract = dict(fallback_contract)
        contract["source"] = fallback_contract.get("source") or "policy"
        contract["raw_model_contract"] = None
    else:
        contract = dict(fallback_contract)
        contract["source"] = "model"
        contract["raw_model_contract"] = _truncate_raw_contract(raw_contract)
        intent = _intent_or_default(raw_contract.get("intent"), fallback_contract.get("intent"))
        requires_write = _bool_or_default(
            raw_contract.get("requires_write"),
            bool(fallback_contract.get("requires_write")),
        )
        requires_state_change = _bool_or_default(
            raw_contract.get("requires_state_change"),
            requires_write or intent in WRITE_INTENTS,
        )
        if requires_write:
            requires_state_change = True
        if requires_state_change and intent not in {"document_export", "paper_workflow"}:
            intent = "write_required"
        if intent == "document_export":
            requires_write = True
            requires_state_change = True
        requires_verification = _bool_or_default(
            raw_contract.get("requires_verification"),
            requires_state_change,
        )
        if requires_state_change:
            requires_verification = True

        contract.update({
            "intent": intent,
            "goal": _clean_text(raw_contract.get("goal"), 240),
            "requires_write": requires_write,
            "requires_state_change": requires_state_change,
            "requires_verification": requires_verification,
            "requires_plan": _bool_or_default(
                raw_contract.get("requires_plan"),
                bool(fallback_contract.get("requires_plan")),
            ),
            "expected_min_output_chars": _safe_int(raw_contract.get("expected_min_output_chars")),
            "deliverables": _normalize_deliverables(raw_contract.get("deliverables")),
            "first_action": _normalize_first_action(
                raw_contract.get("first_action"),
                requires_write or requires_state_change,
            ),
            "blockers": _normalize_string_list(raw_contract.get("blockers"), limit=6, item_limit=180),
            "confidence": _normalize_confidence(raw_contract.get("confidence")),
            "scope_relation": _normalize_scope_relation(raw_contract.get("scope_relation")),
            "scope_relation_source": (
                "model"
                if str(raw_contract.get("scope_relation") or "").strip().lower() in VALID_SCOPE_RELATIONS
                else "default"
            ),
        })

    contract["scope_relation"] = _normalize_scope_relation(contract.get("scope_relation"))
    contract.setdefault("scope_relation_source", "default")
    contract.setdefault("revision_request", "")
    contract["expected_document_coverage"] = (
        bool(contract.get("expected_document_coverage")) or bool(expected_document_coverage)
    )
    contract["expected_min_output_chars"] = max(
        _safe_int(contract.get("expected_min_output_chars")),
        _safe_int(expected_min_output_chars),
    )

    overrides = list(contract.get("system_overrides") or [])
    if hard_no_write_lock:
        contract.update({
            "intent": "read_only_analysis",
            "requires_write": False,
            "requires_state_change": False,
            "requires_verification": False,
            "deliverables": [],
            "first_action": "read",
        })
        overrides.append("hard_no_write_lock")

    if contract.get("expected_document_coverage"):
        overrides.append("expected_document_coverage")
    if _safe_int(contract.get("expected_min_output_chars")) > 0:
        overrides.append("expected_min_output_chars")

    contract["system_overrides"] = list(dict.fromkeys(str(item) for item in overrides if item))
    contract["success_conditions"] = success_conditions_for_contract(contract)
    return contract


def apply_task_continuity(
    contract: dict[str, Any],
    *,
    previous_contract: dict[str, Any] | None,
    current_user_content: str,
) -> dict[str, Any]:
    """Apply a model-declared continuation relationship to a task contract.

    The model decides whether the new request continues, revises, replaces, or
    starts a task. The runtime preserves the previous semantic target for
    continue/revise relationships so an implementation fallback cannot silently
    become the product goal.
    """
    result = dict(contract)
    if "hard_no_write_lock" in set(result.get("system_overrides") or []):
        result["scope_relation"] = _normalize_scope_relation(result.get("scope_relation"))
        result.setdefault("revision_request", "")
        return result
    if not isinstance(previous_contract, dict):
        result["scope_relation"] = _normalize_scope_relation(result.get("scope_relation"))
        result.setdefault("revision_request", "")
        return result

    relation = _normalize_scope_relation(result.get("scope_relation"))
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
    for key in (
        "intent",
        "goal",
        "requires_write",
        "requires_state_change",
        "requires_verification",
        "deliverables",
    ):
        if key in anchor:
            result[key] = deepcopy(anchor[key])
    result["continuity_anchor"] = anchor
    result["revision_request"] = _clean_text(current_user_content, 500)
    result["source"] = "model_with_task_anchor"
    if result.get("requires_write"):
        result["requires_state_change"] = True
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
            "deliverables",
        )
        if key in source
    }


def task_contract_prompt(
    workspace_path: str,
    fallback_contract: dict[str, Any],
    *,
    capability_context: str = "",
    previous_contract: dict[str, Any] | None = None,
) -> str:
    """Prompt used for the model-side task contract judgment."""
    capability_block = ""
    if str(capability_context or "").strip():
        capability_block = (
            "\nRuntime capability context for this contract judgment:\n"
            f"{str(capability_context).strip()}\n"
            "Capability rule: if the user asks to read, inspect, summarize, or analyze "
            "a public website/URL and web.network_fetch or web.* tools are available, "
            "classify it as read_only_analysis and choose first_action=read/search/use_tool. "
            "Do not classify such requests as answer_only merely because the content is remote.\n"
        )
    continuity_block = ""
    if isinstance(previous_contract, dict):
        continuity_block = (
            "\nPrevious task semantic anchor:\n"
            f"{json.dumps(task_continuity_anchor(previous_contract), ensure_ascii=False)}\n"
            "Decide scope_relation for the current request: continue/revise keeps "
            "the previous target and changes how it should be completed; replace/new "
            "changes the target. Do not turn an external-state goal into a script or "
            "other intermediate artifact merely because execution previously fell back.\n"
        )
    return capability_block + continuity_block + (
        "请先判断本轮用户请求的任务契约，只输出 JSON，不要调用工具，不要解释。\n"
        f"当前项目目录：{workspace_path}\n"
        "你负责判断任务语义；系统负责权限、工具执行和完成验收。\n"
        "请结合最近对话理解本轮请求。短句可能是在延续上一轮任务或修改上一轮产物；"
        "requires_write 只表示必须创建或修改本地文件；requires_state_change 表示必须改变文件、"
        "外部应用、数据库、浏览器会话或其他可观察状态。"
        "如果用户只要求在 Blender、CAD 或其他外部应用中修改当前状态，而没有要求保存文件，"
        "requires_state_change 应为 true，requires_write 应为 false。"
        "只有确实不需要任何本地动作的问答才使用 answer_only。\n"
        "请不要因为不确定就默认只聊天。如果用户要求产物、修改、导出、转换、生成文件或执行本地任务，"
        "应正确区分文件写入与外部状态修改；如果只是解释、建议或分析，两者都应为 false。\n"
        "JSON 字段：\n"
        "{\n"
        '  "goal": "用户真实目标的简短描述",\n'
        '  "intent": "answer_only | read_only_analysis | write_required | document_export | paper_workflow",\n'
        '  "requires_write": true,\n'
        '  "requires_state_change": true,\n'
        '  "requires_verification": true,\n'
        '  "requires_plan": false,\n'
        '  "deliverables": [{"kind": "file|answer|document|code|external_state", "path_hint": "", "path_policy": "hint|exact", "description": ""}],\n'
        '  "scope_relation": "new|continue|revise|replace",\n'
        '  "expected_min_output_chars": 0,\n'
        '  "first_action": "answer|read|search|plan|write|verify|ask_user|use_tool",\n'
        '  "blockers": [],\n'
        '  "confidence": 0.0\n'
        "}\n"
        f"系统回退契约：{json.dumps(_contract_prompt_fallback(fallback_contract), ensure_ascii=False)}"
    )


def task_contract_context_messages(
    messages: list[dict[str, Any]],
    current_user_content: str,
    *,
    max_messages: int = 6,
    max_chars: int = 1200,
) -> list[dict[str, str]]:
    """Return a compact recent conversation for model-side contract judgment."""
    current = str(current_user_content or "").strip()
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
    hard_no_write_lock: bool,
    *,
    has_recent_task_context: bool = False,
) -> bool:
    """Return whether semantic task judgment should be delegated to the model.

    This gate should stay intentionally small.  The runtime may skip the model
    only for empty input, hard safety locks, or obvious social chat.  It should
    not use message length or scenario keywords to decide whether a request is
    actionable; that semantic judgment belongs to the model-side contract.
    """
    if hard_no_write_lock:
        return False
    text = str(content or "").strip()
    if not text:
        return False
    intent = _intent_or_default(fallback_intent)
    if intent != "answer_only":
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
    inherited = deepcopy(previous_contract) if isinstance(previous_contract, dict) else {}
    contract = dict(fallback_contract)
    for key in (
        "intent",
        "goal",
        "requires_write",
        "requires_state_change",
        "requires_verification",
        "expected_document_coverage",
        "deliverables",
        "blockers",
        "confidence",
    ):
        if key in inherited:
            contract[key] = deepcopy(inherited[key])
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


def success_conditions_for_contract(contract: dict[str, Any]) -> list[str]:
    conditions = [
        "target_deliverable_success"
        if contract.get("requires_write") or contract.get("requires_state_change")
        else "",
        "target_deliverable_verification" if contract.get("requires_verification") else "",
        "document_output_coverage" if contract.get("expected_document_coverage") else "",
        "document_min_output_chars" if _safe_int(contract.get("expected_min_output_chars")) > 0 else "",
        "final_answer_with_evidence",
    ]
    return [condition for condition in conditions if condition]


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


def _contract_prompt_fallback(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": contract.get("intent"),
        "requires_write": bool(contract.get("requires_write")),
        "requires_state_change": bool(contract.get("requires_state_change")),
        "requires_verification": bool(contract.get("requires_verification")),
        "requires_plan": bool(contract.get("requires_plan")),
    }


def _legacy_execution_mode(planning_policy: str) -> str:
    return {
        "off": "conservative",
        "auto": "auto",
        "always": "aggressive",
    }.get(str(planning_policy or "").strip().lower(), "auto")
