from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .persistence import AtomicJsonDocumentStorage, DocumentStorage
from .run_repository import JsonRunRepository, RunRepository, SqliteRunRepository


RUN_STORE_SCHEMA_VERSION = "0.1"
RUN_RECORD_SCHEMA_VERSION = "0.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    id: str
    conversation_id: str
    workspace_id: str
    mode: str
    user_content: str
    task_id: str = ""
    parent_run_id: str = ""
    source_run_id: str = ""
    attempt: int = 1
    resume_from_checkpoint_id: str = ""
    status: str = "running"
    stage: str = "created"
    message: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    events: list[dict[str, Any]] = field(default_factory=list)
    stored_event_count: int | None = field(default=None, repr=False)

    def to_public_dict(self, include_events: bool = False) -> dict[str, Any]:
        data = {
            "schema_version": RUN_RECORD_SCHEMA_VERSION,
            "record_kind": "run",
            "id": self.id,
            "conversation_id": self.conversation_id,
            "workspace_id": self.workspace_id,
            "mode": self.mode,
            "user_content": self.user_content,
            "task_id": self.task_id,
            "parent_run_id": self.parent_run_id,
            "source_run_id": self.source_run_id,
            "attempt": self.attempt,
            "resume_from_checkpoint_id": self.resume_from_checkpoint_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "event_count": self.stored_event_count if self.stored_event_count is not None else len(self.events),
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
            task_id=str(value.get("task_id") or ""),
            parent_run_id=str(value.get("parent_run_id") or ""),
            source_run_id=str(value.get("source_run_id") or ""),
            attempt=max(1, int(value.get("attempt") or 1)),
            resume_from_checkpoint_id=str(value.get("resume_from_checkpoint_id") or ""),
            status=str(value.get("status") or "running"),
            stage=str(value.get("stage") or "created"),
            message=str(value.get("message") or ""),
            created_at=str(value.get("created_at") or utc_now()),
            updated_at=str(value.get("updated_at") or utc_now()),
            events=value.get("events") if isinstance(value.get("events"), list) else [],
            stored_event_count=int(value["event_count"]) if isinstance(value.get("event_count"), int) else None,
        )


