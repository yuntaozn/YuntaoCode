"""任务契约规范化与校验。

模型可以判断任务是什么，Runtime 管理契约结构、权限与安全事实以及可观察闭环事实。
本模块让该边界保持纯净且可测试。"""

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
    """从模型响应中提取 JSON 对象。"""
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
    """构建模型提案缺失时使用的回退契约。"""
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
        "route_proposals": [],
        "deliverables": [],
        "first_action": "plan" if requires_plan else ("write" if requires_write else "answer"),
        "confidence": 0.0,
        "scope_relation": "new",
        "scope_relation_source": "default",
        "needs_task_lineage": False,
        "task_lineage_request_reason": "",
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
    """规范化模型契约，但不替换其语义判断。

    Runtime 管理字段结构和安全默认值；模型选定意图、交付物、目标或首个动作后，
    Runtime 不把它们改成其他内容。"""
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
        # 本地写入可观察地改变状态。这属于字段本体定义，
        # 不是任务路由决策；intent 与 first_action 保持不变。
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
            "route_proposals": _normalize_route_proposals(
                raw_contract.get("route_proposals")
                or raw_contract.get("task_route_proposals")
                or raw_contract.get("route_proposal")
                or raw_contract.get("task_route_proposal")
            ),
            "deliverables": _normalize_deliverables(raw_contract.get("deliverables")),
            "first_action": _normalize_first_action(
                raw_contract.get("first_action"),
                requires_write or requires_state_change,
            ),
            "execution_advisories": _normalize_contract_advisories(raw_contract),
            "confidence": _normalize_confidence(raw_contract.get("confidence")),
            "scope_relation": _normalize_scope_relation(raw_contract.get("scope_relation")),
            "scope_relation_source": (
                "model"
                if str(raw_contract.get("scope_relation") or "").strip().lower() in VALID_SCOPE_RELATIONS
                else "default"
            ),
            "needs_task_lineage": _bool_or_default(
                raw_contract.get("needs_task_lineage"),
                False,
            ),
            "task_lineage_request_reason": _clean_text(
                raw_contract.get("task_lineage_request_reason")
                or raw_contract.get("task_lineage_reason"),
                240,
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
    contract["needs_task_lineage"] = bool(contract.get("needs_task_lineage"))
    contract["task_lineage_request_reason"] = _clean_text(
        contract.get("task_lineage_request_reason"),
        240,
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
    contract["route_proposals"] = _normalize_route_proposals(contract.get("route_proposals"))
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


def contract_requests_task_lineage(contract: dict[str, Any] | None) -> bool:
    """返回模型契约是否要求查看任务血缘候选。"""

    if not isinstance(contract, dict):
        return False
    if bool(contract.get("needs_task_lineage")):
        return True
    if str(contract.get("referenced_task_candidate_id") or "").strip():
        return True
    relation = str(contract.get("scope_relation") or "").strip().lower()
    return relation in {"continue", "revise", "replace"}


def task_continuity_anchor(contract: dict[str, Any]) -> dict[str, Any]:
    """返回跨续接轮次传递的稳定语义目标。"""
    return _contract_evolution.task_continuity_anchor(contract)


def task_contract_prompt(
    workspace_path: str,
    fallback_contract: dict[str, Any],
    *,
    capability_context: str = "",
    workspace_context: str = "",
    previous_contract: dict[str, Any] | None = None,
) -> str:
    """模型侧任务契约判断使用的提示。

    此提示只描述 Schema。场景操作手册属于模型判断或可选 Capability Pack，
    不属于 Runtime 契约层。"""
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
        "在确定 goal、scope_relation 和 focus_relation 前，先判断当前请求能否脱离历史内容独立成立。"
        "如果它依赖先前安装、修改、执行、失败、产物、对象或省略的指代，而上下文只提示历史任务候选可用，"
        "不要把不完整目标弱化成“检查或提供指导”，也不要猜测缺失语义；请先设置 "
        "needs_task_lineage=true 并说明 task_lineage_request_reason。获得候选详情后再完成任务契约。"
        "只有当前请求本身足以确定目标和工作对象时才保持 false。\n"
        "required_verification_modalities 可使用 structural、visual、behavioral、content；"
        "由目标所需证据决定，不绑定具体工具。execution_advisories 只能记录非约束性提醒。\n"
        "展开的 task_lineage 使用字段级来源：user_request 是历史用户原话；declared_goal、"
        "model_response_excerpt 和 declared_focus 是旧模型解释；observed_status 与 observed_actual_paths "
        "才是 Runtime 观察事实。请自行判断是否继承，不要把旧模型解释当成当前用户指令。\n"
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
        '  "route_proposals": [{"capability_id": "", "tool_id": "", "expected_artifacts": [], "requires_write": false, "requires_verification": false, "confidence": 0.0, "rationale": "why this route fits"}],\n'
        '  "deliverables": [{"kind": "file|answer|document|code|external_state", "path_hint": "", "path_policy": "hint|exact", "capability_id": "", "description": ""}],\n'
        '  "scope_relation": "new|continue|revise|replace",\n'
        '  "needs_task_lineage": false,\n'
        '  "task_lineage_request_reason": "",\n'
        '  "referenced_task_candidate_id": "",\n'
        '  "focus_relation": "explicit|inherit|switch|unresolved",\n'
        '  "focus": {"kind": "workspace|project|subproject|directory|file|artifact|external_state|other", "name": "", "path_hint": "", "description": ""},\n'
        '  "referenced_focus_candidate_id": "",\n'
        '  "expected_document_coverage": false,\n'
        '  "expected_min_output_chars": 0,\n'
        '  "execution_advisories": [{"code": "optional-short-code", "message": "non-binding execution note", "suggested_first_action": "read|write|verify|use_tool"}],\n'
        '  "first_action": "answer|read|search|plan|write|verify|ask_user|use_tool",\n'
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
    """返回供模型侧契约判断使用的有界用户输入。

    模型通常应根据当前用户消息与结构化 Context Pack 事实判断当前请求。原始近期聊天
    历史只作为测试和旧调用点的明确兼容选项，不是默认契约决策路径。"""
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
    """返回是否应把语义任务判断交给模型。

    此门禁应有意保持很小。Runtime 只能在输入为空、硬安全锁或明显社交闲聊时跳过模型，
    不应使用消息长度或场景关键词判断请求是否可执行；该语义判断属于模型侧契约。"""
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


def _normalize_route_proposals(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items[:6]:
        if not isinstance(item, dict):
            continue
        capability_id = _clean_text(item.get("capability_id"), 120)
        tool_id = _clean_text(item.get("tool_id"), 120)
        if not capability_id and not tool_id:
            continue
        key = (capability_id, tool_id)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "capability_id": capability_id,
            "tool_id": tool_id,
            "expected_artifacts": _normalize_string_list(
                item.get("expected_artifacts"),
                limit=8,
                item_limit=80,
            ),
            "requires_write": _bool_or_default(item.get("requires_write"), False),
            "requires_verification": _bool_or_default(
                item.get("requires_verification"),
                False,
            ),
            "confidence": _normalize_confidence(item.get("confidence")),
            "rationale": _clean_text(item.get("rationale"), 240),
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


def _normalize_contract_advisories(raw_contract: dict[str, Any]) -> list[dict[str, str]]:
    raw_advisories = raw_contract.get("execution_advisories")
    if raw_advisories is None:
        raw_advisories = raw_contract.get("advisories")
    if raw_advisories is None:
        raw_advisories = raw_contract.get("strategy_advisories")

    advisories = _normalize_advisories(raw_advisories)
    legacy_blockers = _normalize_string_list(raw_contract.get("blockers"), limit=6, item_limit=180)
    for blocker in legacy_blockers:
        advisories.append({
            "code": "legacy_blocker_note",
            "message": blocker,
            "suggested_first_action": "",
        })
    return _normalize_advisories(advisories)


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
