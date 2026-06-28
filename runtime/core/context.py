"""Context runtime schemas.

Context records describe what the model may rely on, where it came from, and
how trustworthy it is. They are not tied to one prompt format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CONTEXT_RECORD_SCHEMA_VERSION = "context_record.v1"
CONTEXT_SNAPSHOT_SCHEMA_VERSION = "context_snapshot.v1"
EVIDENCE_RECORD_SCHEMA_VERSION = "evidence_record.v1"

ContextKind = Literal[
    "user_intent",
    "task_contract",
    "workspace_summary",
    "capability",
    "evidence",
    "tool_result",
    "memory",
    "recovery",
    "risk",
]

TrustLevel = Literal[
    "user_provided",
    "tool_verified",
    "runtime_fact",
    "summary",
    "memory",
    "model_inferred",
    "unverified",
]

PHASE_CONTEXT_KINDS: dict[str, frozenset[str]] = {
    "understanding": frozenset({"user_intent", "memory", "task_contract", "risk"}),
    "task_contract": frozenset({"user_intent", "workspace_summary", "task_contract", "memory", "recovery", "risk"}),
    "planning": frozenset({"user_intent", "task_contract", "workspace_summary", "capability", "memory", "risk"}),
    "execution": frozenset({"task_contract", "capability", "evidence", "tool_result", "recovery", "risk"}),
    "verification": frozenset({"task_contract", "capability", "evidence", "tool_result", "risk"}),
    "summary": frozenset({"user_intent", "task_contract", "tool_result", "evidence", "recovery", "risk"}),
}


@dataclass(frozen=True)
class ContextRecord:
    kind: ContextKind
    content: str
    source_id: str = ""
    source_type: str = ""
    trust: TrustLevel = "unverified"
    task_id: str = ""
    freshness: str = "unknown"
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTEXT_RECORD_SCHEMA_VERSION,
            "kind": self.kind,
            "content": self.content,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "trust": self.trust,
            "task_id": self.task_id,
            "freshness": self.freshness,
            "token_estimate": self.token_estimate,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceRecord:
    source_id: str
    summary: str
    kind: str = "file"
    path: str = ""
    ranges: tuple[str, ...] = field(default_factory=tuple)
    content_hash: str = ""
    last_read_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_RECORD_SCHEMA_VERSION,
            "source_id": self.source_id,
            "kind": self.kind,
            "path": self.path,
            "summary": self.summary,
            "ranges": list(self.ranges),
            "content_hash": self.content_hash,
            "last_read_at": self.last_read_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ContextSnapshot:
    task_id: str
    phase: str
    records: tuple[ContextRecord, ...] = field(default_factory=tuple)
    evidence: tuple[EvidenceRecord, ...] = field(default_factory=tuple)
    unresolved: tuple[str, ...] = field(default_factory=tuple)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTEXT_SNAPSHOT_SCHEMA_VERSION,
            "task_id": self.task_id,
            "phase": self.phase,
            "summary": self.summary,
            "records": [record.to_dict() for record in self.records],
            "evidence": [item.to_dict() for item in self.evidence],
            "unresolved": list(self.unresolved),
            "metadata": dict(self.metadata),
        }


def select_records_for_phase(
    records: list[ContextRecord] | tuple[ContextRecord, ...],
    phase: str,
    *,
    limit: int = 12,
) -> tuple[ContextRecord, ...]:
    allowed = PHASE_CONTEXT_KINDS.get(str(phase or ""), frozenset())
    if not allowed:
        return tuple(records[:limit])
    selected = [record for record in records if record.kind in allowed]
    return tuple(selected[:limit])
