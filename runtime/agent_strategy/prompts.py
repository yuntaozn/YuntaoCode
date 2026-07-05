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
    build_run_fact_summary,
    build_tool_failure_fact_summary,
    format_run_fact_summary,
    format_tool_failure_fact_summary,
)


# ---------------------------------------------------------------------------
# Stage prompts
# ---------------------------------------------------------------------------

def stage_status_message(stage: str) -> str:
    return {
        "writer": "写作者正在形成论文产出",
        "integrity_gate": "学术质量门正在检查事实与引用风险",
        "explorer": "侦察者正在收集必要证据",
        "editor": "执行者正在基于证据执行修改",
        "verifier": "验证者正在检查变更结果",
        "creator": "创作者正在生成或导出文档",
        "reviewer": "审查者正在收束任务并形成结论",
    }.get(stage, "正在执行阶段任务")


def stage_prompt(
    stage: str,
    workspace_path: str,
    mode: str | None,
    code_change_intent: bool,
) -> str:
    if stage == "explorer":
        if mode == "paper":
            return (
                "你现在是 Explorer（论文侦察者）。职责重点是收集论文任务所需的最小可靠证据。\n"
                f"当前项目目录：{workspace_path}\n"
                "阶段只是参考，不会限制工具；如发现必须写入、验证或换工具，可以基于证据调整计划。\n"
                "优先避免：编造文献、补造实验结果、把推测说成事实、反复读取同一材料。\n"
                "请形成 Material Passport：已读材料、材料类型、Data Access 层级（raw/redacted/verified）、已确认事实、缺失证据、需要用户确认的关键决策。\n"
                "推进条件：已确认足够支撑本轮回答的材料后，进入写作、验证或总结。"
            )
        return (
            "你现在是 Explorer（侦察者）。职责重点是收集完成任务所需的最小证据。\n"
            f"当前项目目录：{workspace_path}\n"
            "阶段只是参考，不会限制工具；如证据已足够，应主动进入写入、验证或总结，而不是机械继续搜索。\n"
            "优先避免：运行无关命令、反复搜索同一关键词、重复读取同一范围。"
        )
    if stage == "editor":
        return (
            "你现在是 Editor（执行者）。职责：基于已收集的证据执行真实修改。\n"
            f"当前项目目录：{workspace_path}\n"
            "所有工具仍然可用；请选择完成修改所需的最合适工具。\n"
            "规则：\n"
            "1. 编辑前应基于本轮已读取的真实文件内容确认目标片段、缩进和 old_text；如果尚未读取目标片段，优先调用 filesystem.read_file。\n"
            "2. 构造 old_text 时，直接复制从 read_file 结果中看到的原文，不要调整空格或缩进。\n"
            "3. 如果 old_text 难以稳定匹配，可在重新读取目标位置后，使用 code.edit_file 的 start_line/end_line/new_text 做有界行号替换。\n"
            "4. 如果写入失败（如 old_text not found），应重新读取文件对应位置，基于真实内容换一种可靠写入策略，不要凭记忆猜测。\n"
            "5. 不要伪造修改结果，不要声称已完成但未实际调用写入工具。"
        )
    if stage == "writer":
        return (
            "你现在是 Writer（论文写作者）。职责：只基于 Planner 和 Explorer 已确认的材料形成论文产出。\n"
            f"当前项目目录：{workspace_path}\n"
            "默认在对话中输出，不要私自写文件。只有用户明确要求保存、生成草稿文件或导出时，才调用写入/导出工具。\n"
            "所有工具仍然可用；如发现材料不足，可以补读；如用户要求保存或导出，可以写入或导出。\n"
            "输出必须区分：事实提取、推断、建议、可直接使用的草稿文本。不要编造引用、作者、DOI、实验结果、统计显著性或方法细节。\n"
            "遇到选题方向、研究假设、章节大纲、投稿目标、审稿回复策略等关键决策时，给出可选方案并标注需要用户确认。"
        )
    if stage == "integrity_gate":
        return (
            "你现在是 Integrity Gate（学术质量门）。职责重点是检查本轮论文输出是否存在学术可靠性风险。\n"
            f"当前项目目录：{workspace_path}\n"
            "阶段只是参考，不会限制工具；如证据不足，可以补充读取必要材料。\n"
            "请按以下失败模式逐项判断 CLEAR / SUSPECTED / INSUFFICIENT EVIDENCE：\n"
            "1. 实现或事实错误被 AI 自审放过；2. 幻觉引用；3. 幻觉实验结果；4. 依赖捷径或证据不足；"
            "5. 把缺陷包装成创新；6. 方法论捏造；7. 早期框架过度锁定。\n"
            "如果出现 SUSPECTED，必须明确风险和需要补充的证据；如果证据不足，不要强行通过。"
        )
    if stage == "creator":
        return (
            "你现在是 Creator（文档创作者）。职责：基于 Explorer 阶段收集的材料，调用文档生成/导出工具完成产出。\n"
            f"当前项目目录：{workspace_path}\n"
            "所有工具仍然可用；优先使用最贴近目标的文档生成、导出或写入工具。\n"
            "规则：\n"
            "1. 如果材料足够，直接调用导出工具；如果材料不足，只补充读取最小必要内容。\n"
            "2. generate_ppt 需要 slides 数组（每项含 title 和 content），path 可省略（会自动生成）。\n"
            "3. export_docx / export_markdown 需要 content（Markdown 格式文本）。\n"
            "4. Word 全文翻译、生成中文版时，优先调用 document.translate_docx，不要临时写 shell 翻译脚本。\n"
            "5. PDF 转 Word / PDF 文本转存 Word 时，优先直接调用 document.extract_pdf_to_docx；用户要求保留图片、图文顺序或近似排版时，传 mode=text_with_images；只有用户需要先审阅文本时，才调用 document.extract_pdf_text_preview。\n"
            "6. 如果工具调用成功，简短确认产出路径和文件大小即可。\n"
            "7. 如果工具调用失败或只完成部分段落，说明失败原因和已完成范围，不要伪造成功结果。"
        )
    if stage == "executor":
        return (
            "你现在是 Executor（能力执行者）。职责：使用已注册能力完成真实的外部状态修改或任务动作。\n"
            f"当前项目目录：{workspace_path}\n"
            "工具是执行手段，任务契约是目标；根据实际结果调整后续动作，不要把外部状态修改误当成本地代码写入。\n"
            "执行后应使用可用的读取、检查、截图或查询能力取得验证证据；工具失败时根据真实错误换策略。"
        )
    if stage == "verifier":
        return (
            "你现在是 Verifier（验证者）。职责：写入成功后只做一次必要验证。\n"
            f"当前项目目录：{workspace_path}\n"
            "所有工具仍然可用；优先运行测试/语法检查、查看 git.status 或 git.diff。"
            "如果验证失败，可以读取必要上下文并继续修复；如果验证通过，进入总结。"
        )
    if stage == "reviewer":
        if mode == "paper":
            return (
                "你现在是 Reviewer（论文审查者）。职责重点是检查是否满足用户目标并形成最终答复。\n"
                f"当前项目目录：{workspace_path}\n"
                "阶段只是参考，不会限制工具；如果发现关键证据缺失，可以补充最小必要工具调用。\n"
                "最终答复请包含：Material Passport 简表、主要产出或结论、质量门结果、仍需用户确认的决策、建议下一步。\n"
                "必须保留证据边界：哪些来自已读材料，哪些只是推断或建议。不要声称已经核验未读取的文献或结果。"
            )
        write_rule = (
            "如果代码写入没有成功，必须明确说明本轮没有完成真实修改。"
            if mode == "coding" and code_change_intent
            else ""
        )
        return (
            "你现在是 Reviewer（审查者）。职责重点是检查任务是否满足用户目标并形成最终答复。\n"
            f"当前项目目录：{workspace_path}\n"
            "阶段只是参考，不会限制工具；如果发现关键验证或证据缺失，可以补充最小必要工具调用。"
            "最终答复请包含：已完成内容、依据/变更文件、验证情况、遗漏或剩余风险。"
            f"{write_rule}"
        )
    return ""


