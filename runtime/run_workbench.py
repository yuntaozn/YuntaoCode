"""User-facing Run Workbench view built from RunEvidence.

The workbench is a presentation model for the product UI. It does not execute
tools, judge model intent, or replace RunEvidence/RunResult. It turns runtime
facts into a compact shape that users can inspect before continuing, replaying,
or exporting a task.
"""

from __future__ import annotations

from typing import Any

from runtime.context_audit import build_context_audit
from runtime.run_evidence import build_run_evidence
from runtime.run_result_presenter import risk_message_zh


RUN_WORKBENCH_SCHEMA_VERSION = "run_workbench.v1"


def build_run_workbench(run: Any) -> dict[str, Any]:
    """Build a user-facing task workbench from a RunRecord-like object."""

    return build_run_workbench_from_evidence(build_run_evidence(run))


def build_run_workbench_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    run = _dict(evidence.get("run"))
    contract = _dict(evidence.get("task_contract"))
    result = _dict(evidence.get("result"))
    trace = _dict(evidence.get("trace"))
    plan = _dict(evidence.get("plan"))
    risks = _string_list(result.get("risks") or evidence.get("risks"))
    failures = _dict_list(result.get("failure_details")) or _dict_list(evidence.get("failure_details"))
    artifacts = _artifact_records(result, fallback_paths=result.get("written_paths") or result.get("changed_paths"))
    verification = _verification_records(result, evidence)
    tool_steps = _dict_list(evidence.get("tool_steps"))
    completion_decisions = _dict_list(evidence.get("completion_decisions"))
    context_evidence = _context_evidence_summary(evidence)
    context_audit = build_context_audit(evidence)
    visual_verification = _dict(evidence.get("visual_verification"))
    debug_audit = _dict(evidence.get("debug_audit"))
    timeline = _timeline(tool_steps, _dict_list(evidence.get("status_timeline")))[:80]
    audit = _audit_summary(
        artifacts=artifacts,
        verification=verification,
        risks=risks,
        failures=failures,
        timeline=timeline,
        completion_decisions=completion_decisions,
        context_evidence=context_evidence,
    )

    run_status = str(run.get("status") or "")
    result_status = str(result.get("status") or "")
    recoverable = run_status in {"failure", "partial", "stopped", "cancelled"} or result_status in {
        "failure",
        "partial",
        "stopped",
    }

    goal = (
        str(run.get("goal") or "").strip()
        or str(contract.get("goal") or "").strip()
        or str(_dict(evidence.get("replay_seed")).get("goal") or "").strip()
    )

    return {
        "schema_version": RUN_WORKBENCH_SCHEMA_VERSION,
        "kind": "run_workbench",
        "run": {
            "id": str(run.get("id") or ""),
            "task_id": str(run.get("task_id") or ""),
            "conversation_id": str(run.get("conversation_id") or ""),
            "workspace_id": str(run.get("workspace_id") or ""),
            "attempt": _safe_int(run.get("attempt"), 1),
            "status": run_status,
            "stage": str(run.get("stage") or ""),
            "created_at": str(run.get("created_at") or ""),
            "updated_at": str(run.get("updated_at") or ""),
        },
        "task": {
            "goal": goal,
            "contract_goal": str(contract.get("goal") or ""),
            "intent": str(contract.get("intent") or ""),
            "requires_write": bool(contract.get("requires_write")),
            "requires_state_change": bool(contract.get("requires_state_change")),
            "requires_verification": bool(contract.get("requires_verification")),
            "success_conditions": _string_list(contract.get("success_conditions")),
        },
        "status": {
            "run_status": run_status,
            "result_status": result_status,
            "result_summary": str(result.get("summary") or result.get("message") or ""),
            "event_count": _safe_int(trace.get("event_count"), 0),
            "tool_event_count": _safe_int(trace.get("tool_event_count"), 0),
            "failed_tool_count": _safe_int(trace.get("failed_tool_count"), 0),
        },
        "artifacts": artifacts[:24],
        "verification": verification[:24],
        "risks": [
            {"code": code, "message": risk_message_zh(code)}
            for code in risks
        ],
        "failures": failures[:24],
        "audit": audit,
        "plan": {
            "title": str(plan.get("title") or ""),
            "state": str(plan.get("state") or ""),
            "steps": _dict_list(plan.get("steps"))[:24],
        },
        "timeline": timeline,
        "completion_decisions": completion_decisions[:12],
        "context_evidence": context_evidence,
        "context_audit": context_audit,
        "visual_verification": visual_verification,
        "debug_audit": debug_audit,
        "context_pack": _dict(evidence.get("context_pack")),
        "context_packs": _dict_list(evidence.get("context_packs"))[:8],
        "workspace": _dict(evidence.get("workspace_snapshot")),
        "capability": {
            "snapshot": _dict(evidence.get("capability_snapshot")),
            "evidence": _dict(evidence.get("capability_evidence")),
        },
        "recovery": _dict(evidence.get("recovery")),
        "actions": {
            "can_continue": recoverable,
            "can_replay": bool(_dict(evidence.get("replay_seed")).get("replayable", False)),
            "can_export_diagnostic": True,
            "can_export_experience": True,
        },
    }


