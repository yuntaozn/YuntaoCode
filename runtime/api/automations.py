from __future__ import annotations

import tornado.web

from runtime.automation_runtime import prepare_automation_run

from .base import ApiHandler


class AutomationsHandler(ApiHandler):
    def get(self) -> None:
        scheduler = getattr(self.runtime, "automation_scheduler", None)
        self.finish_json({
            "success": True,
            "data": [item.to_dict() for item in self.runtime.automations.list()],
            "meta": {
                "scheduler_enabled": scheduler is not None,
                "scheduler_boundary": "prepared_run_only",
                "scheduler_last_error": getattr(scheduler, "last_error", "") if scheduler else "",
            },
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
            try:
                data = prepare_automation_run(self.runtime, automation, triggered_by="manual")
            except RuntimeError as exc:
                raise tornado.web.HTTPError(409, reason=str(exc)) from exc
            except ValueError as exc:
                raise tornado.web.HTTPError(400, reason=str(exc)) from exc
            self.finish_json({"success": True, "data": data})
            return
        raise tornado.web.HTTPError(400, reason="action must be pause, resume, or trigger")
