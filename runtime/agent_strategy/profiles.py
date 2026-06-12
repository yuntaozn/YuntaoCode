"""Agent profiles and stage presets.

Profiles are internal execution personalities.  The UI can stay unified while
the runtime routes each request through a small, explicit profile contract.
Adding a new assistant family should start here instead of adding more
mode-specific branches to the conversation runner.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    id: str
    label: str
    execution_mode: str
    description: str


CHAT_PROFILE = AgentProfile(
    id="chat",
    label="Direct Chat",
    execution_mode="terminal",
    description="Short answers, greetings, and simple explanations without planning or tools by default.",
)
ANALYSIS_PROFILE = AgentProfile(
    id="analysis",
    label="Local Analysis",
    execution_mode="terminal",
    description="Read-only inspection and project/document analysis that may use tools when evidence is needed.",
)
CODING_PROFILE = AgentProfile(
    id="coding",
    label="Code Execution",
    execution_mode="coding",
    description="Code edits, repairs, verification, and local project changes.",
)
DOCUMENT_PROFILE = AgentProfile(
    id="document",
    label="Document Workflow",
    execution_mode="document",
    description="Document export, conversion, summarization, and file-oriented deliverables.",
)
EXECUTION_PROFILE = AgentProfile(
    id="execution",
    label="Capability Execution",
    execution_mode="terminal",
    description="External application, MCP, browser, database, and other capability-driven state changes.",
)
PAPER_PROFILE = AgentProfile(
    id="paper",
    label="Paper Workflow",
    execution_mode="paper",
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
        return CHAT_PROFILE
    if mode == "paper":
        return PAPER_PROFILE
    if mode == "document":
        return DOCUMENT_PROFILE
    if mode == "coding":
        return CODING_PROFILE
    return ANALYSIS_PROFILE


def stage_sequence_for_profile(
    profile_id: str | None,
    *,
    task_intent: str = "",
    code_change_intent: bool = False,
) -> list[str]:
    profile = get_profile(profile_id)
    if profile.id == "coding" or code_change_intent:
        return ["explorer", "editor", "verifier", "reviewer"]
    if profile.id == "execution":
        return ["explorer", "executor", "verifier", "reviewer"]
    if profile.id == "paper":
        if task_intent == "read_only_analysis":
            return ["explorer", "reviewer"]
        return ["explorer", "writer", "integrity_gate", "reviewer"]
    if profile.id == "document":
        if task_intent == "document_export":
            return ["explorer", "creator", "verifier", "reviewer"]
        return ["explorer", "reviewer"]
    return ["explorer", "reviewer"]


def round_limit_for_profile(
    profile_id: str | None,
    stage: str,
    *,
    code_change_intent: bool = False,
) -> int:
    profile = get_profile(profile_id)
    if stage == "explorer":
        if profile.id == "coding" or code_change_intent:
            return 5
        if profile.id == "paper":
            return 5
        if profile.id == "document":
            return 4
        return 5
    if stage in {"editor", "creator", "executor"}:
        return 5
    if stage == "writer":
        return 3
    if stage == "integrity_gate":
        return 1
    if stage == "verifier":
        return 2
    return 1


def profile_to_public_dict(profile: AgentProfile) -> dict[str, str]:
    return {
        "id": profile.id,
        "label": profile.label,
        "execution_mode": profile.execution_mode,
        "description": profile.description,
    }
