"""已完成、暂停或中断 Run 的统一证据视图。

RunEvidence 是 Run 产生事件后由 Runtime 管理的事实视图。它不执行工具、
不判断模型意图，也不选择恢复策略；只收集稳定证据，供 Runbook、诊断、
Experience 导出、Replay 和未来 Evaluation 一致使用。"""

from __future__ import annotations

from typing import Any

from runtime.artifacts import build_run_artifacts, summarize_run_artifacts
from runtime.capability_evidence import build_capability_evidence_summary
from runtime.context_pack import context_pack_summary
from runtime.debug_audit import build_debug_audit
from runtime.run_trace import build_run_trace_summary
from runtime.tool_attempt_recovery import build_tool_attempt_recovery
from runtime.verification_closure import build_verification_closure
from runtime.visual_evidence import visual_evidence_summary
from runtime.visual_verification import build_visual_verification_summary
from runtime.workspace_snapshot import workspace_snapshot_summary


RUN_EVIDENCE_SCHEMA_VERSION = "run_evidence.v1"


def build_run_evidence(run: Any) -> dict[str, Any]:
    """根据类似 RunRecord 的对象构建稳定证据视图。"""
    events = [
        event for event in (getattr(run, "events", []) or [])
        if isinstance(event, dict)
    ]
    task_contract = _latest_event_value(events, "task_contract", "contract")
    result = _latest_event_value(events, "result", "result")
    plan = _latest_event_value(events, "plan", "plan")
    capability = _latest_event_value(events, "capability_snapshot", "snapshot")
    preflight = _latest_event_value(events, "capability_snapshot", "preflight")
    task_route_evidence = _latest_event_value(events, "task_route_evidence", "evidence")
    context_packs = [
        event.get("pack")
        for event in events
        if event.get("event") == "context_pack" and isinstance(event.get("pack"), dict)
    ]
    context_pack = context_packs[-1] if context_packs else None
    workspace_snapshot = _latest_event_value(events, "workspace_snapshot", "snapshot")
    tool_events = [event for event in events if event.get("event") == "tool"]
    status_events = [event for event in events if event.get("event") == "status"]
    model_calls = [event for event in events if event.get("event") == "model_call"]
    visual_context_events = [event for event in events if event.get("event") == "visual_context"]
    completion_decisions = [
        event.get("decision")
        for event in events
        if event.get("event") == "completion_decision" and isinstance(event.get("decision"), dict)
    ]
    failures = [
        event for event in tool_events
        if str(event.get("status") or "") == "failure"
    ]
    checkpoints = [
        event.get("checkpoint")
        for event in events
        if event.get("event") == "checkpoint" and isinstance(event.get("checkpoint"), dict)
    ]
    run_info = _run_info(run)
    contract = task_contract if isinstance(task_contract, dict) else {}
    result = result if isinstance(result, dict) else {}
    artifacts = _run_artifact_records(
        result=result,
        tool_events=tool_events,
        workspace_snapshot=workspace_snapshot,
    )
    visual_context = _visual_context_records(visual_context_events)
    visual_verification = build_visual_verification_summary(
        visual_evidence=_dict_list(result.get("visual_evidence")),
        debug_sessions=_dict_list(result.get("debug_sessions")),
        visual_context=visual_context,
        verification_evidence=_dict_list(result.get("verification_evidence")),
        required_modalities=_string_list(result.get("required_verification_modalities")),
        observed_modalities=_string_list(result.get("observed_verification_modalities")),
        missing_modalities=_string_list(result.get("missing_verification_modalities")),
        result_status=str(result.get("status") or ""),
        risks=_result_risks(result),
    )
    debug_audit = build_debug_audit(
        debug_sessions=_dict_list(result.get("debug_sessions")),
        result_status=str(result.get("status") or ""),
        risks=_result_risks(result),
    )
    verification_closure = _verification_closure_record(
        result=result,
        artifacts=artifacts,
        visual_verification=visual_verification,
        debug_audit=debug_audit,
    )
    tool_attempt_recovery = build_tool_attempt_recovery(tool_events)
    return {
        "schema_version": RUN_EVIDENCE_SCHEMA_VERSION,
        "kind": "run_evidence",
        "run": run_info,
        "task_contract": contract,
        "trace": build_run_trace_summary(run, events=events),
        "context_pack": context_pack_summary(context_pack),
        "context_packs": _selected_context_pack_summaries(context_packs, limit=8),
        "visual_context": visual_context,
        "visual_verification": visual_verification,
        "debug_audit": debug_audit,
        "verification_closure": verification_closure,
        "tool_attempt_recovery": tool_attempt_recovery,
        "workspace_snapshot": workspace_snapshot_summary(workspace_snapshot),
        "capability_evidence": build_capability_evidence_summary(
            tool_events,
            task_contract=contract,
        ),
        "capability_snapshot": _capability_summary(capability, preflight),
        "task_route_evidence": _task_route_evidence_summary(task_route_evidence),
        "plan": _plan_summary(plan),
        "tool_steps": [_tool_step(event) for event in tool_events],
        "status_timeline": [_status_step(event) for event in status_events[-24:]],
        "model_calls": model_calls[-24:],
        "completion_decisions": completion_decisions[-12:],
        "result": result,
        "artifacts": artifacts[:48],
        "artifact_summary": summarize_run_artifacts(artifacts),
        "risks": _result_risks(result),
        "failures": [_tool_step(event) for event in failures],
        "failure_details": _dict_list(result.get("failure_details")),
        "verification_evidence": _dict_list(result.get("verification_evidence")),
        "checkpoints": checkpoints,
        "recovery": {
            "checkpoint_count": len(checkpoints),
            "latest_checkpoint": checkpoints[-1] if checkpoints else {},
            "resume_from_checkpoint_id": run_info.get("resume_from_checkpoint_id", ""),
        },
        "replay_seed": {
            "source_run_id": run_info.get("id", ""),
            "conversation_id": run_info.get("conversation_id", ""),
            "workspace_id": run_info.get("workspace_id", ""),
            "task_id": run_info.get("task_id", ""),
            "mode": run_info.get("mode", ""),
            "goal": run_info.get("goal", ""),
            "task_contract": contract,
            "replayable": bool(events),
            "boundary": "manual_start_required",
        },
    }


