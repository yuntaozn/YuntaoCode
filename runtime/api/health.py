from __future__ import annotations

from runtime.version import __version__

from .base import ApiHandler


HEALTH_SERVICE_NAME = "yuntaocode"


class HealthHandler(ApiHandler):
    def prepare(self) -> None:
        return

    def get(self) -> None:
        self.finish_json({
            "success": True,
            "service": HEALTH_SERVICE_NAME,
            "version": __version__,
            "workspace_roots": [str(root) for root in self.runtime.runner.path_guard.workspace_roots],
        })
