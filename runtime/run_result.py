from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.agent_strategy.classifiers import (
    is_invalid_verification_method_event,
    is_test_verification_event,
    is_write_tool,
    successful_verification_events,
)
from runtime.agent_strategy.document_completion import min_text_output_check
from runtime.agent_strategy.tool_event_roles import (
    deliverable_path_deviations,
    event_effects,
    event_declared_roles,
    failed_tool_event_role,
    failed_deliverable_events,
    missing_required_verification_modalities,
    required_verification_modalities,
    required_verification_strength,
    sufficient_task_verification_events,
    successful_deliverable_events,
    task_verification_events,
    verification_evidence_modalities,
    verification_evidence_strength,
    verification_strength_meets,
)
from runtime.agent_strategy.tool_result_risks import assess_tool_result_risks
from runtime.artifacts import build_run_artifacts, summarize_run_artifacts
from runtime.capability_evidence import build_capability_evidence_summary
from runtime.core.result import RUN_RESULT_SCHEMA_VERSION
from runtime.debug_audit import build_debug_audit
from runtime.debug_session import debug_session_summary, normalize_debug_session
from runtime.verification_closure import build_verification_closure
from runtime.visual_evidence import normalize_visual_evidence, visual_evidence_summary
from runtime.visual_verification import build_visual_verification_summary


