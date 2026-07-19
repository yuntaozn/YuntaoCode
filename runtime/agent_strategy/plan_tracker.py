"""Execution plan lifecycle management extracted from ConversationMessagesStreamHandler.

Functions in this module have no handler/runtime dependency and perform no I/O.
Lifecycle helpers intentionally mutate the provided execution-plan dictionary
in place so the conversation loop can keep a single shared plan object.
"""

from __future__ import annotations

import json
from typing import Any

from .classifiers import (
    canonical_tool_id,
    is_write_tool,
    is_verification_tool,
    explorer_tool_ids,
    RECON_TOOL_IDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_tool_id(value: Any) -> str:
    """Convert a raw tool identifier to canonical dot-separated form."""
    return canonical_tool_id(value)


# ---------------------------------------------------------------------------
# Plan normalization / extraction
# ---------------------------------------------------------------------------

def extract_plan_json(raw_plan: str) -> dict[str, Any] | None:
    """Try to extract a JSON object from a raw plan string (possibly fenced)."""
    text = raw_plan.strip()
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


def normalize_execution_plan(raw_plan: str, mode: str | None) -> dict[str, Any]:
    """Parse *raw_plan* into a normalized execution plan dict.

    Falls back to :func:`fallback_execution_plan` when parsing fails.
    """
    parsed = extract_plan_json(raw_plan)
    if not parsed:
        return fallback_execution_plan(mode)

    raw_steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw_steps[:8], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or f"步骤 {index}").strip()
        description = str(item.get("description") or item.get("detail") or "").strip()
        tool_hint = str(item.get("tool_hint") or item.get("tool") or "").strip()
        steps.append({
            "title": title[:80],
            "description": description[:260],
            "tool_hint": tool_hint[:120],
            "status": "pending",
        })

    if not steps:
        return fallback_execution_plan(mode)

    return {
        "title": str(parsed.get("title") or "计划执行").strip()[:80],
        "steps": steps,
        "raw": raw_plan[:4000],
    }


def fallback_execution_plan(mode: str | None) -> dict[str, Any]:
    """Return a neutral audit plan when the model plan cannot be parsed.

    The fallback keeps the UI and trace readable, but it must not become a
    mode-specific workflow or tool route.  The model still chooses the actual
    next actions from the task contract and visible capabilities.
    """
    _ = mode
    steps = [
        ("确认当前目标", "根据本轮用户请求和任务契约确认要达成的结果。", ""),
        ("收集必要证据", "按当前目标选择需要读取、观察或检查的最小上下文。", ""),
        ("执行模型选择的动作", "由模型根据可见能力选择读取、写入、外部状态变更或回答路线。", ""),
        ("验证可观察结果", "根据任务契约需要检查产物、状态、内容或运行证据。", ""),
        ("基于事实收束", "说明已完成事项、证据、不确定项和下一步。", ""),
    ]
    return {
        "title": "计划执行",
        "steps": [
            {"title": title, "description": desc, "tool_hint": tool, "status": "pending"}
            for title, desc, tool in steps
        ],
        "raw": "",
    }


# ---------------------------------------------------------------------------
# Plan step matching & lifecycle
# ---------------------------------------------------------------------------

def tool_matches_plan_step(tool_id: str, step: dict[str, Any]) -> bool:
    """Determine whether *tool_id* satisfies a plan step's hint and intent."""
    hint = normalize_tool_id(step.get("tool_hint")).lower()
    title = str(step.get("title") or "").lower()
    description = str(step.get("description") or "").lower()
    text = f"{hint} {title} {description}"
    tool_id = normalize_tool_id(tool_id).lower()
    if not tool_id:
        return False
    # Exact match: tool_hint contains the real tool ID
    if tool_id in hint:
        return True

    # When a plan step names a concrete tool, avoid completing it with a
    # different tool just because the wording is similar.
    hint_has_tool_prefix = any(
        prefix in hint for prefix in ("filesystem.", "code.", "document.", "shell.", "git.")
    )
    if hint_has_tool_prefix:
        return False

    write_terms = (
        "写", "写入", "修改", "编辑", "替换", "创建", "新增", "生成", "导出",
        "优化", "补充", "更新", "write", "edit", "replace", "create",
        "generate", "export", "update", "modify", "optimize",
    )
    read_terms = (
        "读", "读取", "扫描", "搜索", "查看", "枚举", "列出", "定位",
        "read", "scan", "search", "list", "inspect", "enumerate",
    )
    verify_terms = (
        "验证", "测试", "检查", "运行", "diff", "status", "verify", "test", "lint",
    )
    if is_write_tool(tool_id):
        return any(term in text for term in write_terms)
    if is_verification_tool(tool_id, None):
        return any(term in text for term in verify_terms)
    if tool_id in explorer_tool_ids("coding") or tool_id in (RECON_TOOL_IDS | {"git.status", "git.diff", "git.log"}):
        return any(term in text for term in read_terms)
    return False


def mark_next_plan_step_running(
    execution_plan: dict[str, Any] | None,
    tool_call: dict[str, Any],
) -> int | None:
    """Mark the next matching pending plan step as *running*.

    Returns the matched step index, or ``None`` if no step matched.
    """
    if not execution_plan:
        return None
    steps = execution_plan.get("steps")
    if not isinstance(steps, list):
        return None
    function = tool_call.get("function") or {}
    active_tool = str(function.get("name") or "")
    tool_id = normalize_tool_id(active_tool)
    pending_indexes = [
        index for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("status") in {None, "pending"}
    ]
    if not pending_indexes:
        return None

    matched_index = next(
        (
            index for index in pending_indexes
            if tool_matches_plan_step(tool_id, steps[index])
        ),
        None,
    )
    if matched_index is None:
        return None

    step = steps[matched_index]
    step["status"] = "running"
    step["active_tool"] = active_tool
    return matched_index


def finish_plan_step(
    execution_plan: dict[str, Any],
    step_index: int,
    tool_event: dict[str, Any],
) -> None:
    """Mark a plan step as completed or failed based on the tool event."""
    steps = execution_plan.get("steps") or []
    if step_index < 0 or step_index >= len(steps) or not isinstance(steps[step_index], dict):
        return
    step = steps[step_index]
    step["status"] = "completed" if tool_event.get("status") == "success" else "failed"
    step["tool"] = tool_event.get("name") or tool_event.get("tool") or ""
    step["task_id"] = tool_event.get("task_id") or ""
    if tool_event.get("error"):
        step["error"] = tool_event["error"]


def complete_remaining_plan_steps(
    execution_plan: dict[str, Any],
    *,
    failed: bool,
    had_tool_events: bool = True,
) -> None:
    """Mark all remaining pending/running steps as skipped."""
    for step in execution_plan.get("steps") or []:
        if not isinstance(step, dict) or step.get("status") not in {None, "pending", "running"}:
            continue
        if failed:
            step["status"] = "skipped"
        elif had_tool_events:
            step["status"] = "skipped"
            step.setdefault("note", "未观察到对应工具事件")
        else:
            step["status"] = "skipped"


def interrupt_execution_plan(execution_plan: dict[str, Any]) -> None:
    """Reset the currently running plan step back to pending (for interruptions)."""
    steps = execution_plan.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("status") == "running":
            step["status"] = "pending"
            note = str(step.get("note") or "").strip()
            step["note"] = f"{note}；收到插话后待重新审视".strip("；")
            break
