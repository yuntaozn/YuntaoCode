"""Completion-loop evidence helpers.

The completion loop lets the model decide whether to finish honestly or keep
working from runtime facts. This module does not choose tools or block model
decisions; it records the model's observable choice so RunEvidence, Workbench,
Replay, and Evaluation can inspect what happened.
"""

from __future__ import annotations

from typing import Any

from runtime.run_fact_summary import build_run_fact_summary, format_run_fact_summary


COMPLETION_DECISION_SCHEMA_VERSION = "completion_decision.v1"
COMPLETION_EVIDENCE_PACK_SCHEMA_VERSION = "completion_evidence_pack.v1"


def build_completion_evidence_pack(
    *,
    workspace_path: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any] | None,
    tool_events: list[dict[str, Any]] | None = None,
    completion_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a model-facing evidence pack for completion self-review.

    The pack is deliberately read-only. It groups facts already observed by the
    runtime so the model can decide whether to continue, verify, repair, ask the
    user, or finish honestly.
    """

    result = run_result if isinstance(run_result, dict) else {}
    contract = task_contract if isinstance(task_contract, dict) else {}
    events = [item for item in (tool_events or []) if isinstance(item, dict)]
    fact_summary = build_run_fact_summary(
        workspace_path=workspace_path,
        tool_events=events,
        run_result=result,
        task_contract=contract,
    )
    visual = _dict(result.get("visual_verification"))
    debug = _dict(result.get("debug_audit"))
    capability = _dict(result.get("capability_evidence"))
    artifact_summary = _dict(result.get("artifact_summary"))
    verification_closure = _dict(result.get("verification_closure"))
    return {
        "schema_version": COMPLETION_EVIDENCE_PACK_SCHEMA_VERSION,
        "kind": "completion_evidence_pack",
        "boundary": "evidence_only",
        "workspace_path": str(workspace_path or ""),
        "goal": str(contract.get("goal") or "").strip(),
        "intent": str(contract.get("intent") or "").strip(),
        "result_status": str(result.get("status") or "unknown"),
        "fact_summary": fact_summary,
        "artifacts": _artifact_records(result.get("artifacts")),
        "run_artifacts": _run_artifact_records(result.get("run_artifacts")),
        "artifact_summary": _artifact_summary_digest(artifact_summary),
        "changed_paths": _string_list(result.get("changed_paths"), limit=12),
        "written_paths": _string_list(
            result.get("target_written_paths")
            or result.get("written_paths")
            or result.get("observed_written_paths"),
            limit=12,
        ),
        "verification": _verification_records(result.get("verification_evidence")),
        "missing_verification_modalities": _string_list(
            result.get("missing_verification_modalities"),
            limit=8,
        ),
        "visual_verification": _audit_digest(visual),
        "debug_audit": _audit_digest(debug),
        "verification_closure": _verification_closure_digest(verification_closure),
        "capability_evidence": _capability_digest(capability),
        "tool_progress": _tool_progress_records(events),
        "tool_attempts": _tool_attempt_records(events),
        "failures": _failure_records(result),
        "risks": _string_list(result.get("risks"), limit=18),
        "previous_completion_decisions": _completion_decision_records(completion_decisions),
        "model_decision_options": [
            "continue_with_tools",
            "verify_or_repair",
            "ask_user_for_missing_boundary",
            "final_answer_from_evidence",
        ],
    }


def format_completion_evidence_pack(pack: dict[str, Any]) -> str:
    """Render a compact evidence pack for model self-review prompts."""

    lines = [
        "Completion evidence pack:",
        f"- schema: {pack.get('schema_version') or COMPLETION_EVIDENCE_PACK_SCHEMA_VERSION}",
        f"- boundary: {pack.get('boundary') or 'evidence_only'}",
        f"- result status: {pack.get('result_status') or 'unknown'}",
    ]
    goal = str(pack.get("goal") or "").strip()
    if goal:
        lines.append(f"- goal: {_short(goal, 240)}")
    fact_summary = pack.get("fact_summary")
    if isinstance(fact_summary, dict):
        lines.append(format_run_fact_summary(fact_summary))
    _append_artifact_summary(lines, pack.get("artifact_summary"))
    _append_string_list(lines, "artifacts", _artifact_labels(pack.get("artifacts")))
    _append_string_list(lines, "run artifacts", _run_artifact_labels(pack.get("run_artifacts")))
    _append_string_list(lines, "changed paths", pack.get("changed_paths"))
    _append_string_list(lines, "written paths", pack.get("written_paths"))
    _append_verification(lines, pack.get("verification"))
    _append_verification_closure(lines, pack.get("verification_closure"))
    _append_audit_digest(lines, "visual verification", pack.get("visual_verification"))
    _append_audit_digest(lines, "debug audit", pack.get("debug_audit"))
    _append_capability(lines, pack.get("capability_evidence"))
    _append_tool_progress(lines, pack.get("tool_progress"))
    _append_tool_attempts(lines, pack.get("tool_attempts"))
    _append_failures(lines, pack.get("failures"))
    _append_string_list(lines, "risks", pack.get("risks"))
    _append_string_list(lines, "missing verification modalities", pack.get("missing_verification_modalities"))
    _append_previous_decisions(lines, pack.get("previous_completion_decisions"))
    _append_string_list(lines, "model decision options", pack.get("model_decision_options"))
    return "\n".join(lines)


def build_completion_decision(
    *,
    review_count: int,
    run_result: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]] | None,
    content: str = "",
    finish_reason: str = "",
    reason: str = "",
    evidence_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the model's next-step choice after a completion review.

    The returned value is audit evidence. It intentionally avoids an
    imperative recommendation such as "must_stop" or "must_continue".
    """

    calls = [item for item in (tool_calls or []) if isinstance(item, dict)]
    text = str(content or "").strip()
    result = run_result if isinstance(run_result, dict) else {}
    action = _observable_action(calls, text, reason)
    return {
        "schema_version": COMPLETION_DECISION_SCHEMA_VERSION,
        "source": "model_observed_behavior",
        "review_count": max(0, int(review_count or 0)),
        "action": action,
        "reason": str(reason or ""),
        "finish_reason": str(finish_reason or ""),
        "result_status": str(result.get("status") or ""),
        "risks": [str(item) for item in result.get("risks") or [] if str(item or "").strip()],
        "tool_call_count": len(calls),
        "content_chars": len(text),
        "evidence_pack": _decision_evidence_summary(evidence_pack),
    }


