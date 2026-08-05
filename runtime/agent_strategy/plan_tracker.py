"""从 ConversationMessagesStreamHandler 提取的执行计划生命周期管理。

本模块函数不依赖 Handler 或 Runtime，也不执行 I/O。生命周期辅助函数有意
原地修改传入的执行计划字典，使对话循环可持续使用同一个共享计划对象。"""

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
# 辅助函数
# ---------------------------------------------------------------------------

def normalize_tool_id(value: Any) -> str:
    """将原始工具标识转换为规范的点分形式。"""
    return canonical_tool_id(value)


# ---------------------------------------------------------------------------
# 计划规范化与提取
# ---------------------------------------------------------------------------

def extract_plan_json(raw_plan: str) -> dict[str, Any] | None:
    """尝试从原始计划文本（可能带代码围栏）中提取 JSON 对象。"""
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
    """将 *raw_plan* 解析为规范化执行计划字典。

    解析失败时回退到 :func:`fallback_execution_plan`。"""
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
    """模型计划无法解析时返回中性的审计计划。

    回退计划保持 UI 和 Trace 可读，但不得变成模式专属流程或工具路线。
    实际下一步仍由模型根据任务契约和可见能力选择。"""
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
# 计划步骤匹配与生命周期
# ---------------------------------------------------------------------------

def tool_matches_plan_step(tool_id: str, step: dict[str, Any]) -> bool:
    """判断 *tool_id* 是否满足计划步骤的提示和意图。"""
    hint = normalize_tool_id(step.get("tool_hint")).lower()
    title = str(step.get("title") or "").lower()
    description = str(step.get("description") or "").lower()
    text = f"{hint} {title} {description}"
    tool_id = normalize_tool_id(tool_id).lower()
    if not tool_id:
        return False
    # 精确匹配：tool_hint 包含真实工具 ID
    if tool_id in hint:
        return True

    # 当计划步骤指定具体工具时，不要仅因措辞相似
    # 就使用另一工具完成该步骤。
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
    """将下一个匹配的待处理计划步骤标记为 *running*。

    返回匹配步骤索引；没有匹配项时返回 ``None``。"""
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
    """根据工具事件将计划步骤标记为已完成或失败。"""
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
    """将所有剩余待处理或运行中步骤标记为已跳过。"""
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
    """发生中断时，将当前运行步骤重置为待处理。"""
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
