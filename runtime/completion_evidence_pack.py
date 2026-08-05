"""面向模型的完成证据包构建与展示。

完成证据包属于只读运行时证据。它使完成自检提示保持有界，
但不判断 Run 是否完成、不选择工具，也不阻止模型自我纠偏。"""

from __future__ import annotations

from typing import Any

from runtime.run_fact_summary import build_run_fact_summary, format_run_fact_summary
from runtime.tool_attempt_recovery import (
    build_tool_attempt_recovery,
    format_tool_attempt_recovery_for_model,
    summarize_tool_attempt_recovery_for_decision,
)


COMPLETION_EVIDENCE_PACK_SCHEMA_VERSION = "completion_evidence_pack.v1"

COMPLETION_EVIDENCE_BUDGET: dict[str, int] = {
    "legacy_artifacts": 12,
    "run_artifacts": 16,
    "artifact_summary_paths": 12,
    "changed_paths": 12,
    "written_paths": 12,
    "verification_records": 12,
    "missing_modalities": 8,
    "audit_counts": 12,
    "capability_ids": 8,
    "tool_progress": 8,
    "tool_attempts": 8,
    "tool_attempt_recovery": 12,
    "failure_records": 12,
    "risks": 18,
    "completion_decisions": 6,
    "route_model_facts": 8,
    "route_advisories": 8,
    "route_capability_ids": 8,
    "formatted_prompt_chars": 12_000,
}


