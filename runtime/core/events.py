"""Trace event schema for task execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TRACE_EVENT_SCHEMA_VERSION = "trace_event.v1"

CANONICAL_EVENT_NAMES: frozenset[str] = frozenset({
    "run.status",
    "run.event",
    "run.guidance",
    "run.completion_decision",
    "task.created",
    "task.contract",
    "task.completed",
    "task.failed",
    "task.cancelled",
    "task.paused",
    "task.resumed",
    "plan.decision",
    "plan.generated",
    "plan.step.updated",
    "context.hygiene",
    "context.workspace_snapshot",
    "capability.snapshot",
    "model.reasoning",
    "model.message",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "tool.partial",
    "tool.updated",
    "tool.waiting_confirmation",
    "confirmation.requested",
    "confirmation.resolved",
    "checkpoint.created",
    "recovery.retry",
    "run.changes",
    "run.result",
    "run.completed",
    "run.failed",
})


@dataclass(frozen=True)
class TraceEvent:
    event_name: str
    run_id: str = ""
    task_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    time: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRACE_EVENT_SCHEMA_VERSION,
            "event_name": self.event_name,
            "event_family": event_family(self.event_name),
            "run_id": self.run_id,
            "task_id": self.task_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "time": self.time,
            "payload": dict(self.payload),
        }


def build_trace_event(
    event_name: str,
    *,
    run_id: str = "",
    task_id: str = "",
    span_id: str = "",
    parent_span_id: str = "",
    time: str = "",
    payload: dict[str, Any] | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_name=normalize_event_name(event_name),
        run_id=run_id,
        task_id=task_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        time=time,
        payload=dict(payload or {}),
    )


def normalize_event_name(value: str, fallback: str = "run.status") -> str:
    name = str(value or "").strip()
    return name if name in CANONICAL_EVENT_NAMES else fallback


def event_family(event_name: str) -> str:
    return str(event_name or "").split(".", 1)[0] or "unknown"
