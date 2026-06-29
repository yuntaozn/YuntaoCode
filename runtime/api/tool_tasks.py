from __future__ import annotations

from typing import Any

import tornado.web

from .base import ApiHandler
from runtime.agent_strategy.confirmation_policy import decide_tool_confirmation
from runtime.agent_strategy.classifiers import canonical_tool_id


class ToolTasksHandler(ApiHandler):
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
        if not self.runtime.is_tool_available(self.runtime.registry.get_public_spec(tool_id)):
            raise tornado.web.HTTPError(409, reason=f"capability service unavailable: {tool_id}")
        input_data = payload.get("input") or {}
        if not isinstance(input_data, dict):
            raise tornado.web.HTTPError(400, reason="input must be an object")
        input_data = self.runtime.registry.normalize_input_data(tool_id, input_data)
        missing_fields = self.runtime.registry.missing_required_input_fields(tool_id, input_data)
        if missing_fields:
            raise tornado.web.HTTPError(
                400,
                reason=f"missing required tool input: {', '.join(missing_fields)}",
            )
        workspace_path = None
        workspace_id = str(payload.get("workspace_id") or "").strip()
        if workspace_id:
            workspace = self.runtime.workspaces.get(workspace_id)
            if not workspace:
                raise tornado.web.HTTPError(404, reason="workspace not found")
            workspace_path = workspace.path
        confirmed = bool(payload.get("confirmed"))
        confirmation_decision = decide_tool_confirmation(
            self.runtime.settings.get_confirmation_policy(),
            tool_id,
            declared_confirmation=bool(tool_spec.requires_confirmation),
        )
        if confirmation_decision.requires_confirmation and not confirmed:
            try:
                task = await self.runtime.runner.submit(
                    tool_id,
                    input_data,
                    wait=False,
                    confirmed=False,
                    workspace_path=workspace_path,
                    workspace_id=workspace_id,
                )
            except PermissionError as exc:
                raise tornado.web.HTTPError(403, reason=str(exc)) from exc
            self.set_status(409)
            self.finish_json({
                "success": False,
                "error": "tool requires confirmation",
                "data": _tool_task_public_dict(task) | {
                    "tool_spec": tool_spec.to_public_dict(),
                    "confirmation_decision": confirmation_decision.to_dict(),
                },
            })
            return

        effective_confirmed = confirmed or not confirmation_decision.requires_confirmation
        try:
            task = await self.runtime.runner.submit(
                tool_id,
                input_data,
                wait=bool(payload.get("wait")),
                confirmed=effective_confirmed,
                workspace_path=workspace_path,
                workspace_id=workspace_id,
            )
        except PermissionError as exc:
            raise tornado.web.HTTPError(403, reason=str(exc)) from exc
        self.finish_json({
            "success": task.status != "failure",
            "data": _tool_task_public_dict(task),
        })


class ToolTaskDetailHandler(ApiHandler):
    def get(self, task_id: str) -> None:
        task = self.runtime.tool_tasks.get(task_id)
        if not task:
            raise tornado.web.HTTPError(404, reason="tool task not found")
        self.finish_json({
            "success": task.status != "failure",
            "data": _tool_task_public_dict(task),
        })


def _tool_task_public_dict(task: Any) -> dict[str, Any]:
    data = task.to_public_dict()
    normalized_error = _normalized_tool_task_error(data)
    if normalized_error:
        data["error"] = normalized_error
    return data


def _normalized_tool_task_error(data: dict[str, Any]) -> str:
    if str(data.get("tool") or "") != "shell.run_command":
        return ""
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    if output.get("timed_out") is not True:
        return ""
    input_data = data.get("input") if isinstance(data.get("input"), dict) else {}
    timeout = output.get("timeout") or input_data.get("timeout")
    message = f"command timed out after {timeout}s" if timeout else "command timed out"
    detail = str(output.get("stderr") or output.get("stdout") or "").strip()
    return f"{message}: {detail}" if detail else message
