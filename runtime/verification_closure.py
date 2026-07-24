"""Run-level verification closure evidence.

The closure record gathers verification, artifact, visual, and debug facts into
one model-facing evidence package. It does not choose a strategy, block a tool,
or decide whether a task is complete.
"""

from __future__ import annotations

from typing import Any


VERIFICATION_CLOSURE_SCHEMA_VERSION = "verification_closure.v1"

_GAP_RISKS = {
    "deliverable_not_verified",
    "write_not_verified",
    "required_verification_not_satisfied",
    "verification_modality_missing",
    "verification_evidence_weak",
    "visual_verification_not_observed",
    "runtime_verification_not_observed",
    "test_not_observed",
    "invalid_verification_method",
    "degraded_verification_failure",
    "optional_write_not_verified",
}


def build_verification_closure(
    *,
    result_status: str = "",
    required_strength: str = "",
    required_modalities: list[str] | tuple[str, ...] | None = None,
    observed_modalities: list[str] | tuple[str, ...] | None = None,
    missing_modalities: list[str] | tuple[str, ...] | None = None,
    verification_evidence: list[dict[str, Any]] | None = None,
    visual_verification: dict[str, Any] | None = None,
    debug_audit: dict[str, Any] | None = None,
    run_artifacts: list[dict[str, Any]] | None = None,
    artifact_summary: dict[str, Any] | None = None,
    risks: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build an evidence-only verification closure summary."""

    required = _unique(required_modalities)
    observed = _unique(observed_modalities)
    missing = _unique(missing_modalities)
    risk_codes = _unique(risks)
    verification_records = _verification_records(verification_evidence)
    visual = visual_verification if isinstance(visual_verification, dict) else {}
    debug = debug_audit if isinstance(debug_audit, dict) else {}
    artifacts = _artifact_records(run_artifacts)
    artifact_counts = _artifact_counts(artifacts, artifact_summary)
    visual_counts = visual.get("counts") if isinstance(visual.get("counts"), dict) else {}
    visual_flags = visual.get("flags") if isinstance(visual.get("flags"), dict) else {}
    debug_counts = debug.get("counts") if isinstance(debug.get("counts"), dict) else {}
    debug_flags = debug.get("flags") if isinstance(debug.get("flags"), dict) else {}
    gap_risks = [item for item in risk_codes if item in _GAP_RISKS]
    sufficient_records = [item for item in verification_records if item.get("sufficient")]
    source_kinds = _source_kinds(
        verification_records=verification_records,
        visual_flags=visual_flags,
        debug_flags=debug_flags,
        artifact_counts=artifact_counts,
    )
    gap_facts = _gap_facts(
        required=required,
        observed=observed,
        missing=missing,
        gap_risks=gap_risks,
        visual_flags=visual_flags,
        debug_flags=debug_flags,
        artifact_counts=artifact_counts,
        verification_records=verification_records,
    )
    model_facts = _model_facts(
        result_status=str(result_status or ""),
        required=required,
        observed=observed,
        missing=missing,
        required_strength=str(required_strength or ""),
        artifact_counts=artifact_counts,
        visual_counts=visual_counts,
        visual_flags=visual_flags,
        debug_counts=debug_counts,
        debug_flags=debug_flags,
        gap_facts=gap_facts,
    )

    return {
        "schema_version": VERIFICATION_CLOSURE_SCHEMA_VERSION,
        "kind": "verification_closure",
        "boundary": "evidence_only",
        "result_status": str(result_status or ""),
        "required_strength": str(required_strength or ""),
        "modalities": {
            "required": required,
            "observed": observed,
            "missing": missing,
        },
        "counts": {
            "verification_records": len(verification_records),
            "sufficient_verification_records": len(sufficient_records),
            "final_artifacts": artifact_counts["final_artifacts"],
            "draft_artifacts": artifact_counts["draft_artifacts"],
            "visual_artifacts": artifact_counts["visual_artifacts"],
            "log_artifacts": artifact_counts["log_artifacts"],
            "verification_artifacts": artifact_counts["verification_artifacts"],
            "model_context_artifacts": artifact_counts["model_context_artifacts"],
            "visual_evidence": _safe_int(visual_counts.get("visual_evidence")),
            "visual_model_context": _safe_int(visual_counts.get("model_context_injected")),
            "visual_runtime_errors": _safe_int(visual_counts.get("runtime_error_records")),
            "debug_sessions": _safe_int(debug_counts.get("debug_sessions")),
            "debug_failures": _safe_int(debug_counts.get("failed_sessions")),
            "debug_warnings": _safe_int(debug_counts.get("warning_sessions")),
            "debug_timeouts": _safe_int(debug_counts.get("timed_out_sessions")),
            "gap_facts": len(gap_facts),
        },
        "flags": {
            "has_required_gap": bool(missing or gap_risks),
            "has_verification_evidence": bool(verification_records),
            "has_sufficient_verification": bool(sufficient_records),
            "has_final_artifact": artifact_counts["final_artifacts"] > 0,
            "has_visual_evidence": bool(visual_flags.get("has_visual_evidence"))
            or artifact_counts["visual_artifacts"] > 0,
            "visual_entered_model_context": bool(visual_flags.get("model_context_injected")),
            "has_debug_evidence": bool(debug_flags.get("has_debug_evidence")),
            "has_runtime_errors": bool(
                visual_flags.get("has_runtime_errors")
                or debug_flags.get("has_runtime_errors")
                or debug_flags.get("has_failure")
                or debug_flags.get("has_timeout")
            ),
            "has_gap_risks": bool(gap_risks),
        },
        "source_kinds": source_kinds,
        "gap_facts": gap_facts[:16],
        "risk_codes": risk_codes[:16],
        "gap_risks": gap_risks[:16],
        "artifact_paths": {
            "final": artifact_counts["final_paths"][:12],
            "visual": artifact_counts["visual_paths"][:12],
            "model_context": artifact_counts["model_context_paths"][:12],
        },
        "verification_records": verification_records[-12:],
        "model_facts": model_facts,
    }


def format_verification_closure_for_model(closure: dict[str, Any] | None) -> str:
    """Format closure facts for model-facing context or prompts."""

    if not isinstance(closure, dict):
        return ""
    if closure.get("kind") != "verification_closure":
        return ""
    lines = ["Verification closure facts:"]
    status = str(closure.get("result_status") or "").strip()
    if status:
        lines.append(f"- result_status={status}")
    modalities = closure.get("modalities") if isinstance(closure.get("modalities"), dict) else {}
    required = _join(modalities.get("required"))
    observed = _join(modalities.get("observed"))
    missing = _join(modalities.get("missing"))
    if required or observed or missing:
        lines.append(
            "- modalities: "
            f"required={required or 'none'}; "
            f"observed={observed or 'none'}; "
            f"missing={missing or 'none'}"
        )
    strength = str(closure.get("required_strength") or "").strip()
    if strength:
        lines.append(f"- required_strength={strength}")
    for fact in _string_list(closure.get("model_facts"))[:10]:
        lines.append(f"- {fact}")
    gap_facts = _string_list(closure.get("gap_facts"))
    if gap_facts:
        lines.append("- evidence gaps: " + ", ".join(gap_facts[:8]))
    paths = closure.get("artifact_paths") if isinstance(closure.get("artifact_paths"), dict) else {}
    final_paths = _string_list(paths.get("final"))
    visual_paths = _string_list(paths.get("visual"))
    if final_paths:
        lines.append("- final_artifacts=" + ", ".join(final_paths[:6]))
    if visual_paths:
        lines.append("- visual_artifacts=" + ", ".join(visual_paths[:6]))
    lines.append("- Boundary: evidence only; the model decides whether to verify, revise, ask, or finish honestly.")
    return "\n".join(lines) + "\n"


def _verification_records(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        records.append({
            "tool": str(item.get("tool") or ""),
            "path": str(item.get("path") or ""),
            "strength": str(item.get("strength") or item.get("verification_strength") or ""),
            "sufficient": bool(item.get("sufficient")),
            "modalities": _unique(item.get("modalities") or [item.get("modality")]),
            "status": str(item.get("status") or "success"),
        })
    return records


def _artifact_records(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        records.append({
            "role": str(item.get("role") or ""),
            "artifact_kind": str(item.get("artifact_kind") or item.get("kind") or ""),
            "path": str(item.get("path") or ""),
            "source_tool": str(item.get("source_tool") or item.get("tool") or ""),
            "can_enter_model_context": bool(item.get("can_enter_model_context")),
            "verification_relevance": str(item.get("verification_relevance") or ""),
        })
    return records


def _artifact_counts(
    artifacts: list[dict[str, Any]],
    artifact_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = artifact_summary if isinstance(artifact_summary, dict) else {}
    final_paths = _string_list(summary.get("final_paths"))
    visual_paths = _string_list(summary.get("visual_paths"))
    changed_paths = _string_list(summary.get("changed_paths"))
    if not final_paths:
        final_paths = _unique(item.get("path") for item in artifacts if item.get("role") == "final")
    if not visual_paths:
        visual_paths = _unique(
            item.get("path")
            for item in artifacts
            if item.get("role") in {"screenshot", "preview"}
            or item.get("artifact_kind") in {"image", "screenshot", "render", "visual_evidence"}
        )
    by_role = summary.get("by_role") if isinstance(summary.get("by_role"), dict) else {}
    model_context_paths = _unique(
        item.get("path") for item in artifacts
        if item.get("can_enter_model_context") and item.get("path")
    )
    return {
        "final_artifacts": _safe_int(by_role.get("final"))
        or len([item for item in artifacts if item.get("role") == "final"])
        or len(final_paths),
        "draft_artifacts": _safe_int(by_role.get("draft"))
        or len([item for item in artifacts if item.get("role") == "draft"]),
        "visual_artifacts": _safe_int(by_role.get("screenshot")) + _safe_int(by_role.get("preview"))
        or len(visual_paths),
        "log_artifacts": _safe_int(by_role.get("log"))
        or len([item for item in artifacts if item.get("role") == "log"]),
        "verification_artifacts": _safe_int(by_role.get("verification"))
        or len([item for item in artifacts if item.get("role") == "verification"]),
        "model_context_artifacts": _safe_int(summary.get("model_context_eligible_count"))
        or len(model_context_paths),
        "final_paths": final_paths or changed_paths,
        "visual_paths": visual_paths,
        "model_context_paths": model_context_paths,
    }


def _source_kinds(
    *,
    verification_records: list[dict[str, Any]],
    visual_flags: dict[str, Any],
    debug_flags: dict[str, Any],
    artifact_counts: dict[str, Any],
) -> list[str]:
    kinds: list[str] = []
    if verification_records:
        kinds.append("verification_evidence")
    if artifact_counts["final_artifacts"]:
        kinds.append("final_artifact")
    if artifact_counts["visual_artifacts"] or visual_flags.get("has_visual_evidence"):
        kinds.append("visual_evidence")
    if visual_flags.get("model_context_injected"):
        kinds.append("visual_model_context")
    if debug_flags.get("has_debug_evidence"):
        kinds.append("debug_evidence")
    if artifact_counts["log_artifacts"]:
        kinds.append("log_artifact")
    return kinds


def _gap_facts(
    *,
    required: list[str],
    observed: list[str],
    missing: list[str],
    gap_risks: list[str],
    visual_flags: dict[str, Any],
    debug_flags: dict[str, Any],
    artifact_counts: dict[str, Any],
    verification_records: list[dict[str, Any]],
) -> list[str]:
    facts: list[str] = []
    if required and not verification_records:
        facts.append("verification_required_but_no_verification_record")
    for modality in missing:
        facts.append(f"missing_modality:{modality}")
    if "visual" in required and not (
        visual_flags.get("has_visual_evidence") or artifact_counts["visual_artifacts"]
    ):
        facts.append("visual_evidence_not_observed")
    if visual_flags.get("model_context_available") and not visual_flags.get("model_context_injected"):
        facts.append("visual_evidence_not_in_model_context")
    if visual_flags.get("has_runtime_errors") or debug_flags.get("has_runtime_errors"):
        facts.append("runtime_errors_observed")
    if debug_flags.get("has_failure") or debug_flags.get("has_timeout"):
        facts.append("debug_failure_or_timeout_observed")
    if artifact_counts["final_artifacts"] and not verification_records:
        facts.append("final_artifact_without_verification_record")
    for risk in gap_risks:
        facts.append(f"risk:{risk}")
    return _unique(facts)


def _model_facts(
    *,
    result_status: str,
    required: list[str],
    observed: list[str],
    missing: list[str],
    required_strength: str,
    artifact_counts: dict[str, Any],
    visual_counts: dict[str, Any],
    visual_flags: dict[str, Any],
    debug_counts: dict[str, Any],
    debug_flags: dict[str, Any],
    gap_facts: list[str],
) -> list[str]:
    facts: list[str] = []
    if result_status:
        facts.append(f"result_status={result_status}")
    if required or observed or missing:
        facts.append(
            "modalities="
            f"required:{_join(required) or 'none'}; "
            f"observed:{_join(observed) or 'none'}; "
            f"missing:{_join(missing) or 'none'}"
        )
    if required_strength:
        facts.append(f"required_strength={required_strength}")
    facts.append(
        "artifacts="
        f"final:{artifact_counts['final_artifacts']}; "
        f"visual:{artifact_counts['visual_artifacts']}; "
        f"log:{artifact_counts['log_artifacts']}; "
        f"model_context:{artifact_counts['model_context_artifacts']}"
    )
    if _safe_int(visual_counts.get("visual_evidence")) or visual_flags.get("has_visual_evidence"):
        facts.append(
            "visual="
            f"evidence:{_safe_int(visual_counts.get('visual_evidence'))}; "
            f"model_context:{_safe_int(visual_counts.get('model_context_injected'))}; "
            f"errors:{_safe_int(visual_counts.get('runtime_error_records'))}"
        )
    if _safe_int(debug_counts.get("debug_sessions")) or debug_flags.get("has_debug_evidence"):
        facts.append(
            "debug="
            f"sessions:{_safe_int(debug_counts.get('debug_sessions'))}; "
            f"failures:{_safe_int(debug_counts.get('failed_sessions'))}; "
            f"warnings:{_safe_int(debug_counts.get('warning_sessions'))}; "
            f"timeouts:{_safe_int(debug_counts.get('timed_out_sessions'))}"
        )
    if gap_facts:
        facts.append("gaps=" + ",".join(gap_facts[:8]))
    return facts


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return _unique(value)


def _join(value: Any) -> str:
    return ", ".join(_string_list(value) if isinstance(value, (list, tuple)) else _unique([value]))