# ---------------------------------------------------------------------------
# Intervention / nudge prompts
# ---------------------------------------------------------------------------

def progress_observer_prompt(
    workspace_path: str,
    current_stage: str,
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
        f"Stage: {current_stage or 'none'}\n"
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
    current_stage: str,
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
        current_stage=current_stage,
        tool_events=tool_events,
    )
    return (
        "Repeated failure recovery advisory.\n"
        f"{format_tool_failure_fact_summary(facts)}\n"
        "The runtime is not choosing the next strategy. Use the facts above to "
        "decide whether to change tool, change arguments, gather smaller context, "
        "verify an existing result, ask the user, or finalize with an honest "
        "boundary. Avoid repeating the same tool with the same missing or oversized "
        "arguments when no new progress was observed."
    )


def recon_budget_prompt(budget: int, workspace_path: str) -> str:
    return (
        "Runtime observation only. Reconnaissance budget has been reached.\n"
        f"Workspace: {workspace_path}\n"
        f"Recon reads/searches observed: {budget}\n"
        "Decide whether the available evidence is enough to act, whether a "
        "different evidence source is needed, or whether the task should be "
        "finalized with an honest boundary."
    )


def write_only_stage_prompt(workspace_path: str) -> str:
    return (
        f"Target deliverable gap observation. Workspace={workspace_path}.\n"
        "The runtime has not yet observed the target deliverable for this task. "
        "Use this only as evidence, not as a forced route. Decide whether the "
        "next useful step is a smaller read/search, a write/edit/export action, "
        "verification of an existing artifact, a different tool, or an honest "
        "boundary to the user."
    )


