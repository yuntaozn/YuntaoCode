from __future__ import annotations

from .base import ApiHandler


class SettingsHandler(ApiHandler):
    def get(self) -> None:
        self.finish_json({"success": True, "data": self.runtime.settings.public()})

    def post(self) -> None:
        payload = self.parse_json_body()
        settings = self.runtime.settings.update(payload)
        self.finish_json({"success": True, "data": settings})
