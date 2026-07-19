from __future__ import annotations

from typing import Any


ACTIVE_AUTOMATION_RUN_STATUSES = {"created", "running", "waiting_confirmation", "paused"}


def active_runs_for_automation(runtime: Any, automation_id: str) -> int:
    """Return active normal Runs linked to an automation."""

    count = 0
    for run in runtime.runs.list():
        if run.status not in ACTIVE_AUTOMATION_RUN_STATUSES:
            continue
        task = runtime.product_tasks.get(run.task_id) if run.task_id else None
        metadata = getattr(task, "metadata", {}) if task else {}
        if metadata.get("automation_id") == automation_id:
            count += 1
    return count


def prepare_automation_run(
    runtime: Any,
    automation: Any,
    *,
    triggered_by: str = "manual",
    now: Any = None,
) -> dict[str, Any]:
    """Create a normal prepared Run from an automation task template.

    The helper creates Task/Run records only. It does not call models, tools, or
    providers; starting the prepared Run still uses the normal conversation
    message stream path.
    """

    if not runtime.automations.can_trigger(
        automation.id,
        active_runs=active_runs_for_automation(runtime, automation.id),
    ):
        raise RuntimeError("automation already has an active run")

    template = automation.task_template
    workspace_id = str(template.workspace_id or "")
    if workspace_id and not runtime.workspaces.get(workspace_id):
        raise ValueError("workspace not found")
    if not workspace_id:
        workspaces = runtime.workspaces.list()
        if not workspaces:
            raise ValueError("workspace is required")
        workspace_id = workspaces[0].id

    conversation_id = str(template.conversation_id or "")
    conversation = runtime.conversations.get(conversation_id) if conversation_id else None
    if not conversation or conversation.workspace_id != workspace_id:
        conversation = runtime.conversations.create(
            workspace_id,
            title=automation.name,
            mode="terminal",
        )
        conversation_id = conversation.id

    product_task = runtime.product_tasks.create(
        goal=template.goal,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        kind="automation_task",
        metadata={
            "source": "automation",
            "automation_id": automation.id,
            "automation_name": automation.name,
            "triggered_by": triggered_by,
            "trigger_kind": automation.trigger.kind,
        },
    )
    run = runtime.runs.create(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        mode="terminal",
        user_content=template.goal,
        task_id=product_task.id,
        status="created",
    )
    runtime.product_tasks.attach_run(product_task.id, run.id, state="created")
    updated = runtime.automations.record_prepared_run(automation.id, run.id, now=now)
    runtime.run_events.emit(run.id, {
        "event": "automation",
        "automation_id": automation.id,
        "automation_name": automation.name,
        "triggered_by": triggered_by,
        "trigger_kind": automation.trigger.kind,
        "message": "automation prepared a normal run",
    })
    prepared_run = run.to_public_dict()
    prepared_run["goal"] = template.goal
    return {
        "automation": updated.to_dict(),
        "prepared_run": prepared_run,
        "boundary": "explicit_start_required",
        "triggered_by": triggered_by,
    }
