from __future__ import annotations

import json
from typing import Any

import tornado.websocket


class LogsWebSocketHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, runtime: Any) -> None:
        self.runtime = runtime
        self.task_id: str | None = None

    def check_origin(self, origin: str) -> bool:
        return (
            origin.startswith("http://localhost")
            or origin.startswith("http://127.0.0.1")
            or origin.startswith("tauri://")
        )

    def open(self, task_id: str) -> None:
        task = self.runtime.tool_tasks.get(task_id)
        if not task:
            self.close(code=4004, reason="task not found")
            return

        self.task_id = task_id
        for event in task.logs:
            self.write_message(json.dumps(event, ensure_ascii=False))
        self.runtime.tool_tasks.subscribe(task_id, self._send_event)

    def on_close(self) -> None:
        if self.task_id:
            self.runtime.tool_tasks.unsubscribe(self.task_id, self._send_event)

    def _send_event(self, event: dict[str, Any]) -> None:
        self.write_message(json.dumps(event, ensure_ascii=False))
