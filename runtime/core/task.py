"""Product-level task schemas.

These records describe the user-goal task model, not one local tool invocation.
The historical /tasks API still stores ToolTask records in runtime.task_store.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal


TASK_SCHEMA_VERSION = "task.v1"
PLAN_SCHEMA_VERSION = "plan.v1"
STEP_SCHEMA_VERSION = "step.v1"

TaskState = Literal[
    "created",
    "planning",
    "running",
    "waiting_confirmation",
    "verifying",
    "completed",
    "failed",
    "cancelled",
    "paused",
    "resuming",
]

StepState = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
]

TASK_STATES: frozenset[str] = frozenset(TaskState.__args__)  # type: ignore[attr-defined]
STEP_STATES: frozenset[str] = frozenset(StepState.__args__)  # type: ignore[attr-defined]

TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"planning", "running", "waiting_confirmation", "completed", "failed", "cancelled"}),
    "planning": frozenset({"running", "waiting_confirmation", "failed", "cancelled", "paused"}),
    "running": frozenset({"waiting_confirmation", "verifying", "completed", "failed", "cancelled", "paused"}),
    "waiting_confirmation": frozenset({"running", "cancelled", "failed", "paused"}),
    "verifying": frozenset({"running", "completed", "failed", "cancelled", "paused"}),
    "paused": frozenset({"resuming", "cancelled"}),
    "resuming": frozenset({"running", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset({"resuming"}),
    "cancelled": frozenset(),
}


@dataclass(frozen=True)
class ProductTask:
    """A user-goal task record.

    This is intentionally separate from ToolTask so future task state, trace,
    recovery, and replay do not overload one tool invocation record.
    """

    id: str
    goal: str
    conversation_id: str = ""
    workspace_id: str = ""
    kind: str = ""
    state: TaskState = "created"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TASK_SCHEMA_VERSION,
            "record_kind": "task",
            "id": self.id,
            "goal": self.goal,
            "conversation_id": self.conversation_id,
            "workspace_id": self.workspace_id,
            "kind": self.kind,
            "state": self.state,
            "metadata": dict(self.metadata),
        }

    def transition(self, target: TaskState) -> "ProductTask":
        if not can_transition(self.state, target):
            raise ValueError(f"invalid task transition: {self.state} -> {target}")
        return replace(self, state=target)


@dataclass(frozen=True)
class TaskStep:
    id: str
    title: str
    description: str = ""
    state: StepState = "pending"
    tool_hint: str = ""
    result_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STEP_SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "state": self.state,
            "tool_hint": self.tool_hint,
            "result_ref": self.result_ref,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TaskPlan:
    id: str
    task_id: str
    title: str
    steps: tuple[TaskStep, ...] = field(default_factory=tuple)
    state: str = "draft"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "state": self.state,
            "steps": [step.to_dict() for step in self.steps],
            "metadata": dict(self.metadata),
        }


def can_transition(current: str, target: str) -> bool:
    if current not in TASK_STATES or target not in TASK_STATES:
        return False
    return target in TASK_TRANSITIONS[current]