def _observable_action(tool_calls: list[dict[str, Any]], content: str, reason: str) -> str:
    if tool_calls:
        return "continue_with_tools"
    if reason in {"malformed_tool_call", "dangling_action"}:
        return "repair_protocol"
    if content.strip():
        return "final_answer_candidate"
    return "no_observable_decision"


def _decision_evidence_summary(evidence_pack: dict[str, Any] | None) -> dict[str, Any]:
    pack = evidence_pack if isinstance(evidence_pack, dict) else {}
    if not pack:
        return {}
    return {
        "schema_version": str(pack.get("schema_version") or ""),
        "kind": str(pack.get("kind") or ""),
        "boundary": str(pack.get("boundary") or ""),
        "result_status": str(pack.get("result_status") or ""),
        "risks": _string_list(pack.get("risks"), limit=12),
        "missing_verification_modalities": _string_list(
            pack.get("missing_verification_modalities"),
            limit=8,
        ),
        "artifact_summary": _decision_artifact_summary(pack.get("artifact_summary")),
        "verification_closure": _decision_verification_closure(pack.get("verification_closure")),
        "tool_progress": _tool_progress_records_from_pack(pack.get("tool_progress"))[:4],
        "tool_attempts": _tool_attempt_records_from_pack(pack.get("tool_attempts"))[:4],
    }


def _tool_progress_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in reversed(events):
        progress = event.get("progress") if isinstance(event.get("progress"), dict) else {}
        task_progress = progress.get("tool_task") if isinstance(progress.get("tool_task"), dict) else progress
        if not isinstance(task_progress, dict) or task_progress.get("kind") != "tool_task_progress":
            continue
        record = _tool_progress_record(
            event_tool=str(event.get("tool") or ""),
            event_status=str(event.get("status") or ""),
            task_progress=task_progress,
        )
        key = f"{record.get('task_id')}:{record.get('tool')}:{record.get('status')}"
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
        if len(records) >= 8:
            break
    return list(reversed(records))


