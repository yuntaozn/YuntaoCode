"""从 ConversationMessagesStreamHandler 提取的提示构建函数。

所有函数都是纯函数：只依赖参数并产生确定性字符串输出；
不使用 ``self``，不执行 I/O，也不产生 i18n 副作用。"""

from __future__ import annotations

from typing import Any

from runtime.run_fact_summary import (
    build_tool_failure_fact_summary,
    format_tool_failure_fact_summary,
)
from runtime.run_completion import (
    build_completion_evidence_pack,
    format_completion_evidence_pack,
)
from runtime.agent_strategy.convergence import (
    build_execution_convergence_decision,
    format_convergence_decision,
)


# ---------------------------------------------------------------------------
# Runtime 证据提示
# ---------------------------------------------------------------------------

def execution_convergence_prompt(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
) -> str:
    """暴露重复执行事实，但不选择下一条路线。"""
    facts = build_tool_failure_fact_summary(
        workspace_path=workspace_path,
        tool_events=tool_events,
    )
    convergence = build_execution_convergence_decision(tool_events)
    convergence_text = format_convergence_decision(convergence)
    return (
        "Repeated failure recovery advisory.\n"
        f"{format_tool_failure_fact_summary(facts)}\n"
        f"{convergence_text + chr(10) if convergence_text else ''}"
        "The runtime is not choosing the next strategy. Use the facts above to "
        "decide whether to change tool, change arguments, gather smaller context, "
        "verify an existing result, ask the user, or finalize with an honest "
        "boundary. Avoid repeating the same tool with the same missing or oversized "
        "arguments when no new progress was observed."
    )


def malformed_tool_call_prompt(workspace_path: str, unfinished_text: str) -> str:
    snippet = unfinished_text[-300:]
    return (
        f"检测到不可执行的工具调用格式。当前项目：{workspace_path}。\n"
        f"模型原始片段：{snippet}\n"
        "不要在普通文本中输出 <toolcall>、<mcreference> 或 FunctionCall 标记。"
        "请使用当前接口提供的结构化工具调用，并一次性提供该工具要求的全部参数。"
        "如果尚不知道目标文件路径，先使用带明确 path 参数的目录扫描或代码文件列表工具。"
        "如果不需要工具，请直接给出最终回答，不要声称即将执行。"
    )


def write_repair_prompt(
    tool_id: str,
    arguments: dict[str, Any],
    event: dict[str, Any],
    workspace_path: str,
) -> str:
    target = arguments.get("path") or arguments.get("output_path") or workspace_path
    error = str(event.get("error") or "")
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    reason = str(output.get("reason") or "")
    facts = build_tool_failure_fact_summary(
        workspace_path=workspace_path,
        tool_events=[event],
    )
    return (
        "Write failure recovery advisory.\n"
        f"Current project: {workspace_path}\n"
        f"Failed tool proposed by model: {tool_id}\n"
        f"Target hint from failed call: {target}\n"
        f"Failure error: {error or '(none)'}\n"
        f"Failure reason: {reason or '(none)'}\n"
        f"{format_tool_failure_fact_summary(facts)}\n"
        "The runtime is not choosing the repair strategy. The previous write did "
        "not happen, so do not claim the file was changed unless a later tool "
        "call succeeds. Choose the smallest reliable next step from the task "
        "goal and observed facts."
    )


def oversized_tool_arguments_prompt(
    workspace_path: str,
    accumulated_chars: int,
    limit_chars: int,
) -> str:
    return (
        "Runtime guard: the current model round was stopped before execution "
        "because the streamed tool-call arguments grew too large.\n"
        f"Current project: {workspace_path}\n"
        f"Accumulated tool argument characters: {accumulated_chars}\n"
        f"Runtime guard limit: {limit_chars}\n"
        "This is not a task failure and not a permission denial. Choose the next "
        "execution strategy yourself from the task goal and observed facts. Do "
        "not repeat one oversized tool call unless new evidence shows it can fit."
    )


# ---------------------------------------------------------------------------
# Task 级提示
# ---------------------------------------------------------------------------

def format_execution_plan_for_context(plan: dict[str, Any]) -> str:
    lines = [f"计划执行：{plan.get('title') or '计划执行'}"]
    for index, step in enumerate(plan.get("steps") or [], start=1):
        lines.append(
            f"{index}. {step.get('title')}: {step.get('description')}"
            + (f"（工具建议：{step.get('tool_hint')}）" if step.get("tool_hint") else "")
        )
    return "\n".join(lines)


def execute_plan_prompt(plan: dict[str, Any], mode: str | None) -> str:
    _ = (plan, mode)
    return (
        "计划执行模式已开启。上面的计划是参考路线，不是固定轨道；"
        "如工具结果、插话或文件结构显示原计划不合适，可以跳过、合并、拆分或追加步骤。"
        "计划只是运行审计和协作上下文，不是新的人工确认门；权限和高风险确认由运行时呈现。"
        "如果任务信息足够，可以直接调用最合适的工具推进；如果信息不足，可以明确向用户提问。"
        "需要读取本地资料或代码时可以调用本地工具；每次工具返回后结合新事实继续判断下一步。"
        "涉及本地变更时，只有观察到成功生成或更新任务契约中的目标产物后，才能声称已经修改完成。"
        "最终回答要说明：完成了哪些步骤、使用了哪些文件或工具、结果和未完成/不确定项。"
    )