def _artifact_records(result: dict[str, Any], *, fallback_paths: Any) -> list[dict[str, Any]]:
    artifacts = _dict_list(result.get("artifacts"))
    if artifacts:
        return [_compact_artifact(item) for item in artifacts]
    return [
        {
            "kind": "file",
            "path": path,
            "tool": "",
            "status": "observed",
        }
        for path in _string_list(fallback_paths)
    ]


def _compact_artifact(item: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "kind": str(item.get("kind") or "artifact"),
        "path": str(item.get("path") or ""),
        "tool": str(item.get("tool") or ""),
        "status": str(item.get("status") or ""),
    }
    for field in ("size", "created", "changed", "deleted", "encoding", "draft_id"):
        if field in item:
            compact[field] = item.get(field)
    validation = item.get("validation")
    if isinstance(validation, dict):
        compact["validation"] = {
            key: validation.get(key)
            for key in ("valid", "validator", "text_chars", "line_count")
            if key in validation
        }
    return compact


def _verification_records(result: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    records = _dict_list(result.get("verification_evidence")) or _dict_list(evidence.get("verification_evidence"))
    if records:
        return [_compact_verification(item) for item in records]
    verified = _dict_list(result.get("verified"))
    return [_compact_verification(item) for item in verified]


def _compact_verification(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": str(item.get("tool") or ""),
        "path": str(item.get("path") or ""),
        "strength": str(item.get("strength") or item.get("verification_strength") or ""),
        "modality": str(item.get("modality") or ""),
        "status": str(item.get("status") or "success"),
    }


def _timeline(tool_steps: list[dict[str, Any]], status_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in status_steps:
        items.append({
            "time": str(item.get("time") or ""),
            "kind": "status",
            "label": str(item.get("status") or ""),
            "status": str(item.get("status") or ""),
            "message": str(item.get("message") or ""),
        })
    for item in tool_steps:
        label = str(item.get("tool") or "")
        items.append({
            "time": str(item.get("time") or ""),
            "kind": "tool",
            "label": label,
            "status": str(item.get("status") or ""),
            "message": str(item.get("error") or ""),
            "tool": label,
            "path": _tool_step_path(item),
        })
    return sorted(items, key=lambda item: item.get("time") or "")


def _audit_summary(
    *,
    artifacts: list[dict[str, Any]],
    verification: list[dict[str, Any]],
    risks: list[str],
    failures: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    completion_decisions: list[dict[str, Any]],
    context_evidence: dict[str, Any],
) -> dict[str, Any]:
    changed_paths = _changed_path_records(artifacts)
    visual_context = _dict_list(context_evidence.get("visual_context"))
    runtime_advisories = _dict_list(context_evidence.get("runtime_advisories"))
    verification_strengths = _unique_strings(item.get("strength") for item in verification)
    verification_modalities = _unique_strings(item.get("modality") for item in verification)
    failure_tools = _unique_strings(item.get("tool") for item in failures)
    risk_codes = _unique_strings(risks)
    return {
        "counts": {
            "artifacts": len(artifacts),
            "changed_paths": len(changed_paths),
            "verification": len(verification),
            "risks": len(risk_codes),
            "failures": len(failures),
            "runtime_advisories": len(runtime_advisories),
            "visual_context": len(visual_context),
            "completion_decisions": len(completion_decisions),
            "timeline": len(timeline),
        },
        "flags": {
            "has_artifacts": bool(artifacts),
            "has_changed_paths": bool(changed_paths),
            "has_verification": bool(verification),
            "has_risks": bool(risk_codes),
            "has_failures": bool(failures),
            "has_runtime_advisories": bool(runtime_advisories),
            "has_visual_context": bool(visual_context),
        },
        "changed_paths": changed_paths[:24],
        "verification": {
            "strengths": verification_strengths,
            "modalities": verification_modalities,
        },
        "risks": risk_codes[:24],
        "failure_tools": failure_tools[:16],
    }


def _changed_path_records(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in artifacts:
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        records.append({
            "path": path,
            "kind": str(item.get("kind") or ""),
            "status": str(item.get("status") or ""),
            "tool": str(item.get("tool") or ""),
            "created": bool(item.get("created")),
            "changed": bool(item.get("changed")),
            "deleted": bool(item.get("deleted")),
        })
    return records


def _context_evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    context_packs = _dict_list(evidence.get("context_packs"))
    capability = _dict(evidence.get("capability_snapshot"))
    visual_context = _dict_list(evidence.get("visual_context"))
    runtime_advisories = _runtime_advisory_records(
        tool_steps=_dict_list(evidence.get("tool_steps")),
        capability_snapshot=capability,
        risks=_string_list(evidence.get("risks")),
    )
    phases = [
        str(item.get("phase") or "")
        for item in context_packs
        if str(item.get("phase") or "")
    ]
    record_kinds: list[str] = []
    total_records = 0
    for pack in context_packs:
        total_records += _safe_int(pack.get("record_count"), 0)
        for kind in pack.get("record_kinds") or []:
            text = str(kind or "").strip()
            if text and text not in record_kinds:
                record_kinds.append(text)
    return {
        "context_pack_count": len(context_packs),
        "context_record_count": total_records,
        "context_phases": phases,
        "context_record_kinds": record_kinds[:16],
        "visual_context": visual_context[:12],
        "runtime_advisories": runtime_advisories[:24],
        "capability": {
            "ok": capability.get("ok"),
            "target_capability_ids": _string_list(capability.get("target_capability_ids")),
            "preferred_tool_ids": _string_list(capability.get("preferred_tool_ids")),
            "visual_verification_tool_ids": _string_list(capability.get("visual_verification_tool_ids")),
            "readiness_issue_count": len(_dict_list(capability.get("readiness_issues"))),
            "advisory_count": len(_dict_list(capability.get("advisories"))),
            "available_tool_count": _safe_int(capability.get("available_tool_count"), 0),
            "unavailable_tool_count": _safe_int(capability.get("unavailable_tool_count"), 0),
        },
    }


def _runtime_advisory_records(
    *,
    tool_steps: list[dict[str, Any]],
    capability_snapshot: dict[str, Any],
    risks: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _dict_list(capability_snapshot.get("readiness_issues")):
        records.append({
            "source": "capability_preflight",
            "code": str(item.get("code") or ""),
            "message": str(item.get("message") or item.get("code") or ""),
            "tool": str(item.get("tool_id") or ""),
            "capability_id": str(item.get("capability_id") or ""),
            "recommended_action": str(item.get("recommended_action") or ""),
        })
    for step in tool_steps:
        for risk in _dict_list(step.get("runtime_risks")):
            records.append({
                "source": str(risk.get("source") or step.get("tool") or "tool_result"),
                "code": str(risk.get("code") or ""),
                "message": str(risk.get("message") or risk.get("code") or ""),
                "tool": str(step.get("tool") or ""),
                "capability_id": str(risk.get("capability_id") or ""),
                "recommended_action": str(risk.get("recommended_action") or ""),
            })
    for code in risks:
        if code.startswith("capability_") or code.endswith("_advisory"):
            records.append({
                "source": "run_result",
                "code": code,
                "message": risk_message_zh(code),
                "tool": "",
                "capability_id": "",
                "recommended_action": "",
            })
    return records


def _tool_step_path(item: dict[str, Any]) -> str:
    output = _dict(item.get("output"))
    event_input = _dict(item.get("input"))
    value = output.get("path") or output.get("output_path") or event_input.get("path") or event_input.get("output_path")
    return str(value or "")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
