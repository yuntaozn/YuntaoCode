"""Experience-layer schemas.

Experience records sit between raw Runbook evidence and Skill Evolution. They
capture what a task taught the runtime without implying that a reusable skill
already exists or should be promoted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EXPERIENCE_SAMPLE_SCHEMA_VERSION = "experience_sample.v1"
EXPERIENCE_DIGEST_SCHEMA_VERSION = "experience_digest.v1"

ExperienceOutcome = Literal["success", "partial", "failure", "stopped", "unknown"]

EXPERIENCE_OUTCOMES: frozenset[str] = frozenset(ExperienceOutcome.__args__)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class ExperienceSample:
    """A compact, portable task experience extracted from one Runbook."""

    id: str
    source_run_id: str
    task_id: str = ""
    workspace_id: str = ""
    conversation_id: str = ""
    goal: str = ""
    outcome: ExperienceOutcome = "unknown"
    task_contract: dict[str, Any] = field(default_factory=dict)
    run_result: dict[str, Any] = field(default_factory=dict)
    verification_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXPERIENCE_SAMPLE_SCHEMA_VERSION,
            "record_kind": "experience_sample",
            "id": self.id,
            "source_run_id": self.source_run_id,
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "goal": self.goal,
            "outcome": self.outcome,
            "task_contract": dict(self.task_contract),
            "run_result": dict(self.run_result),
            "verification_evidence": [dict(item) for item in self.verification_evidence],
            "risks": list(self.risks),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExperienceDigest:
    """A reviewed summary extracted from one or more ExperienceSamples."""

    id: str
    sample_ids: tuple[str, ...] = field(default_factory=tuple)
    pattern_name: str = ""
    summary: str = ""
    applicability: tuple[str, ...] = field(default_factory=tuple)
    capability_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_requirements: tuple[str, ...] = field(default_factory=tuple)
    failure_modes: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXPERIENCE_DIGEST_SCHEMA_VERSION,
            "record_kind": "experience_digest",
            "id": self.id,
            "sample_ids": list(self.sample_ids),
            "pattern_name": self.pattern_name,
            "summary": self.summary,
            "applicability": list(self.applicability),
            "capability_ids": list(self.capability_ids),
            "evidence_requirements": list(self.evidence_requirements),
            "failure_modes": list(self.failure_modes),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


def experience_sample_from_runbook(sample_id: str, runbook: dict[str, Any]) -> ExperienceSample:
    run = runbook.get("run") if isinstance(runbook.get("run"), dict) else {}
    result = runbook.get("result") if isinstance(runbook.get("result"), dict) else {}
    outcome = _normalize_outcome(result.get("status") or run.get("status"))
    return ExperienceSample(
        id=sample_id,
        source_run_id=str(run.get("id") or runbook.get("source_run_id") or ""),
        task_id=str(run.get("task_id") or ""),
        workspace_id=str(run.get("workspace_id") or ""),
        conversation_id=str(run.get("conversation_id") or ""),
        goal=str(run.get("goal") or ""),
        outcome=outcome,
        task_contract=dict(runbook.get("task_contract") or {}),
        run_result=dict(result),
        verification_evidence=tuple(_dict_items(runbook.get("verification_evidence"))),
        risks=tuple(str(item) for item in runbook.get("risks") or [] if str(item)),
        created_at=str(run.get("updated_at") or run.get("created_at") or ""),
    )


def _normalize_outcome(value: Any) -> ExperienceOutcome:
    status = str(value or "").strip().lower()
    if status in EXPERIENCE_OUTCOMES:
        return status  # type: ignore[return-value]
    return "unknown"


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
