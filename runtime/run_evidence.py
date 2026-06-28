"""Unified evidence view for completed, paused, or interrupted Runs.

RunEvidence is the runtime-owned fact view after a run has produced events. It
does not execute tools, judge model intent, or choose a recovery strategy. It
only gathers stable evidence that Runbook, diagnostics, Experience export,
Replay, and future Evaluation can consume consistently.
"""

from __future__ import annotations

from typing import Any

from runtime.capability_evidence import build_capability_evidence_summary
from runtime.run_trace import build_run_trace_summary


RUN_EVIDENCE_SCHEMA_VERSION = "run_evidence.v1"


def build_run_evidence(run: Any) -> dict[str, Any]:
    """Build a stable evidence view from a RunRecord-like object."""
    events = [
        event for event in (getattr(run, "events", []) or [])
        if isinstance(event, dict)
    ]
    task_contract = _latest_event_value(events, "task_contract", "contract")
    result = _latest_event_value(events, "result", "result")
    plan = _latest_event_value(events, "plan", "plan")
    capability = _latest_event_value(events, "capability_snapshot", "snapshot")
    preflight = _latest_event_value(events, "capability_snapshot", "preflight")
    tool_events = [event for event in events if event.get("event") == "tool"]
    status_events = [event for event in events if event.get("event") == "status"]
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
    return {
        "schema_version": RUN_EVIDENCE_SCHEMA_VERSION,
        "kind": "run_evidence",
        "run": run_info,
        "task_contract": contract,
        "trace": build_run_trace_summary(run, events=events),
        "capability_evidence": build_capability_evidence_summary(
            tool_events,
            task_contract=contract,
        ),
        "capability_snapshot": _capability_summary(capability, preflight),
        "plan": _plan_summary(plan),
        "tool_steps": [_tool_step(event) for event in tool_events],
        "status_timeline": [_status_step(event) for event in status_events[-24:]],
        "completion_decisions": completion_decisions[-12:],
        "result": result,
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


def _capability_summary(capability: Any, preflight: Any) -> dict[str, Any]:
    capability = capability if isinstance(capability, dict) else {}
    preflight = preflight if isinstance(preflight, dict) else {}
    return {
        "ok": preflight.get("ok"),
        "available_tool_count": len(capability.get("available_tool_ids") or []),
        "unavailable_tool_count": len(capability.get("unavailable_tool_ids") or []),
        "target_capability_ids": list(preflight.get("target_capability_ids") or []),
        "blockers": list(preflight.get("blockers") or []),
    }


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
