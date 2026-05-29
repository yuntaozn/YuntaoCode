from __future__ import annotations

from .base import ApiHandler


class BackupsHandler(ApiHandler):
    def get(self) -> None:
        self.finish_json({"success": True, "data": self.runtime.backups.public()})

    def delete(self) -> None:
        self.finish_json({"success": True, "data": self.runtime.backups.clear()})


class BackupRestoreHandler(ApiHandler):
    def post(self, backup_id: str) -> None:
        self.finish_json({"success": True, "data": self.runtime.backups.restore(backup_id)})