def build_run_result(
    *,
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    change_summary: dict[str, Any] | None,
    mode: str | None,
    requires_code_write: bool = False,
    expected_document_coverage: bool = False,
    expected_min_output_chars: int = 0,
    task_contract: dict[str, Any] | None = None,
    contract_failed: bool = False,
    max_rounds_exceeded: bool = False,
    no_progress_budget_exhausted: bool = False,
    preflight_advisories: list[dict[str, Any]] | None = None,
    model_error: str = "",
    final_answer_error: str = "",
) -> dict[str, Any]:
    """Build deterministic run facts from tool events.

    The model may still write the final prose answer, but this structure is the
    runtime-owned source of truth for what actually happened.
    """
    capability_advisories: list[dict[str, str]] = []
    state_write_successes: list[dict[str, Any]] = []
    state_write_failures: list[dict[str, Any]] = []
    verification_successes: list[dict[str, Any]] = []
    test_successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    failed_events: list[dict[str, Any]] = []
    for advisory in preflight_advisories or []:
        if not isinstance(advisory, dict):
            continue
        capability_advisories.append({
            "code": str(advisory.get("code") or "capability_preflight_advisory"),
            "message": str(
                advisory.get("message")
                or advisory.get("code")
                or "capability preflight advisory"
            ),
        })
    invalid_verification_failures: list[dict[str, Any]] = []
    effective_statuses: list[str] = []

    for event in tool_events:
        tool_id = str(event.get("tool") or "")
        status = _effective_event_status(tool_id, event)
        effective_statuses.append(status)
        if status == "failure":
            failed_events.append(event)
            failures.append(_failure_record(workspace_path, event))
            if is_invalid_verification_method_event(event):
                invalid_verification_failures.append(event)
        if is_write_tool(tool_id):
            if status == "success":
                state_write_successes.append(event)
            elif status == "partial":
                state_write_successes.append(event)
            elif status == "failure":
                state_write_failures.append(event)

    if isinstance(task_contract, dict):
        write_successes = successful_deliverable_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        write_failures = failed_deliverable_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        verification_successes = task_verification_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        sufficient_verification_successes = sufficient_task_verification_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
    else:
        write_successes = state_write_successes
        write_failures = state_write_failures
        verification_successes = successful_verification_events(tool_events, mode)
        sufficient_verification_successes = verification_successes
    write_partials = [
        event for event in write_successes
        if _effective_event_status(str(event.get("tool") or ""), event) == "partial"
    ]
    unrecovered_write_failures = _unrecovered_failed_deliverable_events(
        tool_events=tool_events,
        failed_deliverables=write_failures,
        successful_deliverables=write_successes,
        sufficient_verifications=sufficient_verification_successes,
    )
    path_deviations = deliverable_path_deviations(write_successes, task_contract)
    target_written_paths = _unique(
        path
        for event in write_successes
        for path in _event_paths(workspace_path, event)
    )
    observed_written_paths = _unique(
        path
        for event in state_write_successes
        for path in _event_paths(workspace_path, event)
    )
    written_paths = _unique([*target_written_paths, *observed_written_paths])
    code_artifact_written = _has_code_artifact(target_written_paths or observed_written_paths)
    artifacts = _artifact_records(workspace_path, write_successes)
    test_successes = [
        event for event in verification_successes
        if is_test_verification_event(event)
    ]
    changed_paths = _changed_paths(change_summary) or written_paths
    verified = [_verification_record(workspace_path, event) for event in verification_successes]
    verified = [item for item in verified if item]
    required_strength = required_verification_strength(task_contract)
    required_modalities = required_verification_modalities(task_contract)
    verification_evidence = [
        {
            **(_verification_record(workspace_path, event) or {
                "tool": str(event.get("tool") or ""),
                "path": "",
            }),
            "strength": verification_evidence_strength(
                event,
                mode=mode,
                task_contract=task_contract,
            ),
            "sufficient": verification_strength_meets(
                verification_evidence_strength(
                    event,
                    mode=mode,
                    task_contract=task_contract,
                ),
                required_strength,
            ),
            "modalities": list(verification_evidence_modalities(
                event,
                mode=mode,
                task_contract=task_contract,
            )),
        }
        for event in verification_successes
    ]
    visual_evidence = _visual_evidence_records(tool_events)
    debug_sessions = _debug_session_records(tool_events)
    run_artifacts = build_run_artifacts(
        workspace_path=workspace_path,
        tool_events=tool_events,
        legacy_artifacts=artifacts,
        visual_evidence=visual_evidence,
        debug_sessions=debug_sessions,
        verification_evidence=verification_evidence,
    )
    artifact_summary = summarize_run_artifacts(run_artifacts)
    observed_verification_modalities = _unique(
        modality
        for item in verification_evidence
        for modality in item.get("modalities", [])
    )
    missing_verification_modalities = list(
        missing_required_verification_modalities(
            sufficient_verification_successes or verification_successes,
            task_contract,
            mode=mode,
        )
    )
    missing_code_test = _missing_code_test(
        requires_code_write=requires_code_write,
        code_artifact_written=code_artifact_written,
        write_successes=write_successes,
        test_successes=test_successes,
        required_modalities=required_modalities,
        observed_modalities=observed_verification_modalities,
        sufficient_verifications=sufficient_verification_successes,
    )
    capability_evidence = build_capability_evidence_summary(
        tool_events,
        task_contract=task_contract,
    )
    unobserved_requested_capabilities = [
        str(item)
        for item in (capability_evidence.get("unobserved_requested_capability_ids") or [])
        if str(item or "").strip()
    ]
    requested_capability_not_observed = bool(
        unobserved_requested_capabilities and not tool_events
    )

    risks: list[str] = []
    if requested_capability_not_observed:
        failures.append({
            "tool": "capability.evidence",
            "path": "",
            "error": (
                "requested capability not observed: "
                + ", ".join(unobserved_requested_capabilities)
            )[:500],
        })
        risks.append("requested_capability_not_observed")
    failure_reasons = {
        str((event.get("output") or {}).get("reason") or "").strip()
        for event in tool_events
        if isinstance(event.get("output"), dict)
    }
    if "truncated_tool_call" in failure_reasons:
        risks.append("model_output_truncated")
    if failure_reasons & {"malformed_tool_arguments", "non_object_tool_arguments", "invalid_tool_input"}:
        risks.append("invalid_tool_call_protocol")
    for event in tool_events:
        event_risks = event.get("runtime_risks")
        if not isinstance(event_risks, list) or not event_risks:
            event_risks = assess_tool_result_risks(
                str(event.get("tool") or ""),
                str(event.get("status") or ""),
                event.get("output"),
                error=event.get("error"),
            )
        for runtime_risk in event_risks or []:
            if isinstance(runtime_risk, dict) and runtime_risk.get("code"):
                risks.append(str(runtime_risk["code"]))
    if requires_code_write and not write_successes:
        risks.append("expected_write_not_observed")
    requires_target_deliverable = (
        isinstance(task_contract, dict)
        and (
            bool(task_contract.get("requires_write"))
            or bool(task_contract.get("requires_state_change"))
        )
    )
    missing_target_deliverable = bool(requires_target_deliverable and not write_successes)
    if missing_target_deliverable:
        risks.append("target_deliverable_not_observed")
    if write_successes and not verification_successes:
        risks.append("deliverable_not_verified")
        if any(is_write_tool(str(event.get("tool") or "")) for event in write_successes):
            risks.append("write_not_verified")
    requires_target_verification = bool(
        isinstance(task_contract, dict)
        and task_contract.get("requires_verification")
        and (write_successes or not requires_target_deliverable)
    )
    missing_required_verification = bool(
        requires_target_verification and not sufficient_verification_successes
    )
    if missing_required_verification:
        risks.append("required_verification_not_satisfied")
        if "visual" in missing_verification_modalities:
            risks.append("visual_verification_not_observed")
        if missing_verification_modalities:
            risks.append("verification_modality_missing")
        elif verification_successes:
            risks.append("verification_evidence_weak")
    if missing_code_test:
        risks.append("test_not_observed")
    if invalid_verification_failures:
        risks.append("invalid_verification_method")
        if write_successes:
            risks.append("runtime_verification_not_observed")
    if write_successes and unrecovered_write_failures:
        risks.append("partial_write_failure")
    if write_partials:
        risks.append("partial_write_resumable")
    if path_deviations:
        risks.append("deliverable_path_hint_changed")
    if max_rounds_exceeded:
        risks.append("max_rounds_exceeded")
    if no_progress_budget_exhausted:
        risks.append("repeated_tool_failure")
    if preflight_advisories:
        risks.append("capability_preflight_advisory")
    model_error_text = str(model_error or "").strip()
    if model_error_text:
        failures.append({
            "tool": "model.provider",
            "path": "",
            "error": model_error_text[:500],
        })
        risks.append("model_provider_error")
    final_answer_error_text = str(final_answer_error or "").strip()
    if final_answer_error_text:
        failures.append({
            "tool": "model.final_answer",
            "path": "",
            "error": final_answer_error_text[:500],
        })
        risks.append("invalid_final_answer")
    if failures and _failures_recovered(
            tool_events,
            effective_statuses,
            write_failures=state_write_failures,
        ):
        risks.append("recovered_tool_failure")

    coverage_failure = _document_coverage_failure(
        workspace_path,
        tool_events,
        expected_document_coverage=expected_document_coverage,
    )
    if coverage_failure:
        failures.append(coverage_failure)
        risks.append("document_output_coverage_low")
    min_output_check = min_text_output_check(
        tool_events,
        expected_min_output_chars=expected_min_output_chars,
        task_contract=task_contract,
        workspace_path=workspace_path,
        mode=mode,
    )
    min_output_failure = _document_min_output_failure(
        workspace_path,
        min_output_check,
    )
    if min_output_failure:
        failures.append(min_output_failure)
        risks.append(str(min_output_check.get("reason") or "document_output_too_short"))
    unresolved_contract_failed = bool(
        contract_failed
        and (
            missing_target_deliverable
            or missing_required_verification
            or bool(coverage_failure)
            or bool(min_output_failure)
        )
    )
    if unresolved_contract_failed:
        risks.append("execution_contract_failed")

    external_state_change_count = sum(
        1
        for event in tool_events
        if _effective_event_status(str(event.get("tool") or ""), event) == "success"
        and "external_state_change" in event_effects(event)
    )
    observed_state_change = bool(state_write_successes or external_state_change_count)
    contract_required_state_change = bool(
        isinstance(task_contract, dict)
        and (
            task_contract.get("requires_write")
            or task_contract.get("requires_state_change")
        )
    )
    optional_state_change_observed = bool(observed_state_change and not contract_required_state_change)
    unverified_optional_write = bool(
        optional_state_change_observed and state_write_successes and not verification_successes
    )
    if unverified_optional_write:
        risks.append("optional_write_not_verified")

    failure_details = _failure_details(
        workspace_path=workspace_path,
        tool_events=tool_events,
        failed_events=failed_events,
        task_contract=task_contract,
        mode=mode,
        successful_deliverables=write_successes,
        sufficient_verifications=sufficient_verification_successes,
    )
    for preflight_advisory in preflight_advisories or []:
        advisory = preflight_advisory if isinstance(preflight_advisory, dict) else {}
        failure_details.insert(0, {
            "tool": "capability.preflight",
            "path": "",
            "role": "capability",
            "impact": "advisory",
            "error": str(
                advisory.get("message")
                or advisory.get("code")
                or "capability preflight advisory"
            ),
        })
    if model_error_text:
        failure_details.append({
            "tool": "model.provider",
            "path": "",
            "role": "model",
            "impact": "degraded" if observed_state_change or tool_events else "blocking",
        })
    if final_answer_error_text:
        failure_details.append({
            "tool": "model.final_answer",
            "path": "",
            "role": "model",
            "impact": "degraded" if observed_state_change or tool_events else "blocking",
        })
    if requested_capability_not_observed:
        failure_details.append({
            "tool": "capability.evidence",
            "path": "",
            "role": "capability",
            "impact": "blocking",
        })
    blocking_failures = [item for item in failure_details if item["impact"] == "blocking"]
    degraded_failures = [item for item in failure_details if item["impact"] == "degraded"]
    incidental_failures = [item for item in failure_details if item["impact"] == "incidental"]
    recovered_failures = [item for item in failure_details if item["impact"] == "recovered"]
    if incidental_failures:
        risks.append("incidental_tool_failure")
    if recovered_failures:
        risks.append("recovered_tool_failure")
    if degraded_failures:
        risks.append("degraded_verification_failure")

    status = _result_status(
        has_tool_events=bool(tool_events),
        has_write_success=bool(write_successes),
        has_failure=bool(blocking_failures),
        has_invalid_verification_failure=bool(invalid_verification_failures),
        has_partial_write=bool(write_successes and unrecovered_write_failures),
        has_partial_resumable=bool(write_partials),
        has_document_coverage_failure=bool(coverage_failure),
        has_document_min_output_failure=bool(min_output_failure),
        has_missing_code_test=(
            missing_code_test
        ),
        has_missing_target_deliverable=missing_target_deliverable,
        has_missing_required_verification=missing_required_verification,
        has_unverified_optional_write=unverified_optional_write,
        has_model_error=bool(model_error_text),
        has_invalid_final_answer=bool(final_answer_error_text),
        has_observed_state_change=observed_state_change,
        contract_failed=unresolved_contract_failed,
        max_rounds_exceeded=max_rounds_exceeded,
        no_progress_budget_exhausted=no_progress_budget_exhausted,
    )
    visual_verification = build_visual_verification_summary(
        visual_evidence=visual_evidence,
        debug_sessions=debug_sessions,
        verification_evidence=verification_evidence,
        required_modalities=list(required_modalities),
        observed_modalities=observed_verification_modalities,
        missing_modalities=missing_verification_modalities,
        result_status=status,
        risks=risks,
    )
    debug_audit = build_debug_audit(
        debug_sessions=debug_sessions,
        result_status=status,
        risks=risks,
    )
    verification_closure = build_verification_closure(
        result_status=status,
        required_strength=required_strength,
        required_modalities=list(required_modalities),
        observed_modalities=observed_verification_modalities,
        missing_modalities=missing_verification_modalities,
        verification_evidence=verification_evidence,
        visual_verification=visual_verification,
        debug_audit=debug_audit,
        run_artifacts=run_artifacts,
        artifact_summary=artifact_summary,
        risks=risks,
    )
    return {
        "schema_version": RUN_RESULT_SCHEMA_VERSION,
        "kind": "run_result",
        "status": status,
        "counts": {
            "tool_events": len(tool_events),
            "deliverable_successes": len(write_successes),
            "file_write_successes": len(state_write_successes),
            "external_state_changes": external_state_change_count,
            "write_successes": len(write_successes),
            "write_partials": len(write_partials),
            "write_failures": len(write_failures),
            "unrecovered_write_failures": len(unrecovered_write_failures),
            "verification_successes": len(verification_successes),
            "test_successes": len(test_successes),
            "visual_evidence": len(visual_evidence),
            "debug_sessions": len(debug_sessions),
            "run_artifacts": len(run_artifacts),
            "failures": len(failures),
            "blocking_failures": len(blocking_failures),
            "degraded_failures": len(degraded_failures),
            "incidental_failures": len(incidental_failures),
            "recovered_failures": len(recovered_failures),
        },
        "changed_paths": changed_paths,
        "written_paths": written_paths,
        "target_written_paths": target_written_paths,
        "observed_written_paths": observed_written_paths,
        "artifacts": artifacts[:24],
        "run_artifacts": run_artifacts[:48],
        "artifact_summary": artifact_summary,
        "verified": verified[:12],
        "verification_evidence": verification_evidence[:12],
        "visual_evidence": visual_evidence[:12],
        "visual_verification": visual_verification,
        "debug_sessions": debug_sessions[:12],
        "debug_audit": debug_audit,
        "verification_closure": verification_closure,
        "capability_evidence": capability_evidence,
        "capability_advisories": capability_advisories[:12],
        "required_verification_strength": required_strength,
        "required_verification_modalities": list(required_modalities),
        "observed_verification_modalities": observed_verification_modalities,
        "missing_verification_modalities": missing_verification_modalities,
        "deliverable_path_deviations": path_deviations[:12],
        "failures": failures[:12],
        "failure_details": failure_details[:12],
        "risks": _unique(risks),
        "flags": {
            "requires_code_write": bool(requires_code_write),
            "contract_failed": bool(contract_failed),
            "unresolved_contract_failed": bool(unresolved_contract_failed),
            "max_rounds_exceeded": bool(max_rounds_exceeded),
            "no_progress_budget_exhausted": bool(no_progress_budget_exhausted),
            "expected_document_coverage": bool(expected_document_coverage),
            "expected_min_output_chars": max(0, int(expected_min_output_chars or 0)),
            "observed_text_output_chars": int(min_output_check.get("observed") or 0),
            "text_length_evidence_observed": bool(min_output_check.get("event")),
            "observed_state_change": observed_state_change,
            "optional_state_change_observed": optional_state_change_observed,
            "unverified_optional_write": unverified_optional_write,
            "model_provider_error": bool(model_error_text),
            "invalid_final_answer": bool(final_answer_error_text),
            "requested_capability_not_observed": requested_capability_not_observed,
        },
    }


