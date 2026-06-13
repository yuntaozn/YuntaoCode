"""Runbook and replay helpers built from persisted run events.

Runbooks are runtime-owned audit artifacts. They summarize what happened in a
run without re-executing tools or trusting model prose as completion evidence.
"""

from __future__ import annotations

from typing import Any


RUNBOOK_SCHEMA_VERSION = "runbook.v1"
REPLAY_REQUEST_SCHEMA_VERSION = "replay_request.v1"


def build_runbook(run: Any) -> dict[str, Any]:
    """Build a compact runbook from a RunRecord-like object."""
    events = list(getattr(run, "events", []) or [])
    contract = _latest_event_value(events, "task_contract", "contract")
    result = _latest_event_value(events, "result", "result")
    plan = _latest_event_value(events, "plan", "plan")
    capability = _latest_event_value(events, "capability_snapshot", "snapshot")
    preflight = _latest_event_value(events, "capability_snapshot", "preflight")
    tool_events = [event for event in events if event.get("event") == "tool"]
    status_events = [event for event in events if event.get("event") == "status"]
    failures = [
        event for event in tool_events
        if str(event.get("status") or "") == "failure"
    ]
    checkpoints = [
        event.get("checkpoint")
        for event in events
        if event.get("event") == "checkpoint" and isinstance(event.get("checkpoint"), dict)
    ]
    return {
        "schema_version": RUNBOOK_SCHEMA_VERSION,
        "kind": "runbook",
        "run": {
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
        },
        "task_contract": contract or {},
        "capability_snapshot": _capability_summary(capability, preflight),
        "plan": _plan_summary(plan),
        "tool_steps": [_tool_step(event) for event in tool_events],
        "status_timeline": [_status_step(event) for event in status_events[-24:]],
        "result": result or {},
        "risks": _result_risks(result),
        "failures": [_tool_step(event) for event in failures],
        "failure_details": list(result.get("failure_details") or []) if isinstance(result, dict) else [],
        "verification_evidence": list(result.get("verification_evidence") or []) if isinstance(result, dict) else [],
        "checkpoints": checkpoints,
        "replay": build_replay_request(run, include_runbook=False),
    }


def build_replay_request(run: Any, *, include_runbook: bool = True) -> dict[str, Any]:
    """Build a replay request artifact without starting another run."""
    events = list(getattr(run, "events", []) or [])
    contract = _latest_event_value(events, "task_contract", "contract")
    replay = {
        "schema_version": REPLAY_REQUEST_SCHEMA_VERSION,
        "kind": "replay_request",
        "source_run_id": str(getattr(run, "id", "")),
        "conversation_id": str(getattr(run, "conversation_id", "")),
        "workspace_id": str(getattr(run, "workspace_id", "")),
        "task_id": str(getattr(run, "task_id", "")),
        "mode": str(getattr(run, "mode", "")),
        "goal": str(getattr(run, "user_content", "")),
        "task_contract": contract or {},
        "replayable": bool(events),
        "boundary": "manual_start_required",
        "notes": [
            "Replay request is an audit artifact in 0.1; it does not execute tools by itself.",
            "Start a new run with the goal and task_contract after reviewing the runbook.",
        ],
    }
    if include_runbook:
        replay["runbook"] = build_runbook(run)
    return replay


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
        "runtime_risks": list(event.get("runtime_risks") or []),
    }


def _status_step(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": str(event.get("time") or ""),
        "status": str(event.get("status") or ""),
        "message": str(event.get("message") or ""),
    }


def _result_risks(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    return [str(item) for item in result.get("risks") or [] if str(item)]