def _verification_closure_record(
    *,
    result: dict[str, Any],
    artifacts: list[dict[str, Any]],
    visual_verification: dict[str, Any],
    debug_audit: dict[str, Any],
) -> dict[str, Any]:
    existing = result.get("verification_closure")
    if isinstance(existing, dict) and existing.get("kind") == "verification_closure":
        return existing
    return build_verification_closure(
        result_status=str(result.get("status") or ""),
        required_strength=str(result.get("required_verification_strength") or ""),
        required_modalities=_string_list(result.get("required_verification_modalities")),
        observed_modalities=_string_list(result.get("observed_verification_modalities")),
        missing_modalities=_string_list(result.get("missing_verification_modalities")),
        verification_evidence=_dict_list(result.get("verification_evidence")),
        visual_verification=visual_verification,
        debug_audit=debug_audit,
        run_artifacts=artifacts,
        artifact_summary=summarize_run_artifacts(artifacts),
        risks=_result_risks(result),
    )


def _run_artifact_records(
    *,
    result: dict[str, Any],
    tool_events: list[dict[str, Any]],
    workspace_snapshot: Any,
) -> list[dict[str, Any]]:
    existing = _dict_list(result.get("run_artifacts"))
    if existing:
        return existing
    legacy_artifacts = _dict_list(result.get("artifacts"))
    if not legacy_artifacts:
        legacy_artifacts = [
            {
                "kind": "file",
                "path": path,
                "status": "observed",
            }
            for path in (
                _string_list(result.get("written_paths"))
                or _string_list(result.get("changed_paths"))
            )
        ]
    return build_run_artifacts(
        workspace_path=_workspace_path_from_snapshot(workspace_snapshot),
        tool_events=tool_events,
        legacy_artifacts=legacy_artifacts,
        visual_evidence=_dict_list(result.get("visual_evidence")),
        debug_sessions=_dict_list(result.get("debug_sessions")),
        verification_evidence=_dict_list(result.get("verification_evidence")),
    )


def _workspace_path_from_snapshot(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("path") or "")


def _run_info(run: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(run, "id", "")),
        "conversation_id": str(getattr(run, "conversation_id", "")),
        "workspace_id": str(getattr(run, "workspace_id", "")),
        "task_id": str(getattr(run, "task_id", "")),
        "parent_run_id": str(getattr(run, "parent_run_id", "")),
        "source_run_id": str(getattr(run, "source_run_id", "")),
        "attempt": int(getattr(run, "attempt", 1) or 1),
        "resume_from_checkpoint_id": str(getattr(run, "resume_from_checkpoint_id", "")),
        "mode": str(getattr(run, "mode", "")),
        "status": str(getattr(run, "status", "")),
        "stage": str(getattr(run, "stage", "")),
        "goal": str(getattr(run, "user_content", "")),
        "created_at": str(getattr(run, "created_at", "")),
        "updated_at": str(getattr(run, "updated_at", "")),
    }


def _latest_event_value(events: list[dict[str, Any]], event_type: str, key: str) -> Any:
    for event in reversed(events):
        if event.get("event") == event_type:
            return event.get(key)
    return None