def build_completion_evidence_pack(
    *,
    workspace_path: str,
    task_contract: dict[str, Any] | None,
    run_result: dict[str, Any] | None,
    tool_events: list[dict[str, Any]] | None = None,
    completion_decisions: list[dict[str, Any]] | None = None,
    task_route_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建有界的模型侧完成自检证据包。"""

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
    route_evidence = _dict(task_route_evidence) or _dict(result.get("task_route_evidence"))
    tool_attempt_recovery = build_tool_attempt_recovery(
        events,
        limit=_budget("tool_attempt_recovery"),
    )
    return {
        "schema_version": COMPLETION_EVIDENCE_PACK_SCHEMA_VERSION,
        "kind": "completion_evidence_pack",
        "boundary": "evidence_only",
        "budget": dict(COMPLETION_EVIDENCE_BUDGET),
        "workspace_path": str(workspace_path or ""),
        "goal": str(contract.get("goal") or "").strip(),
        "intent": str(contract.get("intent") or "").strip(),
        "result_status": str(result.get("status") or "unknown"),
        "evidence_status": str(result.get("evidence_status") or ""),
        "completion_assessment": _completion_assessment_digest(
            result.get("completion_assessment")
        ),
        "fact_summary": fact_summary,
        "artifacts": _artifact_records(result.get("artifacts")),
        "run_artifacts": _run_artifact_records(result.get("run_artifacts")),
        "artifact_summary": _artifact_summary_digest(artifact_summary),
        "changed_paths": _string_list(
            result.get("changed_paths"),
            limit=_budget("changed_paths"),
        ),
        "written_paths": _string_list(
            result.get("target_written_paths")
            or result.get("written_paths")
            or result.get("observed_written_paths"),
            limit=_budget("written_paths"),
        ),
        "verification": _verification_records(result.get("verification_evidence")),
        "missing_verification_modalities": _string_list(
            result.get("missing_verification_modalities"),
            limit=_budget("missing_modalities"),
        ),
        "visual_verification": _audit_digest(visual),
        "debug_audit": _audit_digest(debug),
        "verification_closure": _verification_closure_digest(verification_closure),
        "capability_evidence": _capability_digest(capability),
        "task_route_evidence": _task_route_evidence_digest(route_evidence),
        "tool_progress": _tool_progress_records(events),
        "tool_attempts": _tool_attempt_records(events),
        "tool_attempt_recovery": tool_attempt_recovery,
        "failures": _failure_records(result),
        "risks": _string_list(result.get("risks"), limit=_budget("risks")),
        "previous_completion_decisions": _completion_decision_records(completion_decisions),
        "model_decision_options": [
            "continue_with_tools",
            "verify_or_repair",
            "ask_user_for_missing_boundary",
            "final_answer_from_evidence",
        ],
    }


def format_completion_evidence_pack(pack: dict[str, Any]) -> str:
    """为模型自检提示渲染紧凑证据包。"""

    lines = [
        "Completion evidence pack:",
        f"- schema: {pack.get('schema_version') or COMPLETION_EVIDENCE_PACK_SCHEMA_VERSION}",
        f"- boundary: {pack.get('boundary') or 'evidence_only'}",
        f"- result status: {pack.get('result_status') or 'unknown'}",
    ]
    budget = pack.get("budget") if isinstance(pack.get("budget"), dict) else {}
    formatted_limit = _budget("formatted_prompt_chars", budget=budget)
    goal = str(pack.get("goal") or "").strip()
    if goal:
        lines.append(f"- goal: {_short(goal, 240)}")
    _append_completion_assessment(lines, pack.get("completion_assessment"))
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
    _append_task_route_evidence(lines, pack.get("task_route_evidence"))
    _append_tool_progress(lines, pack.get("tool_progress"))
    _append_tool_attempts(lines, pack.get("tool_attempts"))
    _append_tool_attempt_recovery(lines, pack.get("tool_attempt_recovery"))
    _append_failures(lines, pack.get("failures"))
    _append_string_list(lines, "risks", pack.get("risks"))
    _append_string_list(lines, "missing verification modalities", pack.get("missing_verification_modalities"))
    _append_previous_decisions(lines, pack.get("previous_completion_decisions"))
    _append_string_list(lines, "model decision options", pack.get("model_decision_options"))
    return _bounded_text("\n".join(lines), formatted_limit)


def summarize_completion_evidence_pack_for_decision(
    evidence_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    """返回随完成决策保存的紧凑证据摘要。"""

    pack = evidence_pack if isinstance(evidence_pack, dict) else {}
    if not pack:
        return {}
    return {
        "schema_version": str(pack.get("schema_version") or ""),
        "kind": str(pack.get("kind") or ""),
        "boundary": str(pack.get("boundary") or ""),
        "result_status": str(pack.get("result_status") or ""),
        "evidence_status": str(pack.get("evidence_status") or ""),
        "completion_assessment": _completion_assessment_digest(
            pack.get("completion_assessment")
        ),
        "risks": _string_list(pack.get("risks"), limit=12),
        "missing_verification_modalities": _string_list(
            pack.get("missing_verification_modalities"),
            limit=8,
        ),
        "artifact_summary": _decision_artifact_summary(pack.get("artifact_summary")),
        "verification_closure": _decision_verification_closure(pack.get("verification_closure")),
        "tool_progress": _tool_progress_records_from_pack(pack.get("tool_progress"))[:4],
        "tool_attempts": _tool_attempt_records_from_pack(pack.get("tool_attempts"))[:4],
        "tool_attempt_recovery": summarize_tool_attempt_recovery_for_decision(
            pack.get("tool_attempt_recovery")
        ),
        "task_route_evidence": _decision_task_route_evidence(
            pack.get("task_route_evidence")
        ),
    }


def _completion_assessment_digest(value: Any) -> dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    if (
        item.get("kind") != "completion_self_assessment"
        or not isinstance(item.get("goal_closed"), bool)
    ):
        return {}
    return {
        "schema_version": str(item.get("schema_version") or ""),
        "kind": "completion_self_assessment",
        "source": str(item.get("source") or "model_declared"),
        "goal_closed": bool(item["goal_closed"]),
        "remaining_work": _string_list(item.get("remaining_work"), limit=8),
        "verification_limits": _string_list(
            item.get("verification_limits"),
            limit=8,
        ),
    }


def _append_completion_assessment(lines: list[str], value: Any) -> None:
    item = _completion_assessment_digest(value)
    if not item:
        return
    lines.append(
        "- model completion assessment: "
        f"goal_closed={str(item.get('goal_closed')).lower()}"
    )
    _append_string_list(lines, "model remaining work", item.get("remaining_work"))
    _append_string_list(
        lines,
        "model verification limits",
        item.get("verification_limits"),
    )


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
        if len(records) >= _budget("tool_progress"):
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
        if len(records) >= _budget("tool_attempts"):
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
    for item in value[:_budget("legacy_artifacts")]:
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
    for item in value[:_budget("run_artifacts")]:
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
    path_limit = _budget("artifact_summary_paths")
    return {
        "schema_version": str(value.get("schema_version") or ""),
        "kind": str(value.get("kind") or ""),
        "count": value.get("count"),
        "by_role": _compact_dict(value.get("by_role"), limit=10),
        "by_artifact_kind": _compact_dict(value.get("by_artifact_kind"), limit=10),
        "by_verification_relevance": _compact_dict(value.get("by_verification_relevance"), limit=8),
        "previewable_count": value.get("previewable_count"),
        "model_context_eligible_count": value.get("model_context_eligible_count"),
        "verification_relevant_count": value.get("verification_relevant_count"),
        "changed_paths": _string_list(value.get("changed_paths"), limit=path_limit),
        "final_paths": _string_list(value.get("final_paths"), limit=path_limit),
        "visual_paths": _string_list(value.get("visual_paths"), limit=path_limit),
        "preview_paths": _string_list(value.get("preview_paths"), limit=path_limit),
        "model_context_paths": _string_list(value.get("model_context_paths"), limit=path_limit),
        "verification_paths": _string_list(value.get("verification_paths"), limit=path_limit),
        "diagnostic_paths": _string_list(value.get("diagnostic_paths"), limit=path_limit),
        "path_index": _artifact_path_index_digest(value.get("path_index"), limit=path_limit),
        "flags": _compact_dict(value.get("flags"), limit=12),
    }


def _artifact_path_index_digest(value: Any, *, limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return records
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        records.append({
            "path": path,
            "roles": _string_list(item.get("roles"), limit=4),
            "artifact_kinds": _string_list(item.get("artifact_kinds"), limit=4),
            "source_tools": _string_list(item.get("source_tools"), limit=4),
            "verification_relevance": _string_list(item.get("verification_relevance"), limit=4),
            "can_preview": bool(item.get("can_preview")),
            "can_enter_model_context": bool(item.get("can_enter_model_context")),
        })
        if len(records) >= limit:
            break
    return records


def _verification_closure_digest(value: dict[str, Any]) -> dict[str, Any]:
    if not value or value.get("kind") != "verification_closure":
        return {}
    modalities = _dict(value.get("modalities"))
    artifact_paths = _dict(value.get("artifact_paths"))
    freshness = _dict(value.get("freshness"))
    freshness_paths = _dict(freshness.get("paths"))
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
        "freshness": {
            "kind": str(freshness.get("kind") or ""),
            "boundary": str(freshness.get("boundary") or ""),
            "latest_change_event_index": freshness.get("latest_change_event_index"),
            "counts": _compact_dict(freshness.get("counts"), limit=8),
            "flags": _compact_dict(freshness.get("flags"), limit=8),
            "paths": {
                "fresh": _string_list(freshness_paths.get("fresh"), limit=6),
                "stale": _string_list(freshness_paths.get("stale"), limit=6),
                "unknown": _string_list(freshness_paths.get("unknown"), limit=6),
            },
            "facts": _string_list(freshness.get("facts"), limit=8),
        } if freshness else {},
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
        "preview_paths": _string_list(summary.get("preview_paths"), limit=6),
        "model_context_paths": _string_list(summary.get("model_context_paths"), limit=6),
        "verification_paths": _string_list(summary.get("verification_paths"), limit=6),
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
        "verification_freshness": {
            "latest_change_event_index": _dict(closure.get("freshness")).get("latest_change_event_index"),
            "counts": _compact_dict(_dict(closure.get("freshness")).get("counts"), limit=8),
        },
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
    for item in value[:_budget("verification_records")]:
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
    _append_string_list(lines, "previewable artifact paths", item.get("preview_paths"))
    _append_string_list(lines, "model-context artifact paths", item.get("model_context_paths"))
    _append_string_list(lines, "verification artifact paths", item.get("verification_paths"))
    path_index = item.get("path_index") if isinstance(item.get("path_index"), list) else []
    if path_index:
        lines.append("- artifact path index:")
        for record in path_index[:6]:
            if not isinstance(record, dict):
                continue
            roles = ",".join(_string_list(record.get("roles"), limit=4))
            relevance = ",".join(_string_list(record.get("verification_relevance"), limit=4))
            flags = []
            if record.get("can_preview"):
                flags.append("preview")
            if record.get("can_enter_model_context"):
                flags.append("model_context")
            suffix = "; ".join(part for part in [f"roles={roles}" if roles else "", f"relevance={relevance}" if relevance else "", ",".join(flags)] if part)
            lines.append(f"  - {record.get('path') or ''}" + (f" ({suffix})" if suffix else ""))


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
    freshness = _dict(item.get("freshness"))
    if freshness:
        _append_string_list(lines, "verification freshness facts", freshness.get("facts"))
        freshness_paths = _dict(freshness.get("paths"))
        _append_string_list(lines, "stale verification paths", freshness_paths.get("stale"))


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


def _task_route_evidence_digest(value: dict[str, Any]) -> dict[str, Any]:
    if not value or value.get("kind") != "task_route_evidence":
        return {}
    flags = _dict(value.get("flags"))
    return {
        "schema_version": str(value.get("schema_version") or ""),
        "kind": "task_route_evidence",
        "boundary": str(value.get("boundary") or ""),
        "strategy_owner": str(value.get("strategy_owner") or ""),
        "safety_owner": str(value.get("safety_owner") or ""),
        "proposal_count": value.get("proposal_count"),
        "valid_proposal_count": value.get("valid_proposal_count"),
        "target_capability_ids": _string_list(
            value.get("target_capability_ids"),
            limit=_budget("route_capability_ids"),
        ),
        "preflight_target_capability_ids": _string_list(
            value.get("preflight_target_capability_ids"),
            limit=_budget("route_capability_ids"),
        ),
        "advisory_codes": _string_list(
            value.get("advisory_codes"),
            limit=_budget("route_advisories"),
        ),
        "flags": {
            key: flags.get(key)
            for key in sorted(flags)
            if key in {
                "has_model_route",
                "all_routes_valid",
                "has_route_advisories",
                "has_unknown_capability",
                "has_tool_mismatch",
            }
        },
        "model_facts": _string_list(
            value.get("model_facts"),
            limit=_budget("route_model_facts"),
        ),
    }


def _decision_task_route_evidence(value: Any) -> dict[str, Any]:
    route = value if isinstance(value, dict) else {}
    if not route:
        return {}
    flags = _dict(route.get("flags"))
    return {
        "schema_version": str(route.get("schema_version") or ""),
        "proposal_count": route.get("proposal_count"),
        "valid_proposal_count": route.get("valid_proposal_count"),
        "target_capability_ids": _string_list(
            route.get("target_capability_ids"),
            limit=6,
        ),
        "advisory_codes": _string_list(route.get("advisory_codes"), limit=6),
        "has_model_route": bool(flags.get("has_model_route")),
        "all_routes_valid": bool(flags.get("all_routes_valid")),
        "has_unknown_capability": bool(flags.get("has_unknown_capability")),
        "has_tool_mismatch": bool(flags.get("has_tool_mismatch")),
    }


def _failure_records(result: dict[str, Any]) -> list[dict[str, str]]:
    details = result.get("failure_details") if isinstance(result.get("failure_details"), list) else []
    failures = result.get("failures") if isinstance(result.get("failures"), list) else []
    records: list[dict[str, str]] = []
    for index, item in enumerate(failures[:_budget("failure_records")]):
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
    for item in value[-_budget("completion_decisions"):]:
        if not isinstance(item, dict):
            continue
        records.append({
            "review_count": item.get("review_count"),
            "action": str(item.get("action") or ""),
            "reason": str(item.get("reason") or ""),
            "tool_call_count": item.get("tool_call_count"),
            "result_status": str(item.get("result_status") or ""),
            "self_assessment": _completion_assessment_digest(
                item.get("self_assessment")
            ),
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


def _append_task_route_evidence(lines: list[str], value: Any) -> None:
    item = value if isinstance(value, dict) else {}
    if not item or item.get("kind") != "task_route_evidence":
        return
    bits = []
    if item.get("strategy_owner"):
        bits.append(f"strategy_owner={item.get('strategy_owner')}")
    if item.get("safety_owner"):
        bits.append(f"safety_owner={item.get('safety_owner')}")
    if item.get("proposal_count") is not None:
        bits.append(f"proposals={item.get('proposal_count')}")
    if item.get("valid_proposal_count") is not None:
        bits.append(f"valid={item.get('valid_proposal_count')}")
    flags = _dict(item.get("flags"))
    true_flags = [key for key in sorted(flags) if flags.get(key) is True]
    if true_flags:
        bits.append("flags=" + ",".join(true_flags[:8]))
    if bits:
        lines.append("- task route evidence: " + "; ".join(bits))
    _append_string_list(lines, "route target capabilities", item.get("target_capability_ids"))
    _append_string_list(lines, "route advisories", item.get("advisory_codes"))
    _append_string_list(lines, "route model facts", item.get("model_facts"))


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


def _append_tool_attempt_recovery(lines: list[str], value: Any) -> None:
    text = format_tool_attempt_recovery_for_model(value if isinstance(value, dict) else {})
    if text:
        lines.append(text)


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
        assessment = _completion_assessment_digest(item.get("self_assessment"))
        if assessment:
            lines.append(
                "    model_assessment: "
                f"goal_closed={str(assessment.get('goal_closed')).lower()}"
            )
            for remaining in assessment.get("remaining_work") or []:
                lines.append(f"    remaining: {_short(str(remaining), 220)}")


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


def _budget(key: str, *, budget: dict[str, Any] | None = None) -> int:
    source = budget if isinstance(budget, dict) else COMPLETION_EVIDENCE_BUDGET
    try:
        value = int(source.get(key) or COMPLETION_EVIDENCE_BUDGET[key])
    except (KeyError, TypeError, ValueError):
        value = COMPLETION_EVIDENCE_BUDGET.get(key, 8)
    return max(1, value)


def _bounded_text(text: str, limit: int) -> str:
    clean = str(text or "")
    if len(clean) <= limit:
        return clean
    marker = "\n- evidence pack truncated by presentation budget; preserved earlier high-priority evidence.\n"
    keep = max(0, limit - len(marker))
    return clean[:keep].rstrip() + marker


def _short(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"