class RunStore:
    def __init__(
        self,
        store_path: Path | None = None,
        *,
        keep_runs: int = 200,
        keep_events: int = 300,
        storage: DocumentStorage | None = None,
        repository: RunRepository | None = None,
    ) -> None:
        self.keep_runs = keep_runs
        self.keep_events = keep_events
        if repository is not None:
            self._repository = repository
        else:
            document_storage = storage if storage is not None else AtomicJsonDocumentStorage(store_path)
            self._repository = JsonRunRepository(document_storage, keep_runs=keep_runs)
        self.store_path = self._repository.path
        self._recover_interrupted()

    @classmethod
    def sqlite(
        cls,
        database_path: Path,
        *,
        legacy_store_path: Path | None = None,
        keep_runs: int = 200,
        keep_events: int = 300,
    ) -> "RunStore":
        repository = SqliteRunRepository(
            database_path,
            keep_runs=keep_runs,
            keep_events=keep_events,
        )
        if legacy_store_path is not None:
            repository.import_legacy_document(AtomicJsonDocumentStorage(legacy_store_path))
        return cls(
            keep_runs=keep_runs,
            keep_events=keep_events,
            repository=repository,
        )

    def create(
        self,
        *,
        conversation_id: str,
        workspace_id: str,
        mode: str,
        user_content: str,
        task_id: str = "",
        parent_run_id: str = "",
        source_run_id: str = "",
        attempt: int = 1,
        resume_from_checkpoint_id: str = "",
        status: str = "running",
    ) -> RunRecord:
        record = RunRecord(
            id=str(uuid4()),
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            mode=mode,
            user_content=user_content[:500],
            task_id=task_id,
            parent_run_id=parent_run_id,
            source_run_id=source_run_id,
            attempt=max(1, int(attempt or 1)),
            resume_from_checkpoint_id=resume_from_checkpoint_id,
            status=status,
            stage="created",
            message="run created",
        )
        self._repository.create(record.to_public_dict(include_events=True))
        return record

    def get(self, run_id: str) -> RunRecord | None:
        value = self._repository.get(run_id)
        return RunRecord.from_dict(value) if value else None

    def list(
        self,
        *,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
        task_id: str | None = None,
        status: str | None = None,
    ) -> list[RunRecord]:
        return [
            RunRecord.from_dict(item)
            for item in self._repository.list(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                task_id=task_id,
                status=status,
            )
        ]

    def record_event(self, run_id: str, event: dict[str, Any]) -> RunRecord | None:
        run = self.get(run_id)
        if not run:
            return None
        event_type = str(event.get("event") or "")
        stored_event = {"time": utc_now(), **event}
        run.events.append(stored_event)
        run.events = run.events[-self.keep_events:]
        run.stored_event_count = len(run.events)

        if event_type == "status":
            incoming_status = str(event.get("status") or "").strip()
            incoming_message = str(event.get("message") or "").strip()
            if run.status == "paused" and incoming_status not in {"resumed", "stopping", "cancelled"}:
                run.stage = "paused"
                run.message = incoming_message or run.message
            else:
                run.stage = incoming_status or run.stage
                run.message = incoming_message or run.message
            if run.stage == "paused":
                run.status = "paused"
            elif run.stage == "resumed":
                run.status = "running"
            elif run.stage in {"tool_contract_failed", "error"}:
                run.status = "failure"
            elif run.stage in {"max_tool_rounds", "recon_budget_exhausted", "stopped", "cancelled"}:
                run.status = "stopped"
            elif run.status == "waiting_confirmation" and run.stage in {"resumed", "stopping"}:
                run.status = "running"
            elif run.status == "waiting_confirmation" and run.stage not in {"resumed", "stopping"}:
                pass
            if run.status not in {"failure", "success", "stopped", "waiting_confirmation", "paused"}:
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
            run.message = str(event.get("error") or "run failed")
            if event.get("terminal") is False or event.get("recoverable") is True:
                run.stage = "model_error"
                if run.status not in {"waiting_confirmation", "paused"}:
                    run.status = "running"
            else:
                run.status = "failure"
                run.stage = "error"
        elif event_type == "done":
            run.status = str(event.get("run_status") or "success")
            run.stage = "done"
            run.message = "run completed"
        elif event_type == "result":
            run.stage = "result"
            result = event.get("result") if isinstance(event.get("result"), dict) else {}
            status = str(result.get("status") or "").strip()
            run.message = f"result {status}".strip()
            if status in {"success", "failure", "partial", "stopped"}:
                run.status = status
        elif event_type == "checkpoint":
            run.stage = "checkpoint"
            run.message = "checkpoint created"
        elif event_type == "context_pack":
            run.stage = "context_pack"
            run.message = "context pack recorded"
        elif event_type == "visual_context":
            run.stage = "visual_context"
            run.message = "visual context recorded"
        elif event_type == "workspace_snapshot":
            run.stage = "workspace_snapshot"
            run.message = "workspace snapshot recorded"
        elif event_type == "capability_snapshot":
            run.stage = "capability_snapshot"
            preflight = event.get("preflight") if isinstance(event.get("preflight"), dict) else {}
            if preflight.get("ok") is False:
                run.message = "capability preflight advisory"
            else:
                run.message = "capability preflight ok"
        elif event_type in {"plan", "plan_decision", "plan_step", "changes"}:
            run.stage = event_type
            run.message = event_type

        run.updated_at = utc_now()
        self._repository.append_event(
            run.to_public_dict(include_events=True),
            stored_event,
        )
        return run

    def close(self) -> None:
        self._repository.close()

    def _recover_interrupted(self) -> None:
        for status in ("running", "waiting_confirmation", "paused"):
            for value in self._repository.list(status=status):
                record = RunRecord.from_dict(value)
                record.status = "stopped"
                record.stage = "interrupted"
                record.message = "run interrupted before runtime startup"
                record.updated_at = utc_now()
                self._repository.update(record.to_public_dict(include_events=True))
