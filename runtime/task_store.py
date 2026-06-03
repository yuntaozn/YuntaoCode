from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


TOOL_TASK_STORE_SCHEMA_VERSION = "0.1"
TOOL_TASK_RECORD_SCHEMA_VERSION = "0.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    """A persisted tool invocation record.

    This is intentionally narrower than the product-level Task Model described
    in docs/task-model.md. The public API keeps the historical "task" wording
    for compatibility, while records declare themselves as "tool_task".
    """

    id: str
    tool: str
    input: dict[str, Any]
    status: str = "queued"
    output: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    logs: list[dict[str, Any]] = field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TOOL_TASK_RECORD_SCHEMA_VERSION,
            "record_kind": "tool_task",
            "kind": "tool_task",
            "id": self.id,
            "tool": self.tool,
            "tool_id": self.tool,
            "input": self.input,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "logs": self.logs,
        }


class TaskStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = storage_path
        self._tasks: dict[str, TaskRecord] = {}
        self._subscribers: dict[str, set[Any]] = {}
        self._load()

    def create(self, tool: str, input_data: dict[str, Any]) -> TaskRecord:
        task = TaskRecord(id=str(uuid4()), tool=tool, input=input_data)
        self._tasks[task.id] = task
        self.append_log(task.id, "info", "task queued")
        return task

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        task = self._require(task_id)
        if status is not None:
            task.status = status
        if output is not None:
            task.output = output
        if error is not None:
            task.error = error
        task.updated_at = utc_now()
        self._save()
        return task

    def append_log(self, task_id: str, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        task = self._require(task_id)
        task.updated_at = utc_now()
        event = {
            "time": task.updated_at,
            "level": level,
            "message": message,
            "data": data or {},
        }
        task.logs.append(event)
        self._save()
        for subscriber in list(self._subscribers.get(task_id, set())):
            subscriber(event)

    def subscribe(self, task_id: str, callback: Any) -> None:
        self._subscribers.setdefault(task_id, set()).add(callback)

    def unsubscribe(self, task_id: str, callback: Any) -> None:
        callbacks = self._subscribers.get(task_id)
        if not callbacks:
            return
        callbacks.discard(callback)
        if not callbacks:
            self._subscribers.pop(task_id, None)

    def _require(self, task_id: str) -> TaskRecord:
        task = self.get(task_id)
        if not task:
            raise KeyError(f"unknown task: {task_id}")
        return task

    def _load(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        items = data.get("tasks") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return
        changed = False
        for item in items:
            if not isinstance(item, dict) or not item.get("id") or not item.get("tool"):
                continue
            try:
                record = TaskRecord(
                    id=str(item["id"]),
                    tool=str(item["tool"]),
                    input=item.get("input") if isinstance(item.get("input"), dict) else {},
                    status=str(item.get("status") or "queued"),
                    output=item.get("output") if isinstance(item.get("output"), dict) else None,
                    error=item.get("error") if item.get("error") is not None else None,
                    created_at=str(item.get("created_at") or utc_now()),
                    updated_at=str(item.get("updated_at") or utc_now()),
                    logs=item.get("logs") if isinstance(item.get("logs"), list) else [],
                )
            except (TypeError, ValueError):
                continue
            if record.status in {"queued", "running", "waiting_confirmation"}:
                record.status = "failure"
                record.error = record.error or "task interrupted before runtime startup"
                record.updated_at = utc_now()
                record.logs.append({
                    "time": record.updated_at,
                    "level": "error",
                    "message": record.error,
                    "data": {"reason": "runtime_startup_recovery"},
                })
                changed = True
            self._tasks[record.id] = record
        if changed:
            self._save()

    def _save(self) -> None:
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        records = sorted(self._tasks.values(), key=lambda item: item.created_at)[-200:]
        self.storage_path.write_text(
            json.dumps(
                {
                    "schema_version": TOOL_TASK_STORE_SCHEMA_VERSION,
                    "record_kind": "tool_task_store",
                    "tasks": [item.to_public_dict() for item in records],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


ToolTaskRecord = TaskRecord
ToolTaskStore = TaskStore
