from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.core.automation import (
    AUTOMATION_SCHEMA_VERSION,
    Automation,
    AutomationTaskTemplate,
    AutomationTrigger,
    automation_next_run_at,
    automation_is_due,
    can_trigger_automation,
)
from runtime.persistence import AtomicJsonDocumentStorage, DocumentStorage
from runtime.run_store import utc_now


AUTOMATION_STORE_SCHEMA_VERSION = "automation_store.v1"
VALID_STATES = {"draft", "active", "paused", "disabled", "archived"}
VALID_TRIGGER_KINDS = {"manual", "once", "interval", "daily", "weekly"}
VALID_CONCURRENCY_POLICIES = {"skip_if_running", "queue_next", "allow_parallel"}


class AutomationStore:
    def __init__(
        self,
        store_path: Path | None = None,
        *,
        storage: DocumentStorage | None = None,
    ) -> None:
        self._storage = storage if storage is not None else AtomicJsonDocumentStorage(store_path)
        self.store_path = self._storage.path
        self._automations: dict[str, Automation] = {}
        self._load()

    def list(self, *, include_archived: bool = False) -> list[Automation]:
        items = list(self._automations.values())
        if not include_archived:
            items = [item for item in items if item.state != "archived"]
        return sorted(items, key=lambda item: item.updated_at or item.created_at, reverse=True)

    def get(self, automation_id: str) -> Automation | None:
        return self._automations.get(automation_id)

    def create(self, payload: dict[str, Any]) -> Automation:
        now = utc_now()
        automation = _automation_from_payload(
            payload,
            automation_id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )
        automation = _with_current_next_run(automation)
        self._automations[automation.id] = automation
        self._save()
        return automation

    def update(self, automation_id: str, payload: dict[str, Any]) -> Automation:
        current = self._require(automation_id)
        merged = current.to_dict()
        _deep_update(merged, payload)
        next_run_at = str(payload.get("next_run_at") or "") if "next_run_at" in payload else current.next_run_at
        if "trigger" in payload and "next_run_at" not in payload:
            next_run_at = ""
        updated = _automation_from_payload(
            merged,
            automation_id=current.id,
            created_at=current.created_at,
            updated_at=utc_now(),
            last_run_id=current.last_run_id,
            next_run_at=next_run_at,
        )
        updated = _with_current_next_run(updated)
        self._automations[automation_id] = updated
        self._save()
        return updated

    def set_state(self, automation_id: str, state: str) -> Automation:
        current = self._require(automation_id)
        normalized = _normalize_choice(state, VALID_STATES, current.state)
        updated = replace(current, state=normalized, updated_at=utc_now())
        self._automations[automation_id] = updated
        self._save()
        return updated

    def delete(self, automation_id: str) -> bool:
        if automation_id not in self._automations:
            return False
        del self._automations[automation_id]
        self._save()
        return True

    def record_prepared_run(self, automation_id: str, run_id: str, *, now: Any = None) -> Automation:
        current = self._require(automation_id)
        updated = replace(current, last_run_id=run_id, updated_at=utc_now())
        updated = replace(updated, next_run_at=automation_next_run_at(updated, now=now))
        self._automations[automation_id] = updated
        self._save()
        return updated

    def can_trigger(self, automation_id: str, *, active_runs: int = 0) -> bool:
        return can_trigger_automation(self._require(automation_id), active_runs=active_runs)

    def due(self) -> list[Automation]:
        return [
            item for item in self.list()
            if automation_is_due(item)
        ]

    def ensure_next_run(self, automation_id: str) -> Automation:
        current = self._require(automation_id)
        updated = _with_current_next_run(current, force=True)
        if updated != current:
            self._automations[automation_id] = updated
            self._save()
        return updated

    def advance_next_run(self, automation_id: str, *, now: Any = None) -> Automation:
        current = self._require(automation_id)
        updated = replace(current, next_run_at=automation_next_run_at(current, now=now), updated_at=utc_now())
        self._automations[automation_id] = updated
        self._save()
        return updated

    def _require(self, automation_id: str) -> Automation:
        automation = self.get(automation_id)
        if not automation:
            raise KeyError(f"unknown automation: {automation_id}")
        return automation

    def _load(self) -> None:
        value = self._storage.load()
        items = value.get("automations") if isinstance(value, dict) else []
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict):
                automation = _automation_from_payload(item)
                self._automations[automation.id] = automation

    def _save(self) -> None:
        self._storage.save({
            "schema_version": AUTOMATION_STORE_SCHEMA_VERSION,
            "automations": [item.to_dict() for item in self._automations.values()],
        })


