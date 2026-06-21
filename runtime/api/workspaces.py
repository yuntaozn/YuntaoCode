from __future__ import annotations

from pathlib import Path

import tornado.web

from .base import ApiHandler
from ..local_open import open_path


class WorkspacesHandler(ApiHandler):
    def get(self) -> None:
        self.finish_json({
            "success": True,
            "data": [item.to_public_dict() for item in self.runtime.workspaces.list()],
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        path = payload.get("path")
        if not path:
            raise tornado.web.HTTPError(400, reason="path is required")
        workspace = self.runtime.workspaces.add(path, allow_as_root=True)
        self.finish_json({
            "success": True,
            "data": workspace.to_public_dict(),
        })


class WorkspaceDetailHandler(ApiHandler):
    def delete(self, workspace_id: str) -> None:
        removed = self.runtime.workspaces.remove(workspace_id)
        if not removed:
            raise tornado.web.HTTPError(404, reason="workspace not found")
        self.finish_json({
            "success": True,
            "data": {
                "removed": removed.to_public_dict(),
                "workspaces": [item.to_public_dict() for item in self.runtime.workspaces.list()],
            },
        })


class WorkspaceOpenHandler(ApiHandler):
    def post(self, workspace_id: str) -> None:
        workspace = self.runtime.workspaces.get(workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")

        path = Path(workspace.path)
        if not path.exists() or not path.is_dir():
            raise tornado.web.HTTPError(404, reason=f"workspace folder not found: {path}")

        try:
            open_folder(path)
        except OSError as exc:
            raise tornado.web.HTTPError(500, reason=f"failed to open workspace folder: {exc}") from exc

        self.finish_json({
            "success": True,
            "data": {"opened": workspace.to_public_dict()},
        })


class WorkspacePickerHandler(ApiHandler):
    def post(self) -> None:
        path = pick_folder()
        if not path:
            self.finish_json({"success": True, "data": None})
            return
        workspace = self.runtime.workspaces.add(path, allow_as_root=True)
        self.finish_json({
            "success": True,
            "data": workspace.to_public_dict(),
        })


def pick_folder() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise tornado.web.HTTPError(500, reason=f"failed to open folder picker: {exc}") from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(title="Select workspace folder")
    finally:
        root.destroy()
    return str(Path(selected)) if selected else ""


def open_folder(path: Path) -> None:
    open_path(path)
