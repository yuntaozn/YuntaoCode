"""Skill evolution schemas.

These records describe how completed task experience can become reusable
skills through Runbook evidence and Replay verification. They are data
contracts only; they do not generate code, register plugins, or execute tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal


SKILL_CANDIDATE_SCHEMA_VERSION = "skill_candidate.v1"
REPLAY_FIXTURE_SCHEMA_VERSION = "replay_fixture.v1"
SKILL_REPLAY_RESULT_SCHEMA_VERSION = "skill_replay_result.v1"
SKILL_PROMOTION_SCHEMA_VERSION = "skill_promotion.v1"

SkillCandidateState = Literal[
    "draft",
    "testing",
    "tested",
    "enabled",
    "disabled",
    "rejected",
    "archived",
]

ReplayResultStatus = Literal[
    "passed",
    "failed",
    "partial",
    "blocked",
]

SKILL_CANDIDATE_STATES: frozenset[str] = frozenset(SkillCandidateState.__args__)  # type: ignore[attr-defined]
REPLAY_RESULT_STATUSES: frozenset[str] = frozenset(ReplayResultStatus.__args__)  # type: ignore[attr-defined]

SKILL_CANDIDATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"testing", "rejected", "archived"}),
    "testing": frozenset({"tested", "draft", "rejected", "archived"}),
    "tested": frozenset({"enabled", "disabled", "testing", "rejected", "archived"}),
    "enabled": frozenset({"disabled", "testing", "archived"}),
    "disabled": frozenset({"enabled", "testing", "archived"}),
    "rejected": frozenset({"archived"}),
    "archived": frozenset(),
}


@dataclass(frozen=True)
class SkillCandidate:
    """A reusable skill draft inferred from one or more completed tasks."""

    id: str
    name: str
    description: str = ""
    state: SkillCandidateState = "draft"
    source_runbook_ids: tuple[str, ...] = field(default_factory=tuple)
    fixture_ids: tuple[str, ...] = field(default_factory=tuple)
    capability_ids: tuple[str, ...] = field(default_factory=tuple)
    draft_manifest: dict[str, Any] = field(default_factory=dict)
    boundaries: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SKILL_CANDIDATE_SCHEMA_VERSION,
            "record_kind": "skill_candidate",
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "state": self.state,
            "source_runbook_ids": list(self.source_runbook_ids),
            "fixture_ids": list(self.fixture_ids),
            "capability_ids": list(self.capability_ids),
            "draft_manifest": dict(self.draft_manifest),
            "boundaries": dict(self.boundaries),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    def transition(self, target: SkillCandidateState) -> "SkillCandidate":
        if not can_transition(self.state, target):
            raise ValueError(f"invalid skill candidate transition: {self.state} -> {target}")
        return replace(self, state=target)


@dataclass(frozen=True)
class ReplayFixture:
    """A stable task sample used to test a SkillCandidate."""

    id: str
    source_run_id: str
    runbook_id: str = ""
    task_id: str = ""
    workspace_id: str = ""
    conversation_id: str = ""
    goal: str = ""
    task_contract: dict[str, Any] = field(default_factory=dict)
    expected_artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    verification_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REPLAY_FIXTURE_SCHEMA_VERSION,
            "record_kind": "replay_fixture",
            "id": self.id,
            "source_run_id": self.source_run_id,
            "runbook_id": self.runbook_id,
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "goal": self.goal,
            "task_contract": dict(self.task_contract),
            "expected_artifacts": [dict(item) for item in self.expected_artifacts],
            "verification_evidence": [dict(item) for item in self.verification_evidence],
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SkillReplayResult:
    """Result of replaying one fixture against one candidate."""

    id: str
    candidate_id: str
    fixture_id: str
    run_id: str = ""
    status: ReplayResultStatus = "blocked"
    score: float = 0.0
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    failures: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SKILL_REPLAY_RESULT_SCHEMA_VERSION,
            "record_kind": "skill_replay_result",
            "id": self.id,
            "candidate_id": self.candidate_id,
            "fixture_id": self.fixture_id,
            "run_id": self.run_id,
            "status": self.status,
            "score": max(0.0, min(1.0, float(self.score))),
            "evidence": [dict(item) for item in self.evidence],
            "failures": [dict(item) for item in self.failures],
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SkillPromotion:
    """Manual decision to make a tested candidate available as a skill."""

    id: str
    candidate_id: str
    target: str = "user_skill"
    approved_by: str = "user"
    state: str = "proposed"
    replay_result_ids: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SKILL_PROMOTION_SCHEMA_VERSION,
            "record_kind": "skill_promotion",
            "id": self.id,
            "candidate_id": self.candidate_id,
            "target": self.target,
            "approved_by": self.approved_by,
            "state": self.state,
            "replay_result_ids": list(self.replay_result_ids),
            "notes": self.notes,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


def can_transition(current: str, target: str) -> bool:
    if current not in SKILL_CANDIDATE_STATES or target not in SKILL_CANDIDATE_STATES:
        return False
    return target in SKILL_CANDIDATE_TRANSITIONS[current]


def replay_fixture_from_runbook(fixture_id: str, runbook: dict[str, Any]) -> ReplayFixture:
    run = runbook.get("run") if isinstance(runbook.get("run"), dict) else {}
    result = runbook.get("result") if isinstance(runbook.get("result"), dict) else {}
    return ReplayFixture(
        id=fixture_id,
        source_run_id=str(run.get("id") or runbook.get("source_run_id") or ""),
        runbook_id=str(runbook.get("id") or ""),
        task_id=str(run.get("task_id") or ""),
        workspace_id=str(run.get("workspace_id") or ""),
        conversation_id=str(run.get("conversation_id") or ""),
        goal=str(run.get("goal") or ""),
        task_contract=dict(runbook.get("task_contract") or {}),
        expected_artifacts=tuple(_dict_items(result.get("artifacts"))),
        verification_evidence=tuple(_dict_items(runbook.get("verification_evidence"))),
    )


def skill_readiness(candidate: SkillCandidate, results: list[SkillReplayResult]) -> dict[str, Any]:
    relevant = [item for item in results if item.candidate_id == candidate.id]
    passed = [item for item in relevant if item.status == "passed"]
    failed = [item for item in relevant if item.status == "failed"]
    partial = [item for item in relevant if item.status == "partial"]
    blocked = [item for item in relevant if item.status == "blocked"]
    average_score = sum(max(0.0, min(1.0, item.score)) for item in relevant) / len(relevant) if relevant else 0.0
    promotable = candidate.state == "tested" and bool(passed) and not failed and not blocked
    return {
        "candidate_id": candidate.id,
        "candidate_state": candidate.state,
        "fixture_count": len(relevant),
        "passed": len(passed),
        "failed": len(failed),
        "partial": len(partial),
        "blocked": len(blocked),
        "average_score": round(average_score, 4),
        "promotable": promotable,
        "boundary": "manual_enable_required",
    }


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
