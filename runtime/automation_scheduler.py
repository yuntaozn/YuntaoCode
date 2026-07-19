from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from runtime.automation_runtime import active_runs_for_automation, prepare_automation_run
from runtime.core.automation import automation_is_due


class AutomationScheduler:
    """Lightweight trigger loop for saved automations.

    The scheduler interprets trigger times and creates normal prepared Runs. It
    does not execute tools, call models, or mark tasks complete.
    """

    def __init__(self, runtime: Any, *, interval_seconds: float = 30.0) -> None:
        self.runtime = runtime
        self.interval_seconds = max(1.0, float(interval_seconds))
        self._stopped = False
        self.last_error = ""

    def stop(self) -> None:
        self._stopped = True

    async def start(self) -> None:
        while not self._stopped:
            try:
                await self.tick()
            except Exception as exc:
                # Keep the trigger loop alive. Individual failures remain
                # observable through the automation record and API actions.
                self.last_error = str(exc)[:500]
            await asyncio.sleep(self.interval_seconds)

    async def tick(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        store = getattr(self.runtime, "automations", None)
        if store is None:
            return []
        current = _utc(now)
        results: list[dict[str, Any]] = []
        for automation in store.list():
            if automation.state != "active" or automation.trigger.kind == "manual":
                continue
            if not automation.next_run_at:
                initialized = store.ensure_next_run(automation.id)
                results.append({
                    "automation_id": automation.id,
                    "status": "scheduled",
                    "next_run_at": initialized.next_run_at,
                })
                continue
            if not automation_is_due(automation, now=current):
                continue
            active_runs = active_runs_for_automation(self.runtime, automation.id)
            if active_runs > 0 and automation.concurrency_policy != "allow_parallel":
                if automation.concurrency_policy == "queue_next":
                    results.append({
                        "automation_id": automation.id,
                        "status": "queued",
                        "active_runs": active_runs,
                        "next_run_at": automation.next_run_at,
                    })
                    continue
                updated = store.advance_next_run(automation.id, now=current)
                results.append({
                    "automation_id": automation.id,
                    "status": "skipped_active_run",
                    "active_runs": active_runs,
                    "next_run_at": updated.next_run_at,
                })
                continue
            try:
                data = prepare_automation_run(
                    self.runtime,
                    automation,
                    triggered_by="scheduler",
                    now=current,
                )
            except Exception as exc:
                results.append({
                    "automation_id": automation.id,
                    "status": "failed",
                    "message": str(exc),
                })
                continue
            prepared_run = data.get("prepared_run") if isinstance(data, dict) else {}
            results.append({
                "automation_id": automation.id,
                "status": "prepared_run_created",
                "run_id": prepared_run.get("id") if isinstance(prepared_run, dict) else "",
                "next_run_at": (data.get("automation") or {}).get("next_run_at")
                if isinstance(data.get("automation"), dict)
                else "",
            })
        return results


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
