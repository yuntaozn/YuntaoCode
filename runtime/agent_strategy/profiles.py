"""Agent profiles used to describe model-decided task contracts.

Profiles are internal execution personalities.  The UI can stay unified while
the task-contract model selects a small, explicit profile description. Profiles
do not impose stage sequences, tool routes, or round budgets on execution.
"""

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
    """Resolve the internal profile for a classified task intent."""
    if task_intent == "document_export":
        return DOCUMENT_PROFILE
    if task_intent == "paper_workflow":
        return PAPER_PROFILE
    if code_change_intent:
        return CODING_PROFILE
    if state_change_intent:
        return EXECUTION_PROFILE
    if task_intent == "write_required":
        if mode == "paper":
            return PAPER_PROFILE
        return CODING_PROFILE
    if task_intent == "answer_only":
        if str(first_action or "").strip() in {"read", "search", "use_tool", "verify"}:
            return ANALYSIS_PROFILE
        return CHAT_PROFILE
    if mode == "paper":
        return PAPER_PROFILE
    if mode == "document":
        return DOCUMENT_PROFILE
    if mode == "coding":
        return CODING_PROFILE
    return ANALYSIS_PROFILE


def profile_to_public_dict(profile: AgentProfile) -> dict[str, str]:
    return {
        "id": profile.id,
        "label": profile.label,
        "description": profile.description,
    }
