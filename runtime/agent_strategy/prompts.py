"""Prompt construction functions extracted from ConversationMessagesStreamHandler.

All functions are pure — they depend only on their parameters and produce
deterministic string output.  No ``self``, no I/O, no i18n side-effects.
"""

from __future__ import annotations

from typing import Any

from .classifiers import (
    has_successful_write,
    is_write_tool,
    is_verification_tool,
)
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
# Intervention / nudge prompts
# ---------------------------------------------------------------------------

def progress_observer_prompt(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    code_change_intent: bool,
    reason: str,
    *,
    target_deliverable_observed: bool | None = None,
    required_modalities: list[str] | tuple[str, ...] | None = None,
    observed_modalities: list[str] | tuple[str, ...] | None = None,
    missing_modalities: list[str] | tuple[str, ...] | None = None,
    visual_verification_tool_ids: list[str] | tuple[str, ...] | None = None,
    runtime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> str:
    observations: list[str] = []
    if target_deliverable_observed is not None:
        observations.append(
            "observed_target_deliverable="
            + ("present" if target_deliverable_observed else "missing")
        )
    elif code_change_intent:
        observations.append(
            "observed_write_evidence="
            + ("present" if has_successful_write(tool_events) else "missing")
        )
    observations.append(f"observed_tool_events={len(tool_events)}")
    observation_text = "; ".join(observations)
    verification_context = _verification_retry_context(
        required_modalities=required_modalities,
        observed_modalities=observed_modalities,
        missing_modalities=missing_modalities,
        visual_verification_tool_ids=visual_verification_tool_ids,
        runtime_diagnostics=runtime_diagnostics,
    )
    return (
        "Runtime observation only. The runtime is not choosing a strategy.\n"
        f"Workspace: {workspace_path}\n"
        f"Reason: {reason}\n"
        f"Observed facts: {observation_text}\n"
        f"{verification_context}"
        "Decide the next step from the task goal and observed facts. Do not "
        "claim completion beyond evidence produced by tools or explicit user "
        "input. If evidence is still missing, choose whether to verify, revise, "
        "try a different route, or explicitly ask the user for the missing "
        "condition instead of stopping only because one check was insufficient."
    )


def repeated_failure_strategy_prompt(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
) -> str:
    """Ask the model to choose a materially different route after repetition."""
    latest = tool_events[-1] if tool_events else {}
    tool_id = str(latest.get("tool") or "unknown")
    error = str(latest.get("error") or "unknown failure").strip()
    output = latest.get("output") if isinstance(latest.get("output"), dict) else {}
    reason = str(output.get("reason") or "").strip()
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
# Task-level prompts
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
    """Prompt the model to self-audit completion from runtime facts.

    This is intentionally evidence-oriented instead of file-type-specific. The
    runtime does not decide the next strategy; it exposes facts and asks the
    model to either continue with tools or finish honestly.
    """
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
        "If you finish instead of calling another tool, put this compact JSON "
        "assessment on the first line, then write the ordinary user-facing "
        "Markdown answer below it. The runtime removes only the first line:\n"
        '{"schema_version":"completion_self_assessment.v1",'
        '"kind":"completion_self_assessment","goal_closed":true,'
        '"remaining_work":[],"verification_limits":[]}\n'
        "Your normal final answer starts on the next line.\n"
        "Set goal_closed from your own task judgment. Put concrete unfinished "
        "work in remaining_work and evidence boundaries in verification_limits."
    )


def completion_reentry_prompt(
    workspace_path: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any],
    completion_decision: dict[str, Any],
    *,
    tool_events: list[dict[str, Any]] | None = None,
    completion_decisions: list[dict[str, Any]] | None = None,
    task_route_evidence: dict[str, Any] | None = None,
    evidence_pack: dict[str, Any] | None = None,
) -> str:
    """Return an evidence prompt when a final candidate still has gaps."""
    if not evidence_pack:
        evidence_pack = build_completion_evidence_pack(
            workspace_path=workspace_path,
            task_contract=task_contract,
            run_result=run_result,
            tool_events=tool_events,
            completion_decisions=completion_decisions,
            task_route_evidence=task_route_evidence,
        )
    action = str(completion_decision.get("action") or "unknown")
    content_chars = completion_decision.get("content_chars")
    return (
        "Completion candidate re-entry from runtime facts.\n"
        f"Current project: {workspace_path}\n"
        f"Observed model decision: action={action}; content_chars={content_chars}\n"
        f"{format_completion_evidence_pack(evidence_pack)}\n"
        "The previous response looked like a final answer, but the evidence pack "
        "still contains unresolved verification facts. This is not a forced route "
        "and not a denial of your judgment. Choose the next step yourself: gather "
        "more evidence, inspect how to verify, run a suitable check, repair the "
        "result, ask the user for an external boundary, or finish with an explicit "
        "limitation if further verification is not useful or possible. Do not turn "
        "a partial or weakly verified result into a success claim."
    )


