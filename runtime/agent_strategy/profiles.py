"""描述模型所决定任务契约的 Agent Profile。

Profile 是内部执行人格。UI 可保持统一，同时由任务契约模型选择一段小型明确的
Profile 描述。Profile 不向执行施加固定阶段、工具路线或轮次预算。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    id: str
    label: str
    description: str


CHAT_PROFILE = AgentProfile(
    id="chat",
    label="Direct Chat",
    description="Short answers, greetings, and simple explanations without planning or tools by default.",
)
ANALYSIS_PROFILE = AgentProfile(
    id="analysis",
    label="Local Analysis",
    description="Read-only inspection and project/document analysis that may use tools when evidence is needed.",
)
CODING_PROFILE = AgentProfile(
    id="coding",
    label="Code Execution",
    description="Code edits, repairs, verification, and local project changes.",
)
DOCUMENT_PROFILE = AgentProfile(
    id="document",
    label="Document Workflow",
    description="Document export, conversion, summarization, and file-oriented deliverables.",
)
EXECUTION_PROFILE = AgentProfile(
    id="execution",
    label="Capability Execution",
    description="External application, MCP, browser, database, and other capability-driven state changes.",
)
PAPER_PROFILE = AgentProfile(
    id="paper",
    label="Paper Workflow",
    description="Academic writing, literature review, citation-risk checks, and research workflows.",
)


PROFILES: dict[str, AgentProfile] = {
    profile.id: profile
    for profile in (
        CHAT_PROFILE,
        ANALYSIS_PROFILE,
        CODING_PROFILE,
        EXECUTION_PROFILE,
        DOCUMENT_PROFILE,
        PAPER_PROFILE,
    )
}


def get_profile(profile_id: str | None) -> AgentProfile:
    return PROFILES.get(str(profile_id or ""), ANALYSIS_PROFILE)


def profile_for_task_intent(
    task_intent: str,
    mode: str | None,
    *,
    code_change_intent: bool = False,
    state_change_intent: bool = False,
    first_action: str | None = None,
) -> AgentProfile:
    """根据模型声明的任务契约解析内部 Profile。

    为兼容旧调用点仍接受 ``mode``，但它不得为原本中性的任务进行路由。统一终端
    让任务语义留在模型契约中，不恢复旧版用户可见助手模式。"""
    _ = mode
    if task_intent == "document_export":
        return DOCUMENT_PROFILE
    if task_intent == "paper_workflow":
        return PAPER_PROFILE
    if code_change_intent:
        return CODING_PROFILE
    if state_change_intent:
        return EXECUTION_PROFILE
    if task_intent == "write_required":
        return CODING_PROFILE
    if task_intent == "answer_only":
        if str(first_action or "").strip() in {"read", "search", "use_tool", "verify"}:
            return ANALYSIS_PROFILE
        return CHAT_PROFILE
    return ANALYSIS_PROFILE


def profile_to_public_dict(profile: AgentProfile) -> dict[str, str]:
    return {
        "id": profile.id,
        "label": profile.label,
        "description": profile.description,
    }
