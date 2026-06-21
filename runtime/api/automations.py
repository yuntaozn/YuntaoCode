from __future__ import annotations

from typing import Any

import tornado.web

from .base import ApiHandler


class AutomationsHandler(ApiHandler):
    def get(self) -> None:
        self.finish_json({
            "success": True,
            "data": [item.to_dict() for item in self.runtime.automations.list()],
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        try:
            automation = self.runtime.automations.create(payload)
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.finish_json({"success": True, "data": automation.to_dict()})


class AutomationDetailHandler(ApiHandler):
    def put(self, automation_id: str) -> None:
        payload = self.parse_json_body()
        if not self.runtime.automations.get(automation_id):
            raise tornado.web.HTTPError(404, reason="automation not found")
        try:
            automation = self.runtime.automations.update(automation_id, payload)
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.finish_json({"success": True, "data": automation.to_dict()})

    def delete(self, automation_id: str) -> None:
        if not self.runtime.automations.delete(automation_id):
            raise tornado.web.HTTPError(404, reason="automation not found")
        self.finish_json({"success": True, "data": {"deleted": automation_id}})


class AutomationActionHandler(ApiHandler):
    def post(self, automation_id: str) -> None:
        payload = self.parse_json_body()
        action = str(payload.get("action") or "").strip().lower()
        automation = self.runtime.automations.get(automation_id)
        if not automation:
            raise tornado.web.HTTPError(404, reason="automation not found")

        if action == "pause":
            updated = self.runtime.automations.set_state(automation_id, "paused")
            self.finish_json({"success": True, "data": updated.to_dict()})
            return
        if action == "resume":
            updated = self.runtime.automations.set_state(automation_id, "active")
            self.finish_json({"success": True, "data": updated.to_dict()})
            return
        if action == "trigger":
            self.finish_json({"success": True, "data": self._prepare_run(automation)})
            return
        raise tornado.web.HTTPError(400, reason="action must be pause, resume, or trigger")

    def _prepare_run(self, automation: Any) -> dict[str, Any]:
        active_runs = _active_runs_for_automation(self.runtime, automation.id)
        if not self.runtime.automations.can_trigger(automation.id, active_runs=active_runs):
            raise tornado.web.HTTPError(409, reason="automation already has an active run")

        template = automation.task_template
        workspace_id = str(template.workspace_id or "")
        if workspace_id and not self.runtime.workspaces.get(workspace_id):
            raise tornado.web.HTTPError(404, reason="workspace not found")
        if not workspace_id:
            workspaces = self.runtime.workspaces.list()
            if not workspaces:
                raise tornado.web.HTTPError(400, reason="workspace is required")
            workspace_id = workspaces[0].id

        conversation_id = str(template.conversation_id or "")
        conversation = self.runtime.conversations.get(conversation_id) if conversation_id else None
        if not conversation or conversation.workspace_id != workspace_id:
            conversation = self.runtime.conversations.create(
                workspace_id,
                title=automation.name,
                mode="terminal",
            )
            conversation_id = conversation.id

        product_task = self.runtime.product_tasks.create(
            goal=template.goal,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            kind="automation_task",
            metadata={
                "source": "automation",
                "automation_id": automation.id,
                "automation_name": automation.name,
            },
        )
        run = self.runtime.runs.create(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            mode="terminal",
            user_content=template.goal,
            task_id=product_task.id,
            status="created",
        )
        self.runtime.product_tasks.attach_run(product_task.id, run.id, state="created")
        updated = self.runtime.automations.record_prepared_run(automation.id, run.id)
        prepared_run = run.to_public_dict()
        prepared_run["goal"] = template.goal
        return {
            "automation": updated.to_dict(),
            "prepared_run": prepared_run,
            "boundary": "explicit_start_required",
        }


def _active_runs_for_automation(runtime: Any, automation_id: str) -> int:
    active_statuses = {"created", "running", "waiting_confirmation", "paused"}
    count = 0
    for run in runtime.runs.list():
        if run.status not in active_statuses:
            continue
        task = runtime.product_tasks.get(run.task_id) if run.task_id else None
        metadata = getattr(task, "metadata", {}) if task else {}
        if metadata.get("automation_id") == automation_id:
            count += 1
    return count
