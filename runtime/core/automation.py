"""自动化 Schema。

自动化是普通 Task Runtime 之上的触发层，不得直接执行工具，
也不得绕过权限、确认、Trace、恢复或 RunResult 验证。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
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
WEEKDAY_INDEX: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


@dataclass(frozen=True)
class AutomationTrigger:
    """计划触发或显式触发定义。

    Runtime 调度器可在之后解释它；Schema 有意不保存可执行代码或直接工具指令。"""

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
    """触发后会成为普通 Task/Run 的用户目标。"""

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
    """返回调度器是否可为该自动化创建普通 Run。"""

    if automation.state != "active":
        return False
    if automation.concurrency_policy == "allow_parallel":
        return True
    return active_runs <= 0


def automation_task_seed(automation: Automation) -> dict[str, Any]:
    """构建 Task/Run 请求种子，但不执行任何操作。"""

    seed = automation.task_template.to_run_request()
    seed["automation_id"] = automation.id
    seed["automation_name"] = automation.name
    seed["trigger"] = automation.trigger.to_dict()
    return seed


def automation_is_due(automation: Automation, *, now: datetime | None = None) -> bool:
    """返回活动计划自动化是否已到期。

    这只是计划证据，不决定是否允许执行；并发、权限、确认和实际工作仍进入普通
    Task/Run 路径。"""

    if automation.state != "active" or automation.trigger.kind == "manual":
        return False
    scheduled = parse_automation_datetime(automation.next_run_at)
    if scheduled is None:
        return False
    return scheduled <= _utc(now)


def automation_next_run_at(
    automation: Automation,
    *,
    now: datetime | None = None,
) -> str:
    """返回自动化下一次运行的 UTC ISO 时间戳；没有时返回空字符串。"""

    next_at = next_automation_run_datetime(automation, now=now)
    if next_at is None:
        return ""
    return next_at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def next_automation_run_datetime(
    automation: Automation,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """计算受支持触发类型的下一次计划时间。"""

    if automation.state not in {"active", "draft"}:
        return None
    trigger = automation.trigger
    current = _utc(now)
    if trigger.kind == "manual":
        return None
    if trigger.kind == "once":
        if automation.last_run_id:
            return None
        run_at = parse_automation_datetime(trigger.run_at)
        return run_at if run_at and run_at > current else None
    if trigger.kind == "interval":
        seconds = max(60, int(trigger.interval_seconds or 0))
        return current + timedelta(seconds=seconds)
    if trigger.kind == "daily":
        scheduled_time = _parse_time_of_day(trigger.time_of_day)
        if scheduled_time is None:
            return None
        return _next_daily_datetime(current, scheduled_time)
    if trigger.kind == "weekly":
        scheduled_time = _parse_time_of_day(trigger.time_of_day)
        if scheduled_time is None:
            return None
        weekdays = [
            WEEKDAY_INDEX[item]
            for item in trigger.days_of_week
            if item in WEEKDAY_INDEX
        ]
        if not weekdays:
            weekdays = [0]
        return _next_weekly_datetime(current, scheduled_time, weekdays)
    return None


def parse_automation_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _next_daily_datetime(current: datetime, scheduled_time: time) -> datetime:
    candidate = current.replace(
        hour=scheduled_time.hour,
        minute=scheduled_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly_datetime(
    current: datetime,
    scheduled_time: time,
    weekdays: list[int],
) -> datetime:
    for offset in range(0, 8):
        candidate_date = current.date() + timedelta(days=offset)
        if candidate_date.weekday() not in weekdays:
            continue
        candidate = datetime.combine(candidate_date, scheduled_time, tzinfo=current.tzinfo)
        if candidate > current:
            return candidate
    return datetime.combine(
        current.date() + timedelta(days=7),
        scheduled_time,
        tzinfo=current.tzinfo,
    )


def _parse_time_of_day(value: Any) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    pieces = text.split(":")
    if len(pieces) < 2:
        return None
    try:
        hour = int(pieces[0])
        minute = int(pieces[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return time(hour=hour, minute=minute)


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
