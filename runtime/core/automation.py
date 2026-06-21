"""Automation schemas.

Automation is a trigger layer above the normal Task Runtime. It must not
execute tools directly or bypass permissions, confirmations, trace, recovery,
or RunResult verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AUTOMATION_SCHEMA_VERSION = "automation.v1"
AUTOMATION_TRIGGER_SCHEMA_VERSION = "automation_trigger.v1"
AUTOMATION_TASK_TEMPLATE_SCHEMA_VERSION = "automation_task_template.v1"
AUTOMATION_RUN_SCHEMA_VERSION = "automation_run.v1"

AutomationState = Literal["draft", "active", "paused", "disabled", "archived"]
AutomationTriggerKind = Literal["manual", "once", "interval", "daily", "weekly"]
AutomationRunState = Literal["created", "running", "success", "failure", "skipped"]
ConcurrencyPolicy = Literal["skip_if_running", "queue_next", "allow_parallel"]

AUTOMATION_STATES: frozenset[str] = frozenset(AutomationState.__args__)  # type: ignore[attr-defined]
TRIGGER_KINDS: frozenset[str] = frozenset(AutomationTriggerKind.__args__)  # type: ignore[attr-defined]
CONCURRENCY_POLICIES: frozenset[str] = frozenset(ConcurrencyPolicy.__args__)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class AutomationTrigger:
    """A schedule or explicit trigger definition.

    The runtime scheduler can interpret this later. The schema deliberately
    avoids storing executable code or direct tool instructions.
    """

    kind: AutomationTriggerKind
    timezone: str = "local"
    run_at: str = ""
    interval_seconds: int = 0
    days_of_week: tuple[str, ...] = field(default_factory=tuple)
    time_of_day: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUTOMATION_TRIGGER_SCHEMA_VERSION,
            "kind": self.kind,
            "timezone": self.timezone,
            "run_at": self.run_at,
            "interval_seconds": self.interval_seconds,
            "days_of_week": list(self.days_of_week),
            "time_of_day": self.time_of_day,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AutomationTaskTemplate:
    """A user goal that will become a normal Task/Run when triggered."""

    goal: str
    workspace_id: str = ""
    conversation_id: str = ""
    model: str = ""
    planning_policy: str = "auto"
    confirmation_policy: str = "auto"
    access_scope: str = "project_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUTOMATION_TASK_TEMPLATE_SCHEMA_VERSION,
            "goal": self.goal,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "model": self.model,
            "planning_policy": self.planning_policy,
            "confirmation_policy": self.confirmation_policy,
            "access_scope": self.access_scope,
            "metadata": dict(self.metadata),
        }

    def to_run_request(self) -> dict[str, Any]:
        return {
            "content": self.goal,
            "model": self.model,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "planning_policy": self.planning_policy,
            "confirmation_policy": self.confirmation_policy,
            "access_scope": self.access_scope,
            "automation_triggered": True,
        }


@dataclass(frozen=True)
class Automation:
    id: str
    name: str
    trigger: AutomationTrigger
    task_template: AutomationTaskTemplate
    state: AutomationState = "draft"
    concurrency_policy: ConcurrencyPolicy = "skip_if_running"
    description: str = ""
    last_run_id: str = ""
    next_run_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUTOMATION_SCHEMA_VERSION,
            "record_kind": "automation",
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "state": self.state,
            "concurrency_policy": self.concurrency_policy,
            "trigger": self.trigger.to_dict(),
            "task_template": self.task_template.to_dict(),
            "last_run_id": self.last_run_id,
            "next_run_at": self.next_run_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AutomationRun:
    automation_id: str
    run_id: str
    state: AutomationRunState = "created"
    triggered_at: str = ""
    finished_at: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUTOMATION_RUN_SCHEMA_VERSION,
            "record_kind": "automation_run",
            "automation_id": self.automation_id,
            "run_id": self.run_id,
            "state": self.state,
            "triggered_at": self.triggered_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "metadata": dict(self.metadata),
        }


def can_trigger_automation(automation: Automation, *, active_runs: int = 0) -> bool:
    """Return whether a scheduler may create a normal Run for this automation."""

    if automation.state != "active":
        return False
    if automation.concurrency_policy == "allow_parallel":
        return True
    return active_runs <= 0


def automation_task_seed(automation: Automation) -> dict[str, Any]:
    """Build the Task/Run request seed without executing anything."""

    seed = automation.task_template.to_run_request()
    seed["automation_id"] = automation.id
    seed["automation_name"] = automation.name
    seed["trigger"] = automation.trigger.to_dict()
    return seed