def _result_status(
    *,
    has_tool_events: bool,
    has_write_success: bool,
    has_failure: bool,
    has_invalid_verification_failure: bool,
    has_partial_write: bool,
    has_partial_resumable: bool,
    has_document_coverage_failure: bool,
    has_document_min_output_failure: bool,
    has_missing_code_test: bool,
    has_missing_target_deliverable: bool,
    has_missing_required_verification: bool,
    has_unverified_optional_write: bool,
    has_model_error: bool,
    has_invalid_final_answer: bool,
    has_observed_state_change: bool,
    contract_failed: bool,
    max_rounds_exceeded: bool,
    no_progress_budget_exhausted: bool,
) -> str:
    if contract_failed:
        if has_write_success and not has_missing_target_deliverable:
            return "partial"
        return "failure"
    if max_rounds_exceeded or no_progress_budget_exhausted:
        if has_observed_state_change or has_write_success:
            return "partial"
        return "stopped"
    if has_model_error:
        if has_observed_state_change or has_write_success or has_tool_events:
            return "partial"
        return "failure"
    if has_invalid_final_answer:
        if has_observed_state_change or has_write_success or has_tool_events:
            return "partial"
        return "failure"
    if has_document_coverage_failure or has_document_min_output_failure:
        return "partial"
    if has_partial_resumable:
        return "partial"
    if has_partial_write:
        return "partial"
    if has_write_success and has_invalid_verification_failure:
        return "partial"
    if has_missing_code_test:
        return "partial"
    if has_missing_target_deliverable:
        return "failure"
    if has_missing_required_verification:
        return "partial"
    if has_unverified_optional_write:
        return "partial"
    if has_failure:
        return "failure"
    if has_write_success or has_tool_events:
        return "success"
    return "no_tool_activity"


