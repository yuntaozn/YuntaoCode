"""用运行时能力事实落地模型任务契约。

首次语义判断由模型负责，当前能力快照由 Runtime 管理。本模块协调两者，
不在 Runner 中增加特定场景分支。"""

from __future__ import annotations

from typing import Any


def ground_task_contract_with_capabilities(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    user_content: str = "",
) -> bool:
    """用运行时能力事实落地模型选定的外部状态目标。

    Runtime 只解析模型已经选定的能力 ID，并在外部状态交付物遗漏该 ID 时补入。
    它不根据用户文本选择 Provider，也不改变执行路线。"""
    if not isinstance(contract, dict) or not isinstance(snapshot, dict):
        return False
    _ = user_content  # 兼容输入；语义文本匹配有意禁用。
    if not bool(contract.get("requires_state_change")):
        return False

    selected_ids = _string_set(contract.get("capability_ids"))
    external_target = _has_external_state_deliverable(contract)
    capability = _single_selected_external_state_capability(snapshot, selected_ids)
    if not capability:
        return False

    capability_id = str(capability.get("id") or "").strip()
    if not capability_id:
        return False

    changed = bool(
        external_target
        and _attach_capability_to_external_deliverables(contract, capability_id)
    )
    if changed:
        _add_system_override(contract, "capability_reference_normalized")
    return changed


def _has_external_state_deliverable(contract: dict[str, Any]) -> bool:
    deliverables = contract.get("deliverables") if isinstance(contract.get("deliverables"), list) else []
    return any(
        isinstance(item, dict)
        and str(item.get("kind") or "").strip().lower() == "external_state"
        for item in deliverables
    )


def _single_selected_external_state_capability(
    snapshot: dict[str, Any],
    selected_ids: set[str],
) -> dict[str, Any] | None:
    if not selected_ids:
        return None
    matches: list[dict[str, Any]] = []
    for capability in snapshot.get("capabilities") or []:
        if not isinstance(capability, dict):
            continue
        if str(capability.get("id") or "").strip() not in selected_ids:
            continue
        effects = _string_set(capability.get("effects")) | _string_set(
            capability.get("available_effects")
        )
        source = str(capability.get("source") or capability.get("source_type") or "").lower()
        if "external_state_change" in effects or source == "mcp" or str(capability.get("id") or "").startswith("mcp."):
            matches.append(capability)
    for issue in snapshot.get("capability_issues") or []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("capability_id") or "").strip() not in selected_ids:
            continue
        if _issue_represents_external_capability(issue):
            matches.append({
                "id": str(issue.get("capability_id") or ""),
                "name": str(issue.get("name") or issue.get("capability_id") or ""),
                "description": str(issue.get("message") or ""),
                "available": False,
                "source": str(issue.get("source_type") or ""),
            })
    unique = {
        str(item.get("id") or "").strip(): item
        for item in matches
        if str(item.get("id") or "").strip()
    }
    return next(iter(unique.values())) if len(unique) == 1 else None


def _issue_represents_external_capability(issue: dict[str, Any]) -> bool:
    source_type = str(issue.get("source_type") or "").strip().lower()
    capability_id = str(issue.get("capability_id") or "").strip().lower()
    return source_type == "mcp" or capability_id.startswith("mcp.")


def _attach_capability_to_external_deliverables(
    contract: dict[str, Any],
    capability_id: str,
) -> bool:
    deliverables = contract.get("deliverables") if isinstance(contract.get("deliverables"), list) else []
    changed = False
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "external_state":
            continue
        if not str(item.get("capability_id") or "").strip():
            item["capability_id"] = capability_id
            changed = True
    return changed


def _add_system_override(contract: dict[str, Any], value: str) -> None:
    overrides = [
        str(item)
        for item in contract.get("system_overrides") or []
        if str(item or "").strip()
    ]
    overrides.append(value)
    contract["system_overrides"] = list(dict.fromkeys(overrides))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_set(value: Any) -> set[str]:
    return set(_string_list(value))
