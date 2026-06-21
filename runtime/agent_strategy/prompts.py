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
            "3. 如果写入失败（如 old_text not found），应重新读取文件对应位置，基于真实内容换一种可靠写入策略，不要凭记忆猜测。\n"
            "4. 不要伪造修改结果，不要声称已完成但未实际调用写入工具。"
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
) -> str:
    action_rule = ""
    if code_change_intent and not has_successful_write(tool_events):
        action_rule = (
            "需要真实修改文件但尚未写入。可优先调用 code.edit_file / code.replace_text，"
            "若需要完整生成较大文本/代码文件，可使用 filesystem.create_text_draft / append_text_chunk / finalize_text_file，"
            "或只读取一个最小必要文件后写入。"
        )
    return (
        f"进度纠偏（{reason}）：项目={workspace_path}，阶段={current_stage or '无'}。"
        f"{action_rule}"
        "所有工具仍可用，请根据最新上下文推进。"
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
    reason_line = f"失败类型：{reason}\n" if reason else ""
    write_status = (
        "本轮已经观察到成功写入；除非有新证据表明产物错误，不要继续重复写入，应优先验证或如实总结。"
        if has_successful_write(tool_events)
        else "本轮尚未观察到成功写入；如任务要求产物，请先获得真实目标路径和内容后再写入。"
    )
    text_write_recovery = ""
    if tool_id in {
        "filesystem.write_file",
        "filesystem.create_text_draft",
        "filesystem.append_text_chunk",
        "filesystem.finalize_text_file",
    } and (
        reason == "truncated_tool_call"
        or "output limit" in error.lower()
        or "incomplete arguments" in error.lower()
    ):
        text_write_recovery = (
            "\n这不是目标失败，而是当前写入负载过大或参数未完整生成。"
            "如果仍需生成较大的文本/代码产物，可以考虑换成小步执行："
            "先用 filesystem.create_text_draft 创建空草稿（只给 title/path_hint/language），"
            "再用 filesystem.append_text_chunk 分多次追加完整且有边界的片段，"
            "必要时 inspect，最后用 filesystem.finalize_text_file 写入目标文件。"
            "如果只是局部修改，也可以读取目标片段后使用精确编辑；"
            "如果证据显示不应继续写入，请如实说明阻碍，不要重复同一个超大工具调用。"
        )
    return (
        "策略切换建议：完全相同的工具失败已经连续发生多次，原策略没有产生新进展。\n"
        f"当前项目：{workspace_path}\n"
        f"当前阶段：{current_stage or '无'}\n"
        f"重复失败工具：{tool_id}\n"
        f"最近失败原因：{error}\n"
        f"{reason_line}"
        f"{write_status}\n"
        f"{text_write_recovery}\n"
        "请重新判断任务目标与已有证据，下一步应采用实质不同的策略，避免再次发送相同工具和相同参数。"
        "可选方向包括：补全真实参数、读取最小必要上下文、改用更合适的工具、转入验证，"
        "或在确实无法继续时如实说明阻碍并结束。由你根据当前任务选择最合适的一项。"
    )


def recon_budget_prompt(budget: int, workspace_path: str) -> str:
    return (
        f"侦察预算已用完（{budget} 次读取/搜索）。项目={workspace_path}。"
        "当前证据提示应停止泛泛侦察并推进任务：可读取最小必要片段后调用 code.edit_file / code.replace_text；"
        "若是较大完整文件生成，可改用 filesystem.create_text_draft / append_text_chunk / finalize_text_file，"
        "或明确说明缺少什么信息导致无法修改。不要用文字声称已修改。"
    )


def write_only_stage_prompt(workspace_path: str) -> str:
    return (
        f"执行压力阶段：项目={workspace_path}。"
        "读取应服务于写入目标（说明要确认哪个文件/位置/old_text）。"
        "上下文足够时优先调用写入工具；不够时只读取最小必要片段。"
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
    reason_line = f"失败类型：{reason}\n" if reason else ""
    missing_path_rule = ""
    if "path is required" in error.lower():
        missing_path_rule = (
            "\n本次失败是因为写入工具缺少 path 参数。下一轮应先确定要写入的文件路径，"
            "然后调用 filesystem.write_file 时同时提供 path 和 content。"
            "如果内容较长，请改用 filesystem.create_text_draft / append_text_chunk / finalize_text_file。"
            "如果是修改已有文件，优先读取目标文件后用 code.edit_file 或 code.replace_text；"
            "如果是创建新文件，path 必须是当前项目内的明确相对路径或绝对路径。"
        )
    full_rewrite_rule = ""
    if force_full_file_rewrite:
        full_rewrite_rule = (
            "\n系统已检测到精确编辑连续失败。建议优先暂避 code.edit_file，避免重复同一路径。"
            "请先用 filesystem.read_file 读取目标文件当前内容；小文件可调用 filesystem.write_file 写回完整内容，"
            "较大文件可改用 filesystem.create_text_draft / append_text_chunk / finalize_text_file。"
            "写回内容必须基于刚读取到的真实文件，只修改用户要求的部分。"
        )
    truncated_rule = ""
    if (
        reason == "truncated_tool_call"
        or "output limit" in error.lower()
        or "incomplete arguments" in error.lower()
    ):
        truncated_rule = (
            "\n本次失败是因为模型在构造工具参数时达到输出上限，运行时没有执行不完整参数。"
            "请不要重复同样的大参数写入。若目标是较大的完整文本/代码文件，"
            "可改用文本草稿路线：filesystem.create_text_draft 创建空草稿，"
            "然后 filesystem.append_text_chunk 追加多个较小且完整的片段，"
            "必要时 filesystem.inspect_text_draft 检查进度，最后 filesystem.finalize_text_file 写入。"
            "如果只是小范围修改，则读取目标片段后使用 code.edit_file / code.replace_text。"
            "如果当前证据说明不该继续修改，也可以停止写入并解释真实阻碍。"
        )
    return (
        "写入修复模式：刚才的写入工具调用失败，不能用文字声称已经修改完成。\n"
        f"当前项目目录：{workspace_path}\n"
        f"失败工具：{tool_id}\n"
        f"目标路径：{target}\n"
        f"失败原因：{error}\n"
        f"{reason_line}"
        "下一步请只做必要的修复：\n"
        "1. 如果是 old_text 未匹配或不唯一，先用 filesystem.read_file 读取目标文件相关片段；\n"
        "2. 基于实际文件内容重新调用 code.edit_file 或 code.replace_text；\n"
        "3. 如果目标文件结构变化太大，小文件可使用 filesystem.write_file；较大文件建议使用 filesystem.create_text_draft / append_text_chunk / finalize_text_file；\n"
        "4. 写入成功后再进入验证，不要继续泛泛搜索。"
        f"{missing_path_rule}"
        f"{full_rewrite_rule}"
        f"{truncated_rule}"
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
        "execution strategy yourself, but do not repeat one huge tool call. For "
        "large complete text or code artifacts, create an empty text draft first, "
        "append smaller complete chunks, inspect progress when useful, and then "
        "finalize the draft to the target file. For small targeted edits, read "
        "the relevant file section and use a precise edit tool."
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
            "如果任务涉及代码变更，只有观察到成功生成或更新任务契约中的目标产物后，才能声称已经修改完成；"
            "可按产物形态选择 code.edit_file、code.replace_text、filesystem.write_file 或 filesystem.finalize_text_file。"
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
        f"只读模式。项目={workspace_path}。"
        "严禁修改/创建/删除文件或运行改变状态的命令。可用扫描/搜索/读取/git status/diff 收集证据。"
        "回答给出事实、问题判断和建议；不要声称已修改。"
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
    contract = task_contract if isinstance(task_contract, dict) else {}
    goal = str(contract.get("goal") or "").strip() or "(未声明)"
    counts = run_result.get("counts") if isinstance(run_result.get("counts"), dict) else {}
    paths = [
        str(item)
        for item in (
            run_result.get("target_written_paths")
            or run_result.get("written_paths")
            or run_result.get("changed_paths")
            or []
        )
        if str(item or "").strip()
    ]
    verified = run_result.get("verification_evidence")
    if not isinstance(verified, list):
        verified = []
    failures = run_result.get("failures")
    if not isinstance(failures, list):
        failures = []
    risks = [
        str(item)
        for item in run_result.get("risks", [])
        if str(item or "").strip()
    ]
    path_text = ", ".join(paths[:8]) if paths else "无"
    verification_text = "; ".join(
        f"{item.get('tool') or 'unknown'}:{','.join(item.get('modalities') or []) or 'unknown'}"
        for item in verified[:6]
        if isinstance(item, dict)
    ) or "无"
    failure_text = "; ".join(
        f"{item.get('tool') or 'unknown'}: {item.get('error') or ''}".strip()
        for item in failures[:6]
        if isinstance(item, dict)
    ) or "无"
    risk_text = ", ".join(risks[:12]) if risks else "无"
    return (
        "完成度自审：系统已经观察到目标产物或验证证据，但这不是终止命令。\n"
        f"当前项目：{workspace_path}\n"
        f"任务目标：{goal}\n"
        f"当前运行状态：{run_result.get('status') or 'unknown'}\n"
        f"写入/变更产物：{path_text}\n"
        f"验证证据：{verification_text}\n"
        f"失败记录：{failure_text}\n"
        f"风险标记：{risk_text}\n"
        f"计数：deliverables={counts.get('deliverable_successes', 0)}, "
        f"verifications={counts.get('verification_successes', 0)}, "
        f"failures={counts.get('failures', 0)}\n"
        "请基于这些事实自己判断任务是否真正完整完成。"
        "如果产物存在依赖、配套文件、引用资源、外部状态、内容长度、视觉效果、运行效果或用户目标仍未闭合，"
        "继续调用最合适的工具修正或补证据；不要只给口头说明。"
        "如果你判断已经完整完成，可以直接输出最终总结，必须说明依据、验证方式和仍未验证的边界。"
    )


def final_answer_prompt(workspace_path: str) -> str:
    return (
        f"收束阶段：不再调用工具。项目={workspace_path}。"
        "简洁总结：1.变更文件 2.验证结果 3.剩余风险。"
    )


def verifier_retry_prompt(mode: str | None, workspace_path: str) -> str:
    if mode in {"document", "paper"}:
        return (
            "Verification evidence advisory, not a hard tool constraint.\n"
            f"Workspace: {workspace_path}\n"
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
        "If you plan to claim the target is complete, gather real evidence first. "
        "For external applications, MCP services, browsers, databases, or other "
        "non-file state, prefer a read-only state query, inspection, screenshot, "
        "render, capture, or any available tool that returns evidence/artifact "
        "facts. A state-changing call by itself is not verification unless it "
        "also returns meaningful evidence.\n"
        "For code, HTML, or script tasks, prefer an available shell.run_command "
        "syntax/build/test/lint check such as pytest, python -m py_compile, "
        "node --check, or npm test/build when appropriate. Avoid treating "
        "directory listings or long running dev servers as proof of correctness.\n"
        "If the available tools cannot provide suitable evidence, choose another "
        "safe strategy, ask the user, or finalize with an honest verification "
        "limitation instead of repeating the same failing call."
    )


def tool_contract_correction_prompt(workspace_path: str, write_only: bool = False) -> str:
    if write_only:
        return (
            f"执行契约（压力模式）：项目={workspace_path}。"
            "读取最小上下文后立即生成或更新目标产物；较小改动可用 code.edit_file / code.replace_text，"
            "较大完整文件可用 filesystem.finalize_text_file，或说明缺少什么导致无法完成。不要用文字声称已修改。"
        )
    return (
        f"执行契约：项目={workspace_path}。你还没有成功生成或更新任务目标产物。"
        "请先用 filesystem.read_file 定位必要内容，再按产物形态选择 code.edit_file / code.replace_text；较大完整文件使用 filesystem 文本草稿工具最终写入。"
        "无法修改时必须说明原因。"
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
