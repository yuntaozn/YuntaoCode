"""模型自愿声明的计划记录；不生成计划、匹配工具或推断步骤状态。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def create_model_plan(title: str, steps: list[str]) -> dict[str, Any] | None:
    """保存已经通过原生控制工具校验的步骤，空列表表示清除计划。"""
    if not steps:
        return None
    return {
        "title": title,
        "source": "model_declared",
        "steps": [{"title": step, "status": "pending", "source": "model_declared"} for step in steps],
    }


def apply_model_plan_updates(
    execution_plan: dict[str, Any] | None,
    updates: list[dict[str, Any]],
    tool_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """原子校验模型步骤声明及其证据引用，不推断工具与步骤的语义关系。"""
    plan = deepcopy(execution_plan)
    events = {str(event.get("task_id")): event for event in tool_events if event.get("task_id")}
    seen = set()
    for update in updates:
        if not isinstance(update, dict) or set(update) - {"index", "status", "tool_task_ids", "note"}:
            raise ValueError("invalid plan step update")
        index, status = update.get("index"), update.get("status")
        if type(index) is not int or not plan or not 0 <= index < len(plan.get("steps", [])) or index in seen:
            raise ValueError("plan step index must identify one existing step")
        seen.add(index)
        if not isinstance(status, str) or status not in {"pending", "running", "completed", "failed", "skipped"}:
            raise ValueError("invalid plan step status")
        refs = update.get("tool_task_ids", [])
        if not isinstance(refs, list) or len(refs) > 24 or any(not isinstance(ref, str) or ref not in events for ref in refs):
            raise ValueError("plan evidence must reference observed tool task IDs")
        if status == "completed" and any(events[ref].get("status") != "success" for ref in refs):
            raise ValueError("completed steps cannot cite unsuccessful tool tasks")
        note = update.get("note", "")
        if not isinstance(note, str) or len(note) > 500:
            raise ValueError("plan note must be a string of at most 500 characters")
        plan["steps"][index].update({
            "status": status, "source": "model_declared", "tool_task_ids": refs,
            "evidence_status": "referenced" if refs else "unverified", "note": note,
        })
    return plan
