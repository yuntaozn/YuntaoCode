"""Runtime-owned result schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RUN_RESULT_SCHEMA_VERSION = "0.1"

ResultStatus = Literal["success", "failure", "partial", "stopped", "no_tool_activity"]

RESULT_STATUSES: frozenset[str] = frozenset(ResultStatus.__args__)  # type: ignore[attr-defined]

RISK_CODES: frozenset[str] = frozenset({
    "expected_write_not_observed",
    "target_deliverable_not_observed",
    "write_not_verified",
    "deliverable_not_verified",
    "test_not_observed",
    "partial_write_failure",
    "partial_write_resumable",
    "deliverable_path_hint_changed",
    "execution_contract_failed",
    "max_rounds_exceeded",
    "repeated_tool_failure",
    "capability_preflight_advisory",
    "model_provider_error",
    "invalid_tool_call_protocol",
    "invalid_final_answer",
    "model_output_truncated",
    "recovered_tool_failure",
    "incidental_tool_failure",
    "degraded_verification_failure",
    "required_verification_not_satisfied",
    "verification_evidence_weak",
    "document_output_coverage_low",
    "document_output_too_short",
    "document_output_length_unknown",
    "answer_output_too_short",
    "answer_output_length_unknown",
    "optional_write_not_verified",
    "invalid_verification_method",
    "runtime_verification_not_observed",
    "artifact_integrity_invalid",
    "shell_stderr_warning",
})


@dataclass(frozen=True)
class RuntimeResult:
    status: ResultStatus
    counts: dict[str, int] = field(default_factory=dict)
    changed_paths: tuple[str, ...] = field(default_factory=tuple)
    written_paths: tuple[str, ...] = field(default_factory=tuple)
    verified: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    verification_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    required_verification_strength: str = "none"
    capability_advisories: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    failures: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    failure_details: tuple[dict[str, Any], ...] = field(default_factory=tuple)
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
            "verification_evidence": [dict(item) for item in self.verification_evidence],
            "required_verification_strength": self.required_verification_strength,
            "capability_advisories": [dict(item) for item in self.capability_advisories],
            "failures": [dict(item) for item in self.failures],
            "failure_details": [dict(item) for item in self.failure_details],
            "risks": list(self.risks),
            "flags": dict(self.flags),
        }


def is_result_status(value: str) -> bool:
    return str(value or "") in RESULT_STATUSES
