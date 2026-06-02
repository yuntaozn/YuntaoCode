from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    id: str
    conversation_id: str
    workspace_id: str
    mode: str
    user_content: str
    status: str = "running"
    stage: str = "created"
    message: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_public_dict(self, include_events: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "workspace_id": self.workspace_id,
            "mode": self.mode,
            "user_content": self.user_content,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "event_count": len(self.events),
        }
        if include_events:
            data["events"] = self.events
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunRecord":
        return cls(
            id=str(value.get("id") or uuid4()),
            conversation_id=str(value.get("conversation_id") or ""),
            workspace_id=str(value.get("workspace_id") or ""),
            mode=str(value.get("mode") or "terminal"),
            user_content=str(value.get("user_content") or ""),
            status=str(value.get("status") or "running"),
            stage=str(value.get("stage") or "created"),
            message=str(value.get("message") or ""),
            created_at=str(value.get("created_at") or utc_now()),
            updated_at=str(value.get("updated_at") or utc_now()),
            events=value.get("events") if isinstance(value.get("events"), list) else [],
        )


class RunStore:
    def __init__(self, store_path: Path | None = None, *, keep_runs: int = 200, keep_events: int = 300) -> None:
        self.store_path = store_path
        self.keep_runs = keep_runs
        self.keep_events = keep_events
        self._runs: dict[str, RunRecord] = {}
        self._load()

    def create(
        self,
        *,
        conversation_id: str,
        workspace_id: str,
        mode: str,
        user_content: str,
    ) -> RunRecord:
        record = RunRecord(
            id=str(uuid4()),
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            mode=mode,
            user_content=user_content[:500],
            message="run created",
        )
        self._runs[record.id] = record
        self._save()
        return record

    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def list(
        self,
        *,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
    ) -> list[RunRecord]:
        runs = list(self._runs.values())
        if conversation_id:
            runs = [item for item in runs if item.conversation_id == conversation_id]
        if workspace_id:
            runs = [item for item in runs if item.workspace_id == workspace_id]
        if status:
            runs = [item for item in runs if item.status == status]
        return sorted(runs, key=lambda item: item.updated_at, reverse=True)

    def record_event(self, run_id: str, event: dict[str, Any]) -> RunRecord | None:
        run = self.get(run_id)
        if not run:
            return None
        event_type = str(event.get("event") or "")
        run.events.append({"time": utc_now(), **event})
        run.events = run.events[-self.keep_events:]

        if event_type == "status":
            run.stage = str(event.get("status") or run.stage)
            run.message = str(event.get("message") or run.message)
            if run.stage in {"tool_contract_failed", "error"}:
                run.status = "failure"
            elif run.stage in {"max_tool_rounds", "recon_budget_exhausted"}:
                run.status = "stopped"
            elif run.status in {"waiting_confirmation"}:
                run.status = "running"
            if run.status not in {"failure", "success", "stopped"}:
                run.status = "running"
        elif event_type == "tool":
            run.stage = "tool"
            label = event.get("name") or event.get("tool") or ""
            tool_status = event.get("status") or ""
            run.message = f"{tool_status} {label}".strip()
            if tool_status == "failure":
                run.status = "running"
        elif event_type == "confirm":
            run.status = "waiting_confirmation"
            run.stage = "waiting_confirmation"
            run.message = str(event.get("message") or "waiting for confirmation")
        elif event_type == "error":
            run.status = "failure"
            run.stage = "error"
            run.message = str(event.get("error") or "run failed")
        elif event_type == "done":
            run.status = str(event.get("run_status") or "success")
            run.stage = "done"
            run.message = "run completed"
        elif event_type in {"plan", "plan_decision", "plan_step", "changes"}:
            run.stage = event_type
            run.message = event_type

        run.updated_at = utc_now()
        self._save()
        return run

    def _load(self) -> None:
        if not self.store_path or not self.store_path.exists():
            return
        try:
            value = json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        runs = value.get("runs") if isinstance(value, dict) else []
        if not isinstance(runs, list):
            return
        changed = False
        for item in runs:
            if isinstance(item, dict):
                record = RunRecord.from_dict(item)
                if record.status in {"running", "waiting_confirmation"}:
                    record.status = "stopped"
                    record.stage = "interrupted"
                    record.message = "run interrupted before runtime startup"
                    record.updated_at = utc_now()
                    changed = True
                self._runs[record.id] = record
        if changed:
            self._save()

    def _save(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        records = sorted(self._runs.values(), key=lambda item: item.created_at)[-self.keep_runs:]
        self.store_path.write_text(
            json.dumps(
                {"runs": [item.to_public_dict(include_events=True) for item in records]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