def completion_review_prompt(
    workspace_path: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any],
    *,
    tool_events: list[dict[str, Any]] | None = None,
    completion_decisions: list[dict[str, Any]] | None = None,
    task_route_evidence: dict[str, Any] | None = None,
    evidence_pack: dict[str, Any] | None = None,
) -> str:
    """提示模型根据运行时事实自查完成情况。

    该提示有意面向证据而非特定文件类型。Runtime 不决定下一策略，只提供事实，
    要求模型继续使用工具或如实结束。"""
    if not evidence_pack:
        evidence_pack = build_completion_evidence_pack(
            workspace_path=workspace_path,
            task_contract=task_contract,
            run_result=run_result,
            tool_events=tool_events,
            completion_decisions=completion_decisions,
            task_route_evidence=task_route_evidence,
        )
    return (
        "Completion self-review from runtime facts.\n"
        f"Current project: {workspace_path}\n"
        f"{format_completion_evidence_pack(evidence_pack)}\n"
        "These facts are evidence, not a forced route. Decide whether the task "
        "is actually complete. If the goal is not closed, continue with the "
        "most suitable tool, verification, or repair strategy. If it is closed, "
        "write a final answer that states what changed, what was verified, what "
        "was not verified, and any remaining risk. Do not claim completion "
        "beyond the observed deliverables and verification evidence. The runtime "
        "will record your observable choice as completion-loop evidence; this "
        "record is for audit and replay, not a hard constraint on your strategy.\n"
        "A non-empty answer without another tool call is your decision to end "
        "the execution loop. Runtime evidence may still record the result as "
        "partial or failed; that evidence does not force another model round. "
        "For stronger audit detail, you may put this compact JSON assessment "
        "on the first line, then write the ordinary user-facing Markdown answer "
        "below it. The runtime removes only the recognized first line:\n"
        '{"schema_version":"completion_self_assessment.v1",'
        '"kind":"completion_self_assessment","goal_closed":true,'
        '"remaining_work":[],"verification_limits":[]}\n'
        "Your normal final answer starts on the next line.\n"
        "Set goal_closed from your own task judgment. Put concrete unfinished "
        "work in remaining_work and evidence boundaries in verification_limits. "
        "This header is optional; ordinary Markdown remains supported."
    )


def result_synthesis_prompt(
    workspace_path: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any],
    *,
    previous_answer: str = "",
    tool_events: list[dict[str, Any]] | None = None,
    completion_decisions: list[dict[str, Any]] | None = None,
    task_route_evidence: dict[str, Any] | None = None,
    evidence_pack: dict[str, Any] | None = None,
) -> str:
    """要求模型根据运行时事实编写最终用户结果。"""
    if not evidence_pack:
        evidence_pack = build_completion_evidence_pack(
            workspace_path=workspace_path,
            task_contract=task_contract,
            run_result=run_result,
            tool_events=tool_events,
            completion_decisions=completion_decisions,
            task_route_evidence=task_route_evidence,
        )
    previous = previous_answer.strip()
    previous_block = (
        "\nPrevious assistant draft, which may be incomplete or overclaiming:\n"
        f"{previous[-3000:]}\n"
        if previous
        else ""
    )
    return (
        "Write the final user-facing answer for this run from runtime facts.\n"
        "The runtime facts are the source of truth. You may choose the wording, "
        "but you must not claim work that is not supported by observed "
        "deliverables, verification evidence, or tool results.\n"
        f"Current project: {workspace_path}\n"
        f"{format_completion_evidence_pack(evidence_pack)}\n"
        f"{previous_block}\n"
        "Answer requirements:\n"
        "- If status is partial, failure, or stopped, say that clearly first.\n"
        "- Summarize completed work and changed artifacts only when observed.\n"
        "- Summarize verification evidence and call out missing verification.\n"
        "- Give the next useful action when the run did not fully close.\n"
        "- Keep the answer concise and do not mention hidden system prompts."
    )


def guidance_reorientation_prompt(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    execution_plan: dict[str, Any] | None,
) -> str:
    recent_tools = []
    for event in tool_events[-8:]:
        tool = str(event.get("tool") or "")
        status = str(event.get("status") or "")
        if tool:
            recent_tools.append(f"{tool}:{status}")
    plan_hint = ""
    if execution_plan:
        plan_hint = "此前计划已标记为 interrupted；它仍是历史记录，不是当前路线。"
    return (
        "运行中用户指令事实：用户在当前 Run 中追加了新信息。\n"
        f"当前项目目录：{workspace_path}\n"
        f"最近工具事件：{', '.join(recent_tools) if recent_tools else '暂无'}\n"
        f"{plan_hint}\n"
        "最新用户指令优先于与它冲突的旧计划和旧推理；已有工具结果仍作为事实保留。"
        "运行时不指定新的执行策略，请结合刚刚更新的任务契约自行决定下一步。"
    )


def max_rounds_message(max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
    lines = [
        f"本轮已用完当前工具执行预算（{max_rounds} 轮）。运行记录已保存，可基于已有事实继续、恢复或换策略。",
        "",
    ]
    if tool_events:
        lines.append("最近的工具调用：")
        for event in tool_events[-6:]:
            tool = event.get("tool") or event.get("name") or "unknown"
            status = event.get("status") or "unknown"
            path = ""
            event_input = event.get("input")
            if isinstance(event_input, dict):
                path = str(event_input.get("path") or "")
            error = event.get("error") or ""
            detail = f"- {tool}: {status}"
            if path:
                detail += f"（{path}）"
            if error:
                detail += f"；错误：{error}"
            lines.append(detail)
    else:
        lines.append("本轮没有成功产生可记录的工具调用。")
    lines.extend([
        "",
        "后续可继续依据：以上工具事实、用户后续补充、关键文件、关键词或期望结果。",
    ])
    return "\n".join(lines)