def final_answer_prompt(workspace_path: str) -> str:
    return (
        "Final answer phase. Do not call more tools in this phase.\n"
        f"Current project: {workspace_path}\n"
        "Write from the latest observed runtime facts. State completed work, "
        "changed artifacts, verification evidence, and remaining risk only when "
        "the tool history supports them. If something was not verified, say so "
        "directly instead of turning it into a success claim."
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
    """Ask the model to write the final user-facing result from runtime facts."""
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


def _format_prompt_list(values: list[str] | tuple[str, ...] | None) -> str:
    result: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return ", ".join(result)


def _verification_retry_context(
    *,
    required_modalities: list[str] | tuple[str, ...] | None = None,
    observed_modalities: list[str] | tuple[str, ...] | None = None,
    missing_modalities: list[str] | tuple[str, ...] | None = None,
    visual_verification_tool_ids: list[str] | tuple[str, ...] | None = None,
    runtime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> str:
    rows: list[str] = []
    required = _format_prompt_list(required_modalities)
    observed = _format_prompt_list(observed_modalities)
    missing = _format_prompt_list(missing_modalities)
    visual_tools = _format_prompt_list(visual_verification_tool_ids)
    if required:
        rows.append(f"- required_modalities={required}")
    if observed:
        rows.append(f"- observed_modalities={observed}")
    if missing:
        rows.append(f"- missing_modalities={missing}")
    if visual_tools:
        rows.append(f"- visual_verification_tools={visual_tools}")
    for row in _format_runtime_diagnostics(runtime_diagnostics):
        rows.append(row)
    if not rows:
        return ""
    guidance = (
        "\nCurrent verification facts from this run:\n"
        + "\n".join(rows)
        + "\nUse these facts to decide the next verification step; they are not a fixed route.\n"
    )
    if "behavioral" in {str(item or "").strip().lower() for item in (missing_modalities or [])}:
        if "preview.interact_page" in {str(item or "").strip() for item in (visual_verification_tool_ids or [])}:
            guidance += (
                "If the target is a UI or local HTML page, preview.interact_page can run "
                "bounded page actions and assertions to produce behavioral evidence.\n"
            )
    return guidance


def _format_runtime_diagnostics(
    diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[str]:
    rows: list[str] = []
    for item in diagnostics or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "runtime_diagnostic").strip()
        severity = str(item.get("severity") or "").strip()
        message = str(item.get("message") or "").strip()
        if not code and not message:
            continue
        pieces = [code]
        if severity:
            pieces.append(f"severity={severity}")
        if message:
            pieces.append(f"message={message[:260]}")
        url = str(item.get("url") or "").strip()
        if url:
            pieces.append(f"url={url[:260]}")
        resources = item.get("resources")
        if isinstance(resources, list) and resources:
            formatted = []
            for resource in resources[:5]:
                if not isinstance(resource, dict):
                    continue
                resource_url = str(resource.get("url") or "").strip()
                status = str(resource.get("status") or "").strip()
                content_type = str(resource.get("content_type") or "").strip()
                if resource_url:
                    formatted.append(
                        f"{resource_url[:160]} status={status or '?'} type={content_type or '?'}"
                    )
            if formatted:
                pieces.append("resources=[" + "; ".join(formatted) + "]")
        rows.append("- runtime_diagnostic=" + "; ".join(pieces))
        if len(rows) >= 8:
            break
    return rows


def verifier_retry_prompt(
    mode: str | None,
    workspace_path: str,
    *,
    required_modalities: list[str] | tuple[str, ...] | None = None,
    observed_modalities: list[str] | tuple[str, ...] | None = None,
    missing_modalities: list[str] | tuple[str, ...] | None = None,
    visual_verification_tool_ids: list[str] | tuple[str, ...] | None = None,
    runtime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> str:
    _ = mode
    context = _verification_retry_context(
        required_modalities=required_modalities,
        observed_modalities=observed_modalities,
        missing_modalities=missing_modalities,
        visual_verification_tool_ids=visual_verification_tool_ids,
        runtime_diagnostics=runtime_diagnostics,
    )
    return (
        "Verification evidence advisory, not a hard tool constraint.\n"
        f"Workspace: {workspace_path}\n"
        f"{context}"
        "The current evidence does not yet satisfy the model-declared verification "
        "modalities. State queries, inspections, captures, tests, static checks, "
        "and behavioral probes provide different evidence strengths when their "
        "tools are visible. A state-changing call alone is not independent proof "
        "unless its result contains meaningful observation facts. The model decides "
        "whether to gather more evidence, change route, ask the user, or finalize "
        "with an explicit limitation."
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