def _automation_from_payload(
    payload: dict[str, Any],
    *,
    automation_id: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
    last_run_id: str | None = None,
    next_run_at: str | None = None,
) -> Automation:
    trigger_payload = payload.get("trigger") if isinstance(payload.get("trigger"), dict) else {}
    template_payload = payload.get("task_template") if isinstance(payload.get("task_template"), dict) else payload
    goal = str(template_payload.get("goal") or payload.get("goal") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not name:
        name = goal[:32] or "未命名自动化"
    if not goal:
        raise ValueError("task goal is required")

    trigger = AutomationTrigger(
        kind=_normalize_choice(trigger_payload.get("kind"), VALID_TRIGGER_KINDS, "manual"),  # type: ignore[arg-type]
        timezone=str(trigger_payload.get("timezone") or "local"),
        run_at=str(trigger_payload.get("run_at") or ""),
        interval_seconds=_safe_int(trigger_payload.get("interval_seconds"), 0),
        days_of_week=tuple(
            str(item).strip().lower()
            for item in trigger_payload.get("days_of_week", [])
            if str(item or "").strip()
        ) if isinstance(trigger_payload.get("days_of_week"), list) else (),
        time_of_day=str(trigger_payload.get("time_of_day") or ""),
        metadata=_dict(trigger_payload.get("metadata")),
    )
    task_template = AutomationTaskTemplate(
        goal=goal,
        workspace_id=str(template_payload.get("workspace_id") or payload.get("workspace_id") or ""),
        conversation_id=str(template_payload.get("conversation_id") or payload.get("conversation_id") or ""),
        model=str(template_payload.get("model") or payload.get("model") or ""),
        planning_policy=str(template_payload.get("planning_policy") or payload.get("planning_policy") or "auto"),
        confirmation_policy=str(template_payload.get("confirmation_policy") or payload.get("confirmation_policy") or "auto"),
        access_scope=str(template_payload.get("access_scope") or payload.get("access_scope") or "project_only"),
        metadata=_dict(template_payload.get("metadata")),
    )
    now = utc_now()
    return Automation(
        id=str(automation_id or payload.get("id") or uuid4()),
        name=name,
        description=str(payload.get("description") or ""),
        state=_normalize_choice(payload.get("state"), VALID_STATES, "active"),  # type: ignore[arg-type]
        concurrency_policy=_normalize_choice(
            payload.get("concurrency_policy"),
            VALID_CONCURRENCY_POLICIES,
            "skip_if_running",
        ),  # type: ignore[arg-type]
        trigger=trigger,
        task_template=task_template,
        last_run_id=str(last_run_id if last_run_id is not None else payload.get("last_run_id") or ""),
        next_run_at=str(next_run_at if next_run_at is not None else payload.get("next_run_at") or ""),
        created_at=str(created_at or payload.get("created_at") or now),
        updated_at=str(updated_at or payload.get("updated_at") or now),
        metadata=_dict(payload.get("metadata")),
    )


def _with_current_next_run(automation: Automation, *, force: bool = False) -> Automation:
    if automation.trigger.kind == "manual":
        next_run_at = ""
    elif automation.next_run_at and not force:
        next_run_at = automation.next_run_at
    else:
        next_run_at = automation_next_run_at(automation)
    if next_run_at == automation.next_run_at:
        return automation
    return replace(automation, next_run_at=next_run_at, updated_at=utc_now())


def _normalize_choice(value: Any, allowed: set[str], fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else fallback


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _deep_update(target: dict[str, Any], payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