def _selected_context_pack_summaries(
    context_packs: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    indexed = [
        (index, pack)
        for index, pack in enumerate(context_packs)
        if isinstance(pack, dict)
    ]
    selected: set[int] = set()
    canonical_phases = [
        "task_contract",
        "planning",
        "execution",
        "verification",
        "summary",
    ]
    for phase in canonical_phases:
        for index, pack in reversed(indexed):
            if str(pack.get("phase") or "") == phase:
                selected.add(index)
                break
    for index, _pack in reversed(indexed):
        if len(selected) >= limit:
            break
        selected.add(index)
    return [
        context_pack_summary(pack)
        for index, pack in indexed
        if index in selected
    ]


def _capability_summary(capability: Any, preflight: Any) -> dict[str, Any]:
    capability = capability if isinstance(capability, dict) else {}
    preflight = preflight if isinstance(preflight, dict) else {}
    advisories = _dict_list(preflight.get("advisories"))
    readiness_issues = _dict_list(preflight.get("readiness_issues"))
    if not readiness_issues:
        readiness_issues = advisories
    return {
        "ok": preflight.get("ok"),
        "available_tool_count": len(capability.get("available_tool_ids") or []),
        "unavailable_tool_count": len(capability.get("unavailable_tool_ids") or []),
        "available_evidence_kinds": _string_list(capability.get("available_evidence_kinds")),
        "evidence_affordances": _evidence_affordance_records(
            preflight.get("evidence_affordances") or capability.get("evidence_affordances")
        ),
        "target_capability_ids": list(preflight.get("target_capability_ids") or []),
        "preferred_tool_ids": _string_list(preflight.get("preferred_tool_ids")),
        "visual_verification_tool_ids": _string_list(preflight.get("visual_verification_tool_ids")),
        "advisories": advisories,
        "readiness_issues": readiness_issues,
    }


def _task_route_evidence_summary(value: Any) -> dict[str, Any]:
    evidence = value if isinstance(value, dict) else {}
    if evidence.get("kind") != "task_route_evidence":
        return {}
    return {
        "schema_version": str(evidence.get("schema_version") or ""),
        "kind": "task_route_evidence",
        "boundary": str(evidence.get("boundary") or ""),
        "strategy_owner": str(evidence.get("strategy_owner") or ""),
        "safety_owner": str(evidence.get("safety_owner") or ""),
        "source": str(evidence.get("source") or ""),
        "proposal_count": _safe_int(evidence.get("proposal_count")),
        "valid_proposal_count": _safe_int(evidence.get("valid_proposal_count")),
        "target_capability_ids": _string_list(evidence.get("target_capability_ids"))[:12],
        "preflight_target_capability_ids": _string_list(
            evidence.get("preflight_target_capability_ids")
        )[:12],
        "advisory_codes": _string_list(evidence.get("advisory_codes"))[:12],
        "flags": _compact_bool_flags(evidence.get("flags")),
        "model_facts": _string_list(evidence.get("model_facts"))[:12],
    }


def _evidence_affordance_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if not kind:
            continue
        result.append({
            "kind": kind,
            "tool_ids": _string_list(item.get("tool_ids"))[:12],
            "verification_strengths": _string_list(item.get("verification_strengths"))[:6],
        })
        if len(result) >= 12:
            break
    return result


def _plan_summary(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    return {
        "title": str(plan.get("title") or ""),
        "state": str(plan.get("state") or ""),
        "step_count": len(steps),
        "steps": [
            {
                "index": index,
                "title": str(step.get("title") or step.get("step") or ""),
                "status": str(step.get("status") or step.get("state") or ""),
                "tool_hint": str(step.get("tool_hint") or ""),
            }
            for index, step in enumerate(steps)
            if isinstance(step, dict)
        ],
    }


def _tool_step(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": str(event.get("time") or ""),
        "tool": str(event.get("tool") or event.get("name") or ""),
        "status": str(event.get("status") or ""),
        "task_id": str(event.get("task_id") or ""),
        "input": event.get("input") if isinstance(event.get("input"), dict) else {},
        "output": event.get("output") if isinstance(event.get("output"), dict) else {},
        "error": str(event.get("error") or ""),
        "declared_capability": str(event.get("declared_capability") or ""),
        "declared_effects": _string_list(event.get("declared_effects")),
        "declared_roles": _string_list(event.get("declared_roles")),
        "declared_verification_strength": str(event.get("declared_verification_strength") or ""),
        "runtime_risks": _dict_list(event.get("runtime_risks")),
    }


def _visual_context_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        for record in _dict_list(event.get("records")):
            summary = visual_evidence_summary(record)
            if not summary:
                continue
            summary["tool"] = str(record.get("tool") or "")
            summary["injected_into_model_context"] = True
            summary["mime_type"] = str(record.get("mime_type") or "")
            records.append(summary)
    return records[-24:]


def _status_step(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": str(event.get("time") or ""),
        "status": str(event.get("status") or ""),
        "message": str(event.get("message") or ""),
    }


def _result_risks(result: dict[str, Any]) -> list[str]:
    value = result.get("risks")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compact_bool_flags(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): bool(flag)
        for key, flag in value.items()
        if isinstance(key, str) and isinstance(flag, bool)
    }
