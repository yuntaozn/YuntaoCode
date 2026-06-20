from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .security import PathGuard


LEGACY_WORKSPACE_ID_NAMESPACE = "local-intelligent-terminal"


@dataclass
class WorkspaceRecord:
    id: str
    name: str
    path: str
    is_root: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "is_root": self.is_root,
            "metadata": self.metadata,
        }


class WorkspaceStore:
    def __init__(self, roots: tuple[Path, ...], path_guard: PathGuard, storage_path: Path | None = None) -> None:
        self.path_guard = path_guard
        self.storage_path = storage_path
        self._workspaces: dict[str, WorkspaceRecord] = {}
        self._load_persisted()

    def list(self) -> list[WorkspaceRecord]:
        return list(self._workspaces.values())

    def get(self, workspace_id: str) -> WorkspaceRecord | None:
        return self._workspaces.get(workspace_id)

    def remove(self, workspace_id: str) -> WorkspaceRecord | None:
        removed = self._workspaces.pop(workspace_id, None)
        if removed:
            self._save()
        return removed

    def add(self, raw_path: str, *, is_root: bool = False, allow_as_root: bool = False) -> WorkspaceRecord:
        path = self.path_guard.allow_root(raw_path) if allow_as_root else self.path_guard.resolve(raw_path)
        if not path.exists() or not path.is_dir():
            raise ValueError(f"workspace folder not found: {path}")

        existing = self.find_by_path(str(path))
        if existing:
            if existing.is_root and not is_root and allow_as_root:
                existing.is_root = False
                self._save()
            return existing

        record = WorkspaceRecord(
            id=stable_workspace_id(path),
            name=path.name or str(path),
            path=str(path),
            is_root=is_root,
        )
        self._workspaces[record.id] = record
        self._save()
        return record

    def find_by_path(self, path: str) -> WorkspaceRecord | None:
        normalized = str(Path(path).resolve())
        for record in self._workspaces.values():
            if str(Path(record.path).resolve()) == normalized:
                return record
        return None

    def _load_persisted(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        items = data.get("workspaces") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            try:
                self.add(str(item["path"]), allow_as_root=True)
            except (OSError, ValueError):
                continue

    def _save(self) -> None:
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        items = [
            {
                "path": record.path,
                "name": record.name,
                "metadata": record.metadata,
            }
            for record in self._workspaces.values()
        ]
        self.storage_path.write_text(
            json.dumps({"workspaces": items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def stable_workspace_id(path: Path) -> str:
    normalized = str(path.resolve()).lower()
    # Keep the historical namespace stable so existing workspace IDs do not
    # change across upgrades. This is a compatibility namespace, not the
    # current product name.
    return str(uuid5(NAMESPACE_URL, f"{LEGACY_WORKSPACE_ID_NAMESPACE}:{normalized}"))
