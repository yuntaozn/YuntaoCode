"""Stable trace summaries derived from persisted Run events.

The persisted event stream still keeps the legacy ``event`` field for the
current UI and streaming contract.  This module gives Runbook, diagnostic
export, replay, and future evaluation code one normalized audit view without
forcing a storage migration.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from runtime.run_events import canonical_run_event_name


RUN_TRACE_SUMMARY_SCHEMA_VERSION = "run_trace_summary.v1"


def build_run_trace_summary(
    run: Any,
    *,
    events: list[dict[str, Any]] | None = None,
    timeline_limit: int = 50,
) -> dict[str, Any]:
    """Build a compact, sanitized trace summary for one Run."""
    raw_events = _event_list(run, events)
    normalized = [
        _normalize_trace_event(index, event)
        for index, event in enumerate(raw_events)
        if isinstance(event, dict)
    ]
    event_names = Counter(item["event_name"] for item in normalized)
    event_families = Counter(item["event_family"] for item in normalized)
    tool_events = [item for item in normalized if item["event_family"] == "tool"]
    failed_tools = [
        item for item in tool_events
        if item["event_name"] == "tool.failed" or item["status"] == "failure"
    ]
    result_status = _latest_result_status(raw_events)
    run_status = str(getattr(run, "status", "") or result_status or "")
    limit = max(0, int(timeline_limit))
    return {
        "schema_version": RUN_TRACE_SUMMARY_SCHEMA_VERSION,
        "kind": "run_trace_summary",
        "run_id": str(getattr(run, "id", "")),
        "task_id": str(getattr(run, "task_id", "")),
        "event_count": len(normalized),
        "event_name_counts": dict(sorted(event_names.items())),
        "event_family_counts": dict(sorted(event_families.items())),
        "tool_event_count": len(tool_events),
        "failed_tool_count": len(failed_tools),
        "confirmation_count": event_families.get("confirmation", 0),
        "checkpoint_count": event_families.get("checkpoint", 0),
        "run_status": run_status,
        "result_status": result_status,
        "latest_event_name": normalized[-1]["event_name"] if normalized else "",
        "timeline": normalized[-limit:] if limit else [],
    }


def _event_list(run: Any, events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if events is not None:
        return [item for item in events if isinstance(item, dict)]
    return [
        item for item in (getattr(run, "events", []) or [])
        if isinstance(item, dict)
    ]


def _normalize_trace_event(index: int, event: dict[str, Any]) -> dict[str, Any]:
    event_name = str(event.get("event_name") or canonical_run_event_name(event))
    family = event_name.split(".", 1)[0] if "." in event_name else str(event.get("event") or "run")
    item = {
        "index": index,
        "time": str(event.get("time") or ""),
        "event": str(event.get("event") or ""),
        "event_name": event_name,
        "event_family": family or "run",
        "status": str(event.get("status") or ""),
        "tool": str(event.get("tool") or event.get("name") or ""),
        "task_id": str(event.get("task_id") or ""),
        "summary": _event_summary(event),
    }
    if "terminal" in event:
        item["terminal"] = bool(event.get("terminal", True))
    if "recoverable" in event:
        item["recoverable"] = bool(event.get("recoverable", False))
    if str(event.get("error") or ""):
        item["error"] = _truncate(event.get("error"), 500)
    return item


def _event_summary(event: dict[str, Any]) -> str:
    event_type = str(event.get("event") or "")
    if event_type == "tool":
        tool = str(event.get("tool") or event.get("name") or "tool")
        status = str(event.get("status") or "updated")
        error = str(event.get("error") or "").strip()
        return _truncate(f"{status} {tool}: {error}" if error else f"{status} {tool}", 500)
    if event_type == "status":
        return _truncate(event.get("message") or event.get("status") or "", 500)
    if event_type == "confirm":
        return _truncate(event.get("message") or "confirmation requested", 500)
    if event_type == "error":
        return _truncate(event.get("error") or "runtime error", 500)
    if event_type == "result":
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        status = str(result.get("status") or "").strip()
        summary = str(result.get("summary") or result.get("message") or "").strip()
        return _truncate(f"result {status}: {summary}" if summary else f"result {status}", 500)
    if event_type == "task_contract":
        contract = event.get("contract") if isinstance(event.get("contract"), dict) else {}
        return _truncate(
            contract.get("goal") or contract.get("intent") or "task contract recorded",
            500,
        )
    if event_type == "capability_snapshot":
        preflight = event.get("preflight") if isinstance(event.get("preflight"), dict) else {}
        status = "ok" if preflight.get("ok") is not False else "blocked"
        targets = ", ".join(str(item) for item in (preflight.get("target_capability_ids") or [])[:6])
        return _truncate(f"capability snapshot {status}" + (f": {targets}" if targets else ""), 500)
    if event_type == "plan":
        plan = event.get("plan") if isinstance(event.get("plan"), dict) else {}
        return _truncate(plan.get("title") or "plan generated", 500)
    if event_type == "plan_step":
        return _truncate(event.get("step") or "plan step updated", 500)
    if event_type == "changes":
        return _truncate(event.get("summary") or "changes recorded", 500)
    if event_type == "checkpoint":
        checkpoint = event.get("checkpoint") if isinstance(event.get("checkpoint"), dict) else {}
        return _truncate(checkpoint.get("state") or checkpoint.get("id") or "checkpoint created", 500)
    if event_type == "context_hygiene":
        report = event.get("report") if isinstance(event.get("report"), dict) else {}
        changed = report.get("changed")
        return "context hygiene changed" if changed else "context hygiene checked"
    return _truncate(event.get("message") or event_type or "run event", 500)


def _latest_result_status(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            return str(event["result"].get("status") or "")
        if event.get("event") == "done":
            return str(event.get("run_status") or "")
    return ""


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."
