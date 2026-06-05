"""Task contract normalization and validation.

The model may judge what the task is, but the runtime owns the contract shape,
security overrides, and completion checks.  This module keeps that boundary
pure and testable.
"""

from __future__ import annotations

import json
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
    source: str = "policy",
) -> dict[str, Any]:
    """Build the fallback contract used when the model proposal is missing."""
    intent = _intent_or_default(task_intent)
    requires_write = intent in WRITE_INTENTS
    requires_verification = requires_write
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
        "requires_verification": requires_verification,
        "requires_plan": requires_plan,
        "expected_document_coverage": bool(expected_document_coverage),
        "deliverables": [],
        "first_action": "plan" if requires_plan else ("write" if requires_write else "answer"),
        "blockers": [],
        "confidence": 0.0,
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
        requires_write = _bool_or_default(raw_contract.get("requires_write"), intent in WRITE_INTENTS)
        if requires_write and intent not in {"document_export", "paper_workflow"}:
            intent = "write_required"
        if intent in WRITE_INTENTS:
            requires_write = True
        requires_verification = _bool_or_default(
            raw_contract.get("requires_verification"),
            requires_write,
        )
        if requires_write:
            requires_verification = True

        contract.update({
            "intent": intent,
            "goal": _clean_text(raw_contract.get("goal"), 240),
            "requires_write": requires_write,
            "requires_verification": requires_verification,
            "requires_plan": _bool_or_default(
                raw_contract.get("requires_plan"),
                bool(fallback_contract.get("requires_plan")),
            ),
            "deliverables": _normalize_deliverables(raw_contract.get("deliverables")),
            "first_action": _normalize_first_action(raw_contract.get("first_action"), requires_write),
            "blockers": _normalize_string_list(raw_contract.get("blockers"), limit=6, item_limit=180),
            "confidence": _normalize_confidence(raw_contract.get("confidence")),
        })

    contract["expected_document_coverage"] = (
        bool(contract.get("expected_document_coverage")) or bool(expected_document_coverage)
    )

    overrides = list(contract.get("system_overrides") or [])
    if hard_no_write_lock:
        contract.update({
            "intent": "read_only_analysis",
            "requires_write": False,
            "requires_verification": False,
            "deliverables": [],
            "first_action": "read",
        })
        overrides.append("hard_no_write_lock")

    if contract.get("expected_document_coverage"):
        overrides.append("expected_document_coverage")

    contract["system_overrides"] = list(dict.fromkeys(str(item) for item in overrides if item))
    contract["success_conditions"] = success_conditions_for_contract(contract)
    return contract


def task_contract_prompt(workspace_path: str, fallback_contract: dict[str, Any]) -> str:
    """Prompt used for the model-side task contract judgment."""
    return (
        "请先判断本轮用户请求的任务契约，只输出 JSON，不要调用工具，不要解释。\n"
        f"当前项目目录：{workspace_path}\n"
        "你负责判断任务语义；系统负责权限、工具执行和完成验收。\n"
        "请结合最近对话理解本轮请求。短句可能是在延续上一轮任务或修改上一轮产物；"
        "如果用户要求新增、修改、生成、导出或更新已有产物，requires_write 应为 true。"
        "只有确实不需要任何本地动作的问答才使用 answer_only。\n"
        "请不要因为不确定就默认只聊天。如果用户要求产物、修改、导出、转换、生成文件或执行本地任务，"
        "requires_write 应为 true；如果只是解释、建议或分析，requires_write 应为 false。\n"
        "JSON 字段：\n"
        "{\n"
        '  "goal": "用户真实目标的简短描述",\n'
        '  "intent": "answer_only | read_only_analysis | write_required | document_export | paper_workflow",\n'
        '  "requires_write": true,\n'
        '  "requires_verification": true,\n'
        '  "requires_plan": false,\n'
        '  "deliverables": [{"kind": "file|answer|document|code", "path_hint": "", "description": ""}],\n'
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


def success_conditions_for_contract(contract: dict[str, Any]) -> list[str]:
    conditions = [
        "write_tool_success" if contract.get("requires_write") else "",
        "verification_tool_success" if contract.get("requires_verification") else "",
        "document_output_coverage" if contract.get("expected_document_coverage") else "",
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


def _truncate_raw_contract(value: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= 4000:
        return value
    return {"truncated": True, "preview": text[:4000]}


def _contract_prompt_fallback(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": contract.get("intent"),
        "requires_write": bool(contract.get("requires_write")),
        "requires_verification": bool(contract.get("requires_verification")),
        "requires_plan": bool(contract.get("requires_plan")),
    }


def _legacy_execution_mode(planning_policy: str) -> str:
    return {
        "off": "conservative",
        "auto": "auto",
        "always": "aggressive",
    }.get(str(planning_policy or "").strip().lower(), "auto")
