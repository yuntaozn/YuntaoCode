from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from .run_store import RunStore, utc_now


RECORDED_EVENT_TYPES = {
    "status",
    "tool",
    "plan_decision",
    "plan",
    "plan_step",
    "changes",
    "confirm",
    "guidance",
    "error",
    "done",
}


class RunEventHub:
    """Persist run events and broadcast compact status updates to live clients."""

    def __init__(self, store: RunStore, *, queue_size: int = 300) -> None:
        self.store = store
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
    if event_type == "done":
        result: dict[str, Any] = {
            "event": "done",
            "run_status": payload.get("run_status"),
            "context_tokens": payload.get("context_tokens"),
            "context_limit": payload.get("context_limit"),
        }
        if payload.get("usage"):
            result["usage"] = payload.get("usage")
        return result
    if event_type == "tool":
        return {
            "event": "tool",
            "status": payload.get("status"),
            "tool": payload.get("tool"),
            "name": payload.get("name"),
            "task_id": payload.get("task_id"),
            "input": payload.get("input"),
            "output": payload.get("output"),
            "error": payload.get("error"),
        }
    if event_type == "status":
        return {
            "event": "status",
            "status": payload.get("status"),
            "message": payload.get("message"),
        }
    if event_type == "guidance":
        return {
            "event": "guidance",
            "message": payload.get("message"),
        }
    if event_type == "error":
        return {
            "event": "error",
            "error": payload.get("error"),
        }
    if event_type == "changes":
        return {
            "event": "changes",
            "summary": payload.get("summary"),
        }
    if event_type == "plan_step":
        return {
            "event": "plan_step",
            "index": payload.get("index"),
            "step": payload.get("step"),
        }
    if event_type == "confirm":
        return {
            "event": "confirm",
            "message": payload.get("message"),
            "progress": payload.get("progress"),
        }
    return {key: payload.get(key) for key in ("event", "decision", "plan") if key in payload}
