from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from .run_store import RunStore, utc_now
from .product_task_store import ProductTaskStore


RUN_EVENT_SCHEMA_VERSION = "0.1"

RECORDED_EVENT_TYPES = {
    "status",
    "tool",
    "context_hygiene",
    "capability_snapshot",
    "task_contract",
    "plan_decision",
    "plan",
    "plan_step",
    "changes",
    "confirm",
    "guidance",
    "error",
    "result",
    "checkpoint",
    "done",
}


class RunEventHub:
    """Persist run events and broadcast compact status updates to live clients."""

    def __init__(
        self,
        store: RunStore,
        *,
        product_tasks: ProductTaskStore | None = None,
        queue_size: int = 300,
    ) -> None:
        self.store = store
        self.product_tasks = product_tasks
        self.queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def emit(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not run_id:
            return None
        event_type = str(payload.get("event") or "")
        event_time = utc_now()

        if event_type in RECORDED_EVENT_TYPES:
            compact = compact_run_event(payload)
            record = self.store.record_event(run_id, compact)
            if record and record.events:
                event_time = record.events[-1].get("time") or event_time
            if record and self.product_tasks:
                self.product_tasks.sync_from_run(record)

        live_event = {"time": event_time, **payload}
        self._broadcast(run_id, live_event)
        return live_event

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(run_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(run_id, None)

    def _broadcast(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(run_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass


def compact_run_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = payload.get("event")
    event_name = canonical_run_event_name(payload)
    if event_type == "done":
        result: dict[str, Any] = {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "done",
            "event_name": event_name,
            "run_status": payload.get("run_status"),
            "context_tokens": payload.get("context_tokens"),
            "context_limit": payload.get("context_limit"),
        }
        if payload.get("usage"):
            result["usage"] = payload.get("usage")
        return result
    if event_type == "tool":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "tool",
            "event_name": event_name,
            "status": payload.get("status"),
            "tool": payload.get("tool"),
            "name": payload.get("name"),
            "task_id": payload.get("task_id"),
            "input": payload.get("input"),
            "output": payload.get("output"),
            "error": payload.get("error"),
            "declared_capability": payload.get("declared_capability"),
            "declared_effects": payload.get("declared_effects"),
            "declared_roles": payload.get("declared_roles"),
            "declared_verification_strength": payload.get("declared_verification_strength"),
            "runtime_risks": payload.get("runtime_risks"),
        }
    if event_type == "status":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "status",
            "event_name": event_name,
            "status": payload.get("status"),
            "message": payload.get("message"),
        }
    if event_type == "task_contract":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "task_contract",
            "event_name": event_name,
            "contract": payload.get("contract"),
        }
    if event_type == "context_hygiene":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "context_hygiene",
            "event_name": event_name,
            "report": payload.get("report"),
        }
    if event_type == "capability_snapshot":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "capability_snapshot",
            "event_name": event_name,
            "snapshot": payload.get("snapshot"),
            "preflight": payload.get("preflight"),
        }
    if event_type == "guidance":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "guidance",
            "event_name": event_name,
            "message": payload.get("message"),
        }
    if event_type == "error":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "error",
            "event_name": event_name,
            "error": payload.get("error"),
            "terminal": payload.get("terminal", True),
            "recoverable": payload.get("recoverable", False),
        }
    if event_type == "changes":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "changes",
            "event_name": event_name,
            "summary": payload.get("summary"),
        }
    if event_type == "plan_step":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "plan_step",
            "event_name": event_name,
            "index": payload.get("index"),
            "step": payload.get("step"),
        }
    if event_type == "confirm":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "confirm",
            "event_name": event_name,
            "message": payload.get("message"),
            "tool": payload.get("tool"),
            "name": payload.get("name"),
            "confirmation_decision": payload.get("confirmation_decision"),
            "progress": payload.get("progress"),
        }
    if event_type == "result":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "result",
            "event_name": event_name,
            "result": payload.get("result"),
        }
    if event_type == "checkpoint":
        return {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event": "checkpoint",
            "event_name": event_name,
            "checkpoint": payload.get("checkpoint"),
        }
    result = {
        key: payload.get(key)
        for key in ("event", "decision", "plan")
        if key in payload
    }
    result["schema_version"] = RUN_EVENT_SCHEMA_VERSION
    result["event_name"] = event_name
    return result


def canonical_run_event_name(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("event") or "")
    if event_type == "tool":
        status = str(payload.get("status") or "")
        if status == "running":
            return "tool.started"
        if status == "success":
            return "tool.completed"
        if status == "partial":
            return "tool.partial"
        if status == "failure":
            return "tool.failed"
        if status == "waiting_confirmation":
            return "tool.waiting_confirmation"
        return "tool.updated"
    if event_type == "status":
        return "run.status"
    if event_type == "task_contract":
        return "task.contract"
    if event_type == "context_hygiene":
        return "context.hygiene"
    if event_type == "capability_snapshot":
        return "capability.snapshot"
    if event_type == "plan_decision":
        return "plan.decision"
    if event_type == "plan":
        return "plan.generated"
    if event_type == "plan_step":
        return "plan.step.updated"
    if event_type == "changes":
        return "run.changes"
    if event_type == "confirm":
        return "confirmation.requested"
    if event_type == "guidance":
        return "run.guidance"
    if event_type == "error":
        return "run.failed"
    if event_type == "result":
        return "run.result"
    if event_type == "checkpoint":
        return "checkpoint.created"
    if event_type == "done":
        return "run.completed"
    return event_type or "run.event"