def _tool_progress_records_from_pack(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _tool_attempt_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in reversed(events):
        observation = event.get("tool_attempt_observation")
        if not isinstance(observation, dict):
            output = event.get("output") if isinstance(event.get("output"), dict) else {}
            observation = output.get("observation") if isinstance(output.get("observation"), dict) else {}
        if not observation:
            continue
        records.append({
            "tool": str(observation.get("tool") or event.get("tool") or "unknown"),
            "status": str(observation.get("status") or event.get("status") or "not_executed"),
            "reason": str(observation.get("reason") or ""),
            "boundary": str(observation.get("boundary") or ""),
            "recoverable_by_model": bool(observation.get("recoverable_by_model")),
            "missing_fields": _string_list(observation.get("missing_fields"), limit=8),
            "model_decision": _string_list(observation.get("model_decision"), limit=4),
        })
        if len(records) >= 8:
            break
    return list(reversed(records))


def _tool_attempt_records_from_pack(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _tool_progress_record(
    *,
    event_tool: str,
    event_status: str,
    task_progress: dict[str, Any],
) -> dict[str, Any]:
    command = _dict(task_progress.get("command"))
    flags = _dict(task_progress.get("flags"))
    last_log = _dict(task_progress.get("last_log"))
    last_heartbeat = _dict(task_progress.get("last_heartbeat"))
    return {
        "task_id": str(task_progress.get("task_id") or ""),
        "tool": str(task_progress.get("tool") or event_tool),
        "status": str(task_progress.get("status") or event_status),
        "role": str(command.get("role") or ""),
        "elapsed_seconds": task_progress.get("elapsed_seconds"),
        "stale_seconds": task_progress.get("stale_seconds"),
        "can_cancel": bool(task_progress.get("can_cancel")),
        "has_live_output": bool(flags.get("has_live_output")),
        "has_heartbeat": bool(flags.get("has_heartbeat")),
        "last_log": {
            "level": str(last_log.get("level") or ""),
            "kind": str(last_log.get("kind") or ""),
            "message": _short(str(last_log.get("message") or ""), 260),
        },
        "last_heartbeat": {
            "silent_seconds": last_heartbeat.get("silent_seconds"),
            "elapsed_seconds": last_heartbeat.get("elapsed_seconds"),
        },
    }


def _artifact_records(value: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not isinstance(value, list):
        return records
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        records.append({
            "kind": str(item.get("kind") or "artifact"),
            "path": str(item.get("path") or item.get("output_path") or "").strip(),
            "tool": str(item.get("tool") or "").strip(),
            "status": str(item.get("status") or "").strip(),
        })
    return records


def _run_artifact_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return records
    for item in value[:16]:
        if not isinstance(item, dict):
            continue
        records.append({
            "role": str(item.get("role") or "artifact"),
            "artifact_kind": str(item.get("artifact_kind") or item.get("kind") or "artifact"),
            "path": str(item.get("path") or "").strip(),
            "source_tool": str(item.get("source_tool") or item.get("tool") or "").strip(),
            "status": str(item.get("status") or "").strip(),
            "can_enter_model_context": bool(item.get("can_enter_model_context")),
            "verification_relevance": str(item.get("verification_relevance") or "").strip(),
        })
    return records


def _artifact_summary_digest(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    return {
        "schema_version": str(value.get("schema_version") or ""),
        "kind": str(value.get("kind") or ""),
        "count": value.get("count"),
        "by_role": _compact_dict(value.get("by_role"), limit=10),
        "by_artifact_kind": _compact_dict(value.get("by_artifact_kind"), limit=10),
        "previewable_count": value.get("previewable_count"),
        "model_context_eligible_count": value.get("model_context_eligible_count"),
        "verification_relevant_count": value.get("verification_relevant_count"),
        "changed_paths": _string_list(value.get("changed_paths"), limit=12),
        "final_paths": _string_list(value.get("final_paths"), limit=12),
        "visual_paths": _string_list(value.get("visual_paths"), limit=12),
        "model_context_paths": _string_list(value.get("model_context_paths"), limit=12),
        "flags": _compact_dict(value.get("flags"), limit=12),
    }


def _verification_closure_digest(value: dict[str, Any]) -> dict[str, Any]:
    if not value or value.get("kind") != "verification_closure":
        return {}
    modalities = _dict(value.get("modalities"))
    artifact_paths = _dict(value.get("artifact_paths"))
    return {
        "schema_version": str(value.get("schema_version") or ""),
        "kind": str(value.get("kind") or ""),
        "boundary": str(value.get("boundary") or ""),
        "result_status": str(value.get("result_status") or ""),
        "required_strength": str(value.get("required_strength") or ""),
        "modalities": {
            "required": _string_list(modalities.get("required"), limit=8),
            "observed": _string_list(modalities.get("observed"), limit=8),
            "missing": _string_list(modalities.get("missing"), limit=8),
        },
        "counts": _compact_dict(value.get("counts"), limit=16),
        "flags": _compact_dict(value.get("flags"), limit=16),
        "source_kinds": _string_list(value.get("source_kinds"), limit=12),
        "gap_facts": _string_list(value.get("gap_facts"), limit=12),
        "gap_risks": _string_list(value.get("gap_risks"), limit=12),
        "artifact_paths": {
            "final": _string_list(artifact_paths.get("final"), limit=8),
            "visual": _string_list(artifact_paths.get("visual"), limit=8),
            "model_context": _string_list(artifact_paths.get("model_context"), limit=8),
        },
        "model_facts": _string_list(value.get("model_facts"), limit=10),
    }


def _decision_artifact_summary(value: Any) -> dict[str, Any]:
    summary = value if isinstance(value, dict) else {}
    if not summary:
        return {}
    flags = _dict(summary.get("flags"))
    return {
        "count": summary.get("count"),
        "by_role": _compact_dict(summary.get("by_role"), limit=8),
        "final_paths": _string_list(summary.get("final_paths"), limit=6),
        "visual_paths": _string_list(summary.get("visual_paths"), limit=6),
        "model_context_paths": _string_list(summary.get("model_context_paths"), limit=6),
        "has_final_artifacts": bool(flags.get("has_final_artifacts")),
        "has_visual_artifacts": bool(flags.get("has_visual_artifacts")),
        "has_model_context_artifacts": bool(flags.get("has_model_context_artifacts")),
    }


def _decision_verification_closure(value: Any) -> dict[str, Any]:
    closure = value if isinstance(value, dict) else {}
    if not closure:
        return {}
    flags = _dict(closure.get("flags"))
    modalities = _dict(closure.get("modalities"))
    return {
        "result_status": str(closure.get("result_status") or ""),
        "missing_modalities": _string_list(modalities.get("missing"), limit=8),
        "gap_facts": _string_list(closure.get("gap_facts"), limit=8),
        "gap_risks": _string_list(closure.get("gap_risks"), limit=8),
        "has_required_gap": bool(flags.get("has_required_gap")),
        "has_sufficient_verification": bool(flags.get("has_sufficient_verification")),
        "has_runtime_errors": bool(flags.get("has_runtime_errors")),
    }


def _artifact_labels(value: Any) -> list[str]:
    records = value if isinstance(value, list) else []
    labels: list[str] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        label = str(item.get("kind") or "artifact")
        if item.get("path"):
            label += f": {item['path']}"
        if item.get("status"):
            label += f" ({item['status']})"
        labels.append(label)
    return labels


def _run_artifact_labels(value: Any) -> list[str]:
    records = value if isinstance(value, list) else []
    labels: list[str] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        label = str(item.get("role") or "artifact")
        kind = str(item.get("artifact_kind") or "").strip()
        if kind:
            label += f"/{kind}"
        if item.get("path"):
            label += f": {item['path']}"
        if item.get("source_tool"):
            label += f" via {item['source_tool']}"
        if item.get("can_enter_model_context"):
            label += " model_context"
        relevance = str(item.get("verification_relevance") or "").strip()
        if relevance:
            label += f" verification={relevance}"
        labels.append(label)
    return labels


def _verification_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return records
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        records.append({
            "tool": str(item.get("tool") or "unknown"),
            "path": str(item.get("path") or "").strip(),
            "strength": str(item.get("strength") or "").strip(),
            "sufficient": bool(item.get("sufficient")),
            "modalities": _string_list(item.get("modalities"), limit=8),
        })
    return records


def _append_artifact_summary(lines: list[str], value: Any) -> None:
    item = value if isinstance(value, dict) else {}
    if not item or not item.get("kind"):
        return
    bits = []
    if item.get("count") is not None:
        bits.append(f"count={item.get('count')}")
    by_role = _dict(item.get("by_role"))
    role_bits = [f"{key}:{by_role[key]}" for key in sorted(by_role) if by_role.get(key)]
    if role_bits:
        bits.append("roles=" + ",".join(role_bits[:8]))
    for field in ("previewable_count", "model_context_eligible_count", "verification_relevant_count"):
        if item.get(field) not in (None, "", 0, False):
            bits.append(f"{field}={item.get(field)}")
    if bits:
        lines.append("- artifact summary: " + "; ".join(bits[:10]))
    _append_string_list(lines, "final artifact paths", item.get("final_paths"))
    _append_string_list(lines, "visual artifact paths", item.get("visual_paths"))
    _append_string_list(lines, "model-context artifact paths", item.get("model_context_paths"))


def _append_verification_closure(lines: list[str], value: Any) -> None:
    item = value if isinstance(value, dict) else {}
    if not item or item.get("kind") != "verification_closure":
        return
    bits = []
    modalities = _dict(item.get("modalities"))
    missing = ",".join(_string_list(modalities.get("missing"), limit=6))
    if item.get("result_status"):
        bits.append(f"status={item.get('result_status')}")
    if missing:
        bits.append(f"missing={missing}")
    flags = _dict(item.get("flags"))
    true_flags = [key for key in sorted(flags) if flags.get(key) is True]
    if true_flags:
        bits.append("flags=" + ",".join(true_flags[:8]))
    if bits:
        lines.append("- verification closure: " + "; ".join(bits))
    _append_string_list(lines, "verification gap facts", item.get("gap_facts"))
    _append_string_list(lines, "verification gap risks", item.get("gap_risks"))


def _audit_digest(value: dict[str, Any]) -> dict[str, Any]:
    counts = _dict(value.get("counts"))
    flags = _dict(value.get("flags"))
    return {
        "schema_version": str(value.get("schema_version") or ""),
        "kind": str(value.get("kind") or ""),
        "boundary": str(value.get("boundary") or ""),
        "counts": {
            key: counts.get(key)
            for key in sorted(counts)
            if key in {
                "visual_evidence",
                "visual_verification_records",
                "runtime_error_records",
                "model_context_injected",
                "debug_sessions",
                "dependency_install_sessions",
                "preview_sessions",
                "service_sessions",
                "timed_out_sessions",
                "failed_sessions",
                "warning_sessions",
                "long_sessions",
                "diagnostics",
            }
        },
        "flags": {
            key: flags.get(key)
            for key in sorted(flags)
            if key in {
                "has_visual_evidence",
                "visual_required",
                "visual_missing",
                "has_runtime_errors",
                "model_context_injected",
                "has_dependency_install",
                "has_preview_service",
                "has_service_evidence",
                "has_timeout",
                "has_failure",
                "has_warning",
                "has_long_session",
            }
        },
    }


def _capability_digest(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": str(value.get("schema_version") or ""),
        "requested_capability_ids": _string_list(value.get("requested_capability_ids"), limit=8),
        "observed_capability_ids": _string_list(value.get("observed_capability_ids"), limit=8),
        "unobserved_requested_capability_ids": _string_list(
            value.get("unobserved_requested_capability_ids"),
            limit=8,
        ),
        "status_counts": _dict(value.get("status_counts")),
        "verification_strengths": _string_list(value.get("verification_strengths"), limit=8),
    }


def _failure_records(result: dict[str, Any]) -> list[dict[str, str]]:
    details = result.get("failure_details") if isinstance(result.get("failure_details"), list) else []
    failures = result.get("failures") if isinstance(result.get("failures"), list) else []
    records: list[dict[str, str]] = []
    for index, item in enumerate(failures[:12]):
        if not isinstance(item, dict):
            continue
        detail = details[index] if index < len(details) and isinstance(details[index], dict) else {}
        records.append({
            "tool": str(item.get("tool") or detail.get("tool") or "unknown"),
            "path": str(item.get("path") or detail.get("path") or "").strip(),
            "impact": str(detail.get("impact") or "").strip(),
            "error": _short(str(item.get("error") or detail.get("error") or ""), 420),
        })
    return records


def _completion_decision_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return records
    for item in value[-6:]:
        if not isinstance(item, dict):
            continue
        records.append({
            "review_count": item.get("review_count"),
            "action": str(item.get("action") or ""),
            "reason": str(item.get("reason") or ""),
            "tool_call_count": item.get("tool_call_count"),
            "result_status": str(item.get("result_status") or ""),
        })
    return records


def _append_verification(lines: list[str], value: Any) -> None:
    records = value if isinstance(value, list) else []
    if not records:
        return
    lines.append("- verification evidence:")
    for item in records[:8]:
        if not isinstance(item, dict):
            continue
        modalities = ",".join(_string_list(item.get("modalities"), limit=4))
        suffix = f" [{modalities}]" if modalities else ""
        path = f" {item.get('path')}" if item.get("path") else ""
        strength = f" strength={item.get('strength')}" if item.get("strength") else ""
        sufficient = " sufficient" if item.get("sufficient") else ""
        lines.append(f"  - {item.get('tool') or 'unknown'}{path}{suffix}{strength}{sufficient}")


def _append_audit_digest(lines: list[str], title: str, value: Any) -> None:
    item = value if isinstance(value, dict) else {}
    if not item or not item.get("kind"):
        return
    counts = _dict(item.get("counts"))
    flags = _dict(item.get("flags"))
    bits = [
        f"{key}={counts[key]}"
        for key in sorted(counts)
        if counts.get(key) not in (None, "", 0, False)
    ]
    flag_bits = [
        key
        for key in sorted(flags)
        if flags.get(key) is True
    ]
    if bits or flag_bits:
        lines.append(f"- {title}: " + "; ".join([*bits[:8], *flag_bits[:8]]))


def _append_capability(lines: list[str], value: Any) -> None:
    item = value if isinstance(value, dict) else {}
    if not item:
        return
    _append_string_list(lines, "requested capabilities", item.get("requested_capability_ids"))
    _append_string_list(lines, "observed capabilities", item.get("observed_capability_ids"))
    _append_string_list(
        lines,
        "unobserved requested capabilities",
        item.get("unobserved_requested_capability_ids"),
    )


def _append_tool_progress(lines: list[str], value: Any) -> None:
    records = value if isinstance(value, list) else []
    if not records:
        return
    lines.append("- recent tool progress:")
    for item in records[-6:]:
        if not isinstance(item, dict):
            continue
        bits = [
            str(item.get("tool") or "unknown"),
            str(item.get("status") or ""),
            f"role={item.get('role')}" if item.get("role") else "",
            f"elapsed={item.get('elapsed_seconds')}s" if item.get("elapsed_seconds") is not None else "",
            f"stale={item.get('stale_seconds')}s" if item.get("stale_seconds") is not None else "",
        ]
        last_log = _dict(item.get("last_log"))
        suffix = f": {_short(str(last_log.get('message') or ''), 220)}" if last_log.get("message") else ""
        lines.append("  - " + " | ".join(part for part in bits if part) + suffix)


def _append_tool_attempts(lines: list[str], value: Any) -> None:
    records = _tool_attempt_records_from_pack(value)
    if not records:
        return
    lines.append("- recent unexecuted tool attempts:")
    for item in records[:8]:
        bits = [
            str(item.get("tool") or "unknown"),
            str(item.get("reason") or "unknown"),
        ]
        boundary = str(item.get("boundary") or "").strip()
        if boundary:
            bits.append(f"boundary={boundary}")
        missing = _string_list(item.get("missing_fields"), limit=4)
        if missing:
            bits.append("missing=" + ",".join(missing))
        if item.get("recoverable_by_model") is True:
            bits.append("recoverable_by_model=true")
        lines.append(f"  - {' | '.join(bits)}")


def _append_failures(lines: list[str], value: Any) -> None:
    records = value if isinstance(value, list) else []
    if not records:
        return
    lines.append("- failures:")
    for item in records[:8]:
        if not isinstance(item, dict):
            continue
        bits = [str(item.get("tool") or "unknown")]
        if item.get("path"):
            bits.append(str(item["path"]))
        if item.get("impact"):
            bits.append(f"impact={item['impact']}")
        suffix = f": {_short(str(item.get('error') or ''), 220)}" if item.get("error") else ""
        lines.append(f"  - {' | '.join(bits)}{suffix}")


def _append_previous_decisions(lines: list[str], value: Any) -> None:
    records = value if isinstance(value, list) else []
    if not records:
        return
    lines.append("- previous completion decisions:")
    for item in records[-6:]:
        if not isinstance(item, dict):
            continue
        lines.append(
            "  - "
            f"review={item.get('review_count')}; "
            f"action={item.get('action')}; "
            f"tools={item.get('tool_call_count')}; "
            f"reason={item.get('reason') or ''}"
        )


def _append_string_list(lines: list[str], title: str, value: Any) -> None:
    items = _string_list(value, limit=8)
    if not items:
        return
    lines.append(f"- {title}:")
    lines.extend(f"  - {_short(item, 260)}" for item in items)


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact_dict(value: Any, *, limit: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in sorted(value, key=lambda item: str(item)):
        if len(result) >= limit:
            break
        result[str(key)] = value[key]
    return result


def _short(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"
