"""Runtime-owned result schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RUN_RESULT_SCHEMA_VERSION = "0.1"

ResultStatus = Literal["success", "failure", "partial", "stopped", "no_tool_activity"]

RESULT_STATUSES: frozenset[str] = frozenset(ResultStatus.__args__)  # type: ignore[attr-defined]

RISK_CODES: frozenset[str] = frozenset({
    "expected_write_not_observed",
    "write_not_verified",
    "test_not_observed",
    "partial_write_failure",
    "partial_write_resumable",
    "execution_contract_failed",
    "max_rounds_exceeded",
    "recovered_tool_failure",
    "document_output_coverage_low",
    "invalid_verification_method",
    "runtime_verification_not_observed",
})


@dataclass(frozen=True)
class RuntimeResult:
    status: ResultStatus
    counts: dict[str, int] = field(default_factory=dict)
    changed_paths: tuple[str, ...] = field(default_factory=tuple)
    written_paths: tuple[str, ...] = field(default_factory=tuple)
    verified: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    failures: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    flags: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_RESULT_SCHEMA_VERSION,
            "kind": "run_result",
            "status": self.status,
            "counts": dict(self.counts),
            "changed_paths": list(self.changed_paths),
            "written_paths": list(self.written_paths),
            "verified": [dict(item) for item in self.verified],
            "failures": [dict(item) for item in self.failures],
            "risks": list(self.risks),
            "flags": dict(self.flags),
        }


def is_result_status(value: str) -> bool:
    return str(value or "") in RESULT_STATUSES