def dangling_action_prompt(
    workspace_path: str,
    unfinished_text: str,
    tool_events: list[dict[str, Any]],
    mode: str | None,
    *,
    allow_state_change: bool = True,
) -> str:
    snippet = unfinished_text[-200:]
    capability_boundary = (
        "当前任务契约允许产生本地变更；需要执行时请选择与目标最接近的工具。"
        if allow_state_change
        else "当前任务契约没有声明本地变更；可继续读取或直接回答，不要创建或修改文件。"
    )
    return (
        f"悬空动作：项目={workspace_path}。未完成：{snippet}\n"
        f"{capability_boundary}\n"
        "请调用本地工具执行动作，或直接输出最终总结（变更文件+验证结果+风险）。"
        "不要只说'我先验证/我将检查/接下来处理'。"
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
    force_full_file_rewrite: bool = False,
) -> str:
    target = arguments.get("path") or arguments.get("output_path") or workspace_path
    error = str(event.get("error") or "")
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    reason = str(output.get("reason") or "")
    facts = build_tool_failure_fact_summary(
        workspace_path=workspace_path,
        current_stage="write_repair",
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
    code_rule = ""
    if mode == "coding":
        code_rule = (
            "如果任务涉及代码变更，只有观察到成功生成或更新任务契约中的目标产物后，才能声称已经修改完成。"
        )
    return (
        "计划执行模式已开启。上面的计划是参考路线，不是固定轨道；"
        "如工具结果、插话或文件结构显示原计划不合适，可以跳过、合并、拆分或追加步骤。"
        "计划只是运行审计和协作上下文，不是新的人工确认门。不要输出“确认/是否执行/Y/n”等文本询问；"
        "如果任务信息足够，请直接调用最合适的工具推进。运行时会负责权限、安全和确认策略。"
        "需要读取本地资料或代码时应调用本地工具；每次工具返回后继续推进下一步。"
        f"{code_rule}"
        "最终回答要说明：完成了哪些步骤、使用了哪些文件或工具、结果和未完成/不确定项。"
    )


def read_only_task_prompt(workspace_path: str) -> str:
    return (
        f"User constraint: read-only requested. Workspace={workspace_path}.\n"
        "Treat the user's no-write/no-change wording as a current-task constraint. "
        "Prefer read/search/status/diff evidence. If you judge that the user's goal "
        "cannot be completed without modifying local files or external state, explain "
        "that conflict and ask for confirmation instead of silently changing state. "
        "Do not claim changes were made unless a write/state-change tool actually ran."
    )


def analysis_first_task_prompt(workspace_path: str) -> str:
    return (
        f"分析优先任务。项目={workspace_path}。"
        "先用工具定位事实；若确需修改可直接调用写入工具。"
        "高风险操作（大范围覆盖/提交/删除）请先说明风险；普通编辑可按需推进并验证。"
    )


def post_deliverable_prompt(workspace_path: str) -> str:
    return (
        f"已有目标产物成功出现。项目={workspace_path}。"
        "现在优先调用真实验证工具，然后总结。除非验证返回了新的失败证据，或任务契约明确还有未生成的产物，"
        "不要重复执行已经成功完成的同一状态变更。代码/HTML/脚本任务优先运行可行的语法检查、构建、测试或 lint；"
        "外部应用/MCP/浏览器/数据库等非文件产物，优先调用只读查询、状态读取、截图、检查或 evidence/verification 能力取证；"
        "不要把 dir/ls/os.listdir/Get-Item 这类目录或存在性检查当作测试通过。"
        "不要把 python -m http.server、npm run dev 等长驻服务命令当作普通验证命令。"
        "如果只能读取生成文件做内容检查，最终必须说明未运行测试。"
        "最终回复须列出目标产物、验证情况和剩余风险。"
    )


def completion_review_prompt(
    workspace_path: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any],
) -> str:
    """Prompt the model to self-audit completion from runtime facts.

    This is intentionally evidence-oriented instead of file-type-specific. The
    runtime does not decide the next strategy; it exposes facts and asks the
    model to either continue with tools or finish honestly.
    """
    facts = build_run_fact_summary(
        workspace_path=workspace_path,
        tool_events=[],
        run_result=run_result,
        task_contract=task_contract,
    )
    return (
        "Completion self-review from runtime facts.\n"
        f"Current project: {workspace_path}\n"
        f"{format_run_fact_summary(facts)}\n"
        "These facts are evidence, not a forced route. Decide whether the task "
        "is actually complete. If the goal is not closed, continue with the "
        "most suitable tool, verification, or repair strategy. If it is closed, "
        "write a final answer that states what changed, what was verified, what "
        "was not verified, and any remaining risk. Do not claim completion "
        "beyond the observed deliverables and verification evidence. The runtime "
        "will record your observable choice as completion-loop evidence; this "
        "record is for audit and replay, not a hard constraint on your strategy."
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
) -> str:
    """Ask the model to write the final user-facing result from runtime facts."""
    facts = build_run_fact_summary(
        workspace_path=workspace_path,
        tool_events=[],
        run_result=run_result,
        task_contract=task_contract,
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
        f"{format_run_fact_summary(facts)}"
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
    context = _verification_retry_context(
        required_modalities=required_modalities,
        observed_modalities=observed_modalities,
        missing_modalities=missing_modalities,
        visual_verification_tool_ids=visual_verification_tool_ids,
        runtime_diagnostics=runtime_diagnostics,
    )
    if mode in {"document", "paper"}:
        return (
            "Verification evidence advisory, not a hard tool constraint.\n"
            f"Workspace: {workspace_path}\n"
            f"{context}"
            "If you plan to claim the document or paper task is complete, gather "
            "real evidence first. Prefer a read/check tool that fits the artifact: "
            "filesystem.read_file for .md/.txt, document.extract_docx_outline for "
            ".docx, document.extract_pdf_text_preview for .pdf, "
            "spreadsheet.inspect_workbook for .xlsx/.csv/.tsv, or another available "
            "tool that returns content or artifact facts. If no suitable evidence "
            "path is available, do not keep retrying blindly; summarize what is "
            "done and explicitly say what could not be verified."
        )
    return (
        "Verification evidence advisory, not a hard tool constraint.\n"
        f"Workspace: {workspace_path}\n"
        f"{context}"
        "If you plan to claim the target is complete, gather real evidence first. "
        "For external applications, MCP services, browsers, databases, or other "
        "non-file state, prefer a read-only state query, inspection, screenshot, "
        "render, capture, or any available tool that returns evidence/artifact "
        "facts. A state-changing call by itself is not verification unless it "
        "also returns meaningful evidence.\n"
        "For code, HTML, or script tasks, prefer an available shell.run_command "
        "check that matches the task. Syntax/static checks such as python -m "
        "py_compile, node --check, tsc, lint, or build commands are structural "
        "verification. For services, APIs, UI behavior, databases, or generated "
        "backends, also gather behavioral evidence such as a unit test, import/"
        "startup probe, TestClient/request/curl call, or other runtime/API check "
        "when practical. Avoid treating directory listings or long running dev "
        "servers as proof of correctness.\n"
        "If the available tools cannot provide suitable evidence, choose another "
        "safe strategy, ask the user, or finalize with an honest verification "
        "limitation instead of repeating the same failing call."
    )


def runtime_intervention_prompt(
    workspace_path: str,
    current_stage: str,
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
        plan_hint = (
            "当前计划已被标记为需要重新审视。不要机械继续旧计划；"
            "如果插话改变目标、约束、文件范围或发现原路线错误，请调整下一步。"
        )
    return (
        "运行中干预：用户在任务执行过程中追加了新信息或纠偏要求。\n"
        f"当前项目目录：{workspace_path}\n"
        f"当前阶段：{current_stage or '未锁定阶段'}\n"
        f"最近工具事件：{', '.join(recent_tools) if recent_tools else '暂无'}\n"
        f"{plan_hint}\n"
        "处理规则：\n"
        "1. 最新插话优先于此前计划、此前推理和此前未完成输出；\n"
        "2. 先重新判断用户真实意图：这是补充信息、纠正方向、要求停止某动作，还是新增约束；\n"
        "3. 如果插话与旧方案冲突，放弃旧方案中冲突部分，不要继续沿旧思路执行；\n"
        "4. 如果已有工具结果仍有用，可以复用；如果不足，请只读取最小必要上下文；\n"
          "5. 下一步应优先基于插话重新选择：继续、调整计划、补读证据、写入、验证或停止说明原因。\n"
        "不要把插话当作普通聊天补充，也不要忽略它继续执行旧路径。"
    )


def max_rounds_message(max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
    lines = [
        f"本轮已达到工具调用上限（{max_rounds} 轮），系统已停止继续执行，避免陷入重复调用。",
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
        "建议：如果这是代码或界面修改任务，请直接说明要修改的文件、关键词或期望结果；系统会继续自动识别任务类型并调用合适工具。",
    ])
    return "\n".join(lines)
