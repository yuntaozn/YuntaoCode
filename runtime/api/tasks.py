from __future__ import annotations

import tornado.web

from .base import ApiHandler


class TasksHandler(ApiHandler):
    """产品级 Task 集合 API。"""

    def get(self) -> None:
        workspace_id = self.get_argument("workspace_id", None)
        conversation_id = self.get_argument("conversation_id", None)
        state = self.get_argument("state", None)
        tasks = self.runtime.product_tasks.list(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            state=state,
        )
        self.finish_json({
            "success": True,
            "data": [task.to_dict() for task in tasks],
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise tornado.web.HTTPError(400, reason="goal is required")
        workspace_id = str(payload.get("workspace_id") or "").strip()
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if workspace_id and not self.runtime.workspaces.get(workspace_id):
            raise tornado.web.HTTPError(404, reason="workspace not found")
        if conversation_id and not self.runtime.conversations.get(conversation_id):
            raise tornado.web.HTTPError(404, reason="conversation not found")
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        task = self.runtime.product_tasks.create(
            goal=goal,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            kind=str(payload.get("kind") or ""),
            metadata=metadata,
        )
        self.finish_json({"success": True, "data": task.to_dict()})


class TaskDetailHandler(ApiHandler):
    def get(self, task_id: str) -> None:
        task = self.runtime.product_tasks.get(task_id)
        if not task:
            raise tornado.web.HTTPError(404, reason="task not found")
        data = task.to_dict()
        data["runs"] = [
            run.to_public_dict()
            for run in self.runtime.runs.list(task_id=task_id)
        ]
        data["checkpoints"] = self.runtime.product_tasks.list_checkpoints(task_id=task_id)
        data["context_snapshots"] = self.runtime.product_tasks.list_context_snapshots(task_id=task_id)
        self.finish_json({"success": True, "data": data})
