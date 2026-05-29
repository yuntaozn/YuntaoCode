from __future__ import annotations

from .base import ApiHandler


class HealthHandler(ApiHandler):
    def prepare(self) -> None:
        return

    def get(self) -> None:
        self.finish_json({
            "success": True,
            "service": "local-intelligent-terminal",
            "version": "0.1.0",
            "workspace_roots": [str(root) for root in self.runtime.runner.path_guard.workspace_roots],
        })
