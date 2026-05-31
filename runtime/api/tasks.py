from __future__ import annotations

import tornado.web

from .base import ApiHandler
from runtime.agent_strategy.classifiers import canonical_tool_id


class TasksHandler(ApiHandler):
    async def post(self) -> None:
        payload = self.parse_json_body()
        tool_id = payload.get("tool")
        if not tool_id:
            raise tornado.web.HTTPError(400, reason="tool is required")
        tool_id = canonical_tool_id(tool_id)
        try:
            tool_spec = self.runtime.registry.get(tool_id).spec
        except KeyError:
            raise tornado.web.HTTPError(404, reason=f"unknown tool: {tool_id}")
        if not self.runtime.settings.is_tool_enabled(tool_id):
            raise tornado.web.HTTPError(403, reason=f"plugin is disabled for tool: {tool_id}")
        input_data = payload.get("input") or {}
        if not isinstance(input_data, dict):
            raise tornado.web.HTTPError(400, reason="input must be an object")
        workspace_path = None
        workspace_id = str(payload.get("workspace_id") or "").strip()
        if workspace_id:
            workspace = self.runtime.workspaces.get(workspace_id)
            if not workspace:
                raise tornado.web.HTTPError(404, reason="workspace not found")
            workspace_path = workspace.path
        confirmed = bool(payload.get("confirmed"))
        if tool_spec.requires_confirmation and not confirmed:
            task = await self.runtime.runner.submit(
                tool_id,
                input_data,
                wait=False,
                confirmed=False,
                workspace_path=workspace_path,
            )
            self.set_status(409)
            self.finish_json({
                "success": False,
                "error": "tool requires confirmation",
                "data": task.to_public_dict() | {"tool_spec": tool_spec.to_public_dict()},
            })
            return

        task = await self.runtime.runner.submit(
            tool_id,
            input_data,
            wait=bool(payload.get("wait")),
            confirmed=confirmed,
            workspace_path=workspace_path,
        )
        self.finish_json({
            "success": task.status != "failure",
            "data": task.to_public_dict(),
        })


class TaskDetailHandler(ApiHandler):
    def get(self, task_id: str) -> None:
        task = self.runtime.store.get(task_id)
        if not task:
            raise tornado.web.HTTPError(404, reason="task not found")
        self.finish_json({
            "success": task.status != "failure",
            "data": task.to_public_dict(),
        })