def _unrecovered_failed_deliverable_events(
    *,
    tool_events: list[dict[str, Any]],
    failed_deliverables: list[dict[str, Any]],
    successful_deliverables: list[dict[str, Any]],
    sufficient_verifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return failed deliverable attempts that were not superseded later.

    A failed write or external-state attempt is an audit fact.  It should only
    lower the final result when no later deliverable or sufficient verification
    closed the same task loop.
    """
    if not failed_deliverables:
        return []
    failed_ids = {id(event) for event in failed_deliverables}
    deliverable_ids = {id(event) for event in successful_deliverables}
    verification_ids = {id(event) for event in sufficient_verifications}
    unrecovered: list[dict[str, Any]] = []
    for index, event in enumerate(tool_events):
        if id(event) not in failed_ids:
            continue
        recovered = any(
            id(candidate) in deliverable_ids or id(candidate) in verification_ids
            for candidate in tool_events[index + 1:]
        )
        if not recovered:
            unrecovered.append(event)
    return unrecovered


def _missing_code_test(
    *,
    requires_code_write: bool,
    code_artifact_written: bool,
    write_successes: list[dict[str, Any]],
    test_successes: list[dict[str, Any]],
    required_modalities: tuple[str, ...],
    observed_modalities: list[str],
    sufficient_verifications: list[dict[str, Any]],
) -> bool:
    if not (requires_code_write and code_artifact_written and write_successes):
        return False
    if test_successes:
        return False
    if required_modalities:
        if "behavioral" in required_modalities:
            return True
        if set(required_modalities).issubset(set(observed_modalities)) and sufficient_verifications:
            return False
    return True


def _failure_details(
    *,
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    failed_events: list[dict[str, Any]],
    task_contract: dict[str, Any] | None,
    mode: str | None,
    successful_deliverables: list[dict[str, Any]],
    sufficient_verifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failed_ids = {id(event) for event in failed_events}
    deliverable_ids = {id(event) for event in successful_deliverables}
    verification_ids = {id(event) for event in sufficient_verifications}
    success_indexes = {
        index
        for index, event in enumerate(tool_events)
        if _effective_event_status(str(event.get("tool") or ""), event) in {"success", "partial"}
    }
    has_success = bool(success_indexes)
    details: list[dict[str, Any]] = []
    for index, event in enumerate(tool_events):
        if id(event) not in failed_ids:
            continue
        role = failed_tool_event_role(
            event,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        later_deliverable = any(
            id(candidate) in deliverable_ids
            for candidate in tool_events[index + 1:]
        )
        later_verification = any(
            id(candidate) in verification_ids
            for candidate in tool_events[index + 1:]
        )
        later_success = any(candidate_index > index for candidate_index in success_indexes)
        if role == "deliverable":
            impact = "recovered" if later_deliverable or later_verification else "blocking"
        elif role == "verification":
            if later_verification:
                impact = "recovered"
            elif successful_deliverables:
                impact = "degraded"
            else:
                impact = "incidental" if has_success else "blocking"
        elif later_success:
            impact = "recovered"
        else:
            impact = "incidental" if has_success else "blocking"
        details.append({
            "tool": str(event.get("tool") or ""),
            "path": _event_path(workspace_path, event),
            "role": role,
            "impact": impact,
        })
    return details


def _changed_paths(change_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(change_summary, dict):
        return []
    paths: list[str] = []
    for item in change_summary.get("files") or []:
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]))
    return _unique(paths)


def _has_code_artifact(paths: list[str]) -> bool:
    code_suffixes = {
        ".bat",
        ".cmd",
        ".cjs",
        ".css",
        ".go",
        ".htm",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".mjs",
        ".php",
        ".ps1",
        ".py",
        ".rs",
        ".sh",
        ".svelte",
        ".ts",
        ".tsx",
        ".vue",
    }
    for path in paths:
        suffix = Path(str(path or "")).suffix.lower()
        if suffix in code_suffixes:
            return True
    return False


def _failure_record(workspace_path: str, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": str(event.get("tool") or ""),
        "path": _event_path(workspace_path, event),
        "error": _event_failure_message(event)[:500],
    }


def _effective_event_status(tool_id: str, event: dict[str, Any]) -> str:
    status = str(event.get("status") or "")
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if tool_id == "shell.run_command":
        if output.get("timed_out") is True:
            return "failure"
        try:
            exit_code = int(output.get("exit_code", 0) or 0)
        except (TypeError, ValueError):
            exit_code = 0
        if exit_code != 0:
            return "failure"
    if output.get("error") is True:
        return "failure"
    output_status = str(output.get("status") or "").strip().lower()
    if status == "partial" or output_status in {"partial", "partial_resumable"} or output.get("partial_resumable") is True:
        return "partial"
    return status


def _artifact_records(workspace_path: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        tool_id = str(event.get("tool") or "")
        kind = _artifact_kind(tool_id, output)
        status = _effective_event_status(tool_id, event)
        for path in _event_paths(workspace_path, event):
            key = (tool_id, kind, path)
            if key in seen:
                continue
            seen.add(key)
            record: dict[str, Any] = {
                "kind": kind,
                "path": path,
                "tool": tool_id,
                "status": status,
            }
            for field in (
                "size",
                "created",
                "changed",
                "deleted",
                "encoding",
                "draft_id",
            ):
                if field in output:
                    record[field] = output.get(field)
            validation = output.get("validation")
            if isinstance(validation, dict):
                compact_validation = {
                    key: validation.get(key)
                    for key in ("valid", "validator", "text_chars", "line_count")
                    if key in validation
                }
                if compact_validation:
                    record["validation"] = compact_validation
            records.append(record)
    return records


def _visual_evidence_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        tool_id = str(event.get("tool") or "")
        status = _effective_event_status(tool_id, event)
        if status not in {"success", "partial"}:
            continue
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        evidence = normalize_visual_evidence(output)
        summary = visual_evidence_summary(evidence)
        if not summary:
            continue
        path = str(summary.get("path") or "")
        key = (tool_id, path)
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "tool": tool_id,
            "status": status,
            **summary,
        })
    return records


def _debug_session_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        tool_id = str(event.get("tool") or "")
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        session = normalize_debug_session(output)
        summary = debug_session_summary(session)
        if not summary:
            continue
        key = (
            tool_id,
            str(summary.get("command") or ""),
            str(summary.get("pid") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "tool": tool_id,
            "status": _effective_event_status(tool_id, event),
            **summary,
        })
    return records


def _artifact_kind(tool_id: str, output: dict[str, Any]) -> str:
    explicit = str(output.get("artifact_kind") or "").strip()
    if explicit:
        return explicit
    output_type = str(output.get("type") or "").strip()
    if output_type in {"file_write", "file_change_set"}:
        return "file"
    if tool_id.startswith("document."):
        return "document"
    if is_write_tool(tool_id):
        return "file"
    return "artifact"


def _event_failure_message(event: dict[str, Any]) -> str:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if output.get("timed_out") is True:
        event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
        timeout = output.get("timeout") or event_input.get("timeout")
        message = f"command timed out after {timeout}s" if timeout else "command timed out"
        detail = str(output.get("stderr") or output.get("stdout") or "").strip()
        return f"{message}: {detail}" if detail else message
    error = str(event.get("error") or "").strip()
    if error:
        return error
    stderr = str(output.get("stderr") or "").strip()
    stdout = str(output.get("stdout") or "").strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    if output.get("exit_code") is not None:
        return f"exit_code={output.get('exit_code')}"
    return ""


def _failures_recovered(
    tool_events: list[dict[str, Any]],
    effective_statuses: list[str],
    *,
    write_failures: list[dict[str, Any]],
) -> bool:
    if write_failures:
        return False
    failure_indexes = [index for index, status in enumerate(effective_statuses) if status == "failure"]
    if not failure_indexes:
        return False
    last_failure = max(failure_indexes)
    return any(
        effective_statuses[index] == "success"
        and _event_indicates_progress(tool_events[index])
        for index in range(last_failure + 1, len(tool_events))
    )


def _event_indicates_progress(event: dict[str, Any]) -> bool:
    tool_id = str(event.get("tool") or "")
    if is_write_tool(tool_id):
        return True
    if "external_state_change" in event_effects(event):
        return True
    if "deliverable" in event_declared_roles(event):
        return True
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if tool_id == "shell.run_command":
        if output.get("timed_out") is True:
            return False
        try:
            return int(output.get("exit_code", 0) or 0) == 0
        except (TypeError, ValueError):
            return False
    return False


def _document_coverage_failure(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    *,
    expected_document_coverage: bool,
) -> dict[str, Any] | None:
    if not expected_document_coverage:
        return None

    source_paragraphs = 0
    source_chars = 0
    for event in tool_events:
        if str(event.get("tool") or "") != "document.extract_docx_outline":
            continue
        if _effective_event_status("document.extract_docx_outline", event) != "success":
            continue
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        source_paragraphs = max(source_paragraphs, _safe_int(output.get("paragraph_count")))
        source_chars = max(source_chars, _safe_int(output.get("text_chars")))

    if source_paragraphs < 50 and source_chars < 20000:
        return None

    best_export: dict[str, Any] | None = None
    best_ratio = 0.0
    export_tools = {"document.export_docx", "document.export_draft_docx"}
    for event in tool_events:
        tool_id = str(event.get("tool") or "")
        if tool_id not in export_tools:
            continue
        if _effective_event_status(tool_id, event) != "success":
            continue
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        draft_stats = output.get("draft_stats") if isinstance(output.get("draft_stats"), dict) else {}
        out_paragraphs = max(
            _safe_int(output.get("nonempty_paragraph_count")),
            _safe_int(output.get("paragraph_count")),
        )
        out_chars = max(_safe_int(output.get("content_chars")), _safe_int(draft_stats.get("text_chars")))
        ratios: list[float] = []
        if source_paragraphs:
            ratios.append(out_paragraphs / max(source_paragraphs, 1))
        if source_chars:
            ratios.append(out_chars / max(source_chars, 1))
        ratio = max(ratios) if ratios else 0.0
        if best_export is None or ratio > best_ratio:
            best_export = event
            best_ratio = ratio

    if best_export is None or best_ratio >= 0.25:
        return None

    output = best_export.get("output") if isinstance(best_export.get("output"), dict) else {}
    draft_stats = output.get("draft_stats") if isinstance(output.get("draft_stats"), dict) else {}
    out_paragraphs = max(
        _safe_int(output.get("nonempty_paragraph_count")),
        _safe_int(output.get("paragraph_count")),
    )
    out_chars = max(_safe_int(output.get("content_chars")), _safe_int(draft_stats.get("text_chars")))
    return {
        "tool": str(best_export.get("tool") or "document.export_docx"),
        "path": _event_path(workspace_path, best_export),
        "error": (
            "document output coverage is too low: "
            f"source_paragraphs={source_paragraphs}, output_paragraphs={out_paragraphs}, "
            f"source_chars={source_chars}, output_chars={out_chars}"
        ),
    }


def _document_min_output_failure(
    workspace_path: str,
    check: dict[str, Any],
) -> dict[str, Any] | None:
    if not check.get("required") or check.get("ok"):
        return None
    event = check.get("event") if isinstance(check.get("event"), dict) else None
    expected = _safe_int(check.get("expected"))
    observed = _safe_int(check.get("observed"))
    reason = str(check.get("reason") or "document_output_too_short")
    if reason == "document_output_length_unknown":
        return {
            "tool": str((event.get("tool") if event else "") or "runtime.text_length_check"),
            "path": _event_path(workspace_path, event) if event else "",
            "error": (
                "document output length evidence was not observed: "
                f"expected_min_chars={expected}, output_chars=0"
            ),
        }
    return {
        "tool": str((event.get("tool") if event else "") or "runtime.text_length_check"),
        "path": _event_path(workspace_path, event) if event else "",
        "error": (
            "document output is shorter than requested: "
            f"expected_min_chars={expected}, output_chars={observed}"
        ),
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _verification_record(workspace_path: str, event: dict[str, Any]) -> dict[str, Any]:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    record = {
        "tool": str(event.get("tool") or ""),
        "path": _event_path(workspace_path, event),
    }
    if event_input.get("query"):
        record["query"] = str(event_input["query"])
    return record


def _event_path(workspace_path: str, event: dict[str, Any]) -> str:
    value = _raw_event_path_hint(event)
    if not value:
        return ""
    return _relative_workspace_path(workspace_path, value)


def _event_paths(workspace_path: str, event: dict[str, Any]) -> list[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values = output.get("paths") if isinstance(output.get("paths"), list) else []
    paths = [
        _relative_workspace_path(workspace_path, str(value))
        for value in values
        if str(value or "").strip()
    ]
    if paths:
        return paths
    path = _event_path(workspace_path, event)
    return [path] if path else []


def _raw_event_path_hint(event: dict[str, Any]) -> str:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    visual_summary = visual_evidence_summary(normalize_visual_evidence(output))
    return str(
        output.get("path")
        or output.get("output_path")
        or (visual_summary or {}).get("path")
        or event_input.get("output_path")
        or event_input.get("path")
        or ""
    )


def _relative_workspace_path(workspace_path: str, value: str) -> str:
    normalized_workspace = workspace_path.replace("\\", "/").rstrip("/")
    normalized_value = value.replace("\\", "/")
    if normalized_workspace:
        workspace_prefix = normalized_workspace.lower() + "/"
        value_lower = normalized_value.lower()
        if value_lower == normalized_workspace.lower():
            return "."
        if value_lower.startswith(workspace_prefix):
            return normalized_value[len(normalized_workspace) + 1:]
    try:
        workspace = Path(workspace_path).resolve()
        path = Path(value)
        if not path.is_absolute():
            return str(path).replace("\\", "/")
        return str(path.resolve().relative_to(workspace)).replace("\\", "/")
    except (OSError, ValueError):
        return value.replace("\\", "/")


def _unique(values: Any) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
