from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .security import PathGuard


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BackupStore:
    def __init__(self, root: Path, path_guard: PathGuard) -> None:
        self.root = root
        self.path_guard = path_guard
        self.index_path = self.root / "index.json"
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._index = self._load()

    def begin(
        self,
        task_id: str,
        tool_id: str,
        input_data: dict[str, Any],
        path_guard: PathGuard | None = None,
    ) -> "BackupSession":
        backup_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        return BackupSession(self, backup_id, task_id, tool_id, input_data, path_guard=path_guard)

    def public(self, limit: int = 50) -> dict[str, Any]:
        backups = self._sorted_backups()[:limit]
        return {
            "items": [self._public_record(item) for item in backups],
            "storage_dir": str(self.root),
            "total_count": len(self._index.get("backups") or []),
            "total_file_count": sum(len(item.get("files") or []) for item in self._index.get("backups") or []),
        }

    def restore(self, backup_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._find(backup_id)
            if not record:
                raise ValueError(f"backup not found: {backup_id}")

            restored: list[str] = []
            for item in reversed(record.get("files") or []):
                try:
                    original = self.path_guard.resolve(item.get("path"))
                except PermissionError:
                    original = Path(str(item.get("path") or "")).expanduser().resolve()
                existed = bool(item.get("existed"))
                if existed:
                    backup_path = self.root / backup_id / str(item.get("backup_path") or "")
                    if not backup_path.exists():
                        raise FileNotFoundError(f"backup file missing: {backup_path}")
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(backup_path), str(original))
                    restored.append(str(original))
                elif original.exists():
                    if not original.is_file():
                        raise ValueError(f"refusing to remove non-file path: {original}")
                    original.unlink()
                    restored.append(str(original))

            record["restored_at"] = now_iso()
            self._save_locked()
            public = self._public_record(record)
            public["restored_file_count"] = len(restored)
            public["restored_files"] = restored[:100]
            return public

    def clear(self) -> dict[str, Any]:
        with self._lock:
            if self.root.exists():
                for child in self.root.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    elif child.name != self.index_path.name:
                        child.unlink()
            self._index = {"backups": []}
            self._save_locked()
            return self.public()

    def add_record(self, record: dict[str, Any], keep_rounds: int) -> dict[str, Any]:
        with self._lock:
            backups = self._index.setdefault("backups", [])
            backups.append(record)
            self._enforce_retention_locked(keep_rounds)
            self._save_locked()
            return self._public_record(record)

    def _find(self, backup_id: str) -> dict[str, Any] | None:
        for item in self._index.get("backups") or []:
            if item.get("id") == backup_id:
                return item
        return None

    def _sorted_backups(self) -> list[dict[str, Any]]:
        return sorted(
            self._index.get("backups") or [],
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )

    def _enforce_retention_locked(self, keep_rounds: int) -> None:
        keep = max(1, min(int(keep_rounds or 50), 100))
        backups = self._sorted_backups()
        retained = backups[:keep]
        expired = backups[keep:]
        for item in expired:
            backup_id = item.get("id")
            if not backup_id:
                continue
            backup_dir = self.root / str(backup_id)
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
        self._index["backups"] = retained

    def _public_record(self, item: dict[str, Any]) -> dict[str, Any]:
        files = item.get("files") or []
        public_files = [
            {
                "path": file.get("path"),
                "name": Path(str(file.get("path") or "")).name,
                "existed": bool(file.get("existed")),
                "size": file.get("size"),
            }
            for file in files[:100]
        ]
        return {
            "id": item.get("id"),
            "tool_id": item.get("tool_id"),
            "task_id": item.get("task_id"),
            "created_at": item.get("created_at"),
            "status": item.get("status"),
            "file_count": len(files),
            "files": public_files,
            "file_names": [file.get("name") for file in public_files if file.get("name")],
            "restored_at": item.get("restored_at", ""),
        }

    def _load(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"backups": []}
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"backups": []}
        if not isinstance(value, dict):
            return {"backups": []}
        if not isinstance(value.get("backups"), list):
            value["backups"] = []
        return value

    def _save_locked(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class BackupSession:
    def __init__(
        self,
        store: BackupStore,
        backup_id: str,
        task_id: str,
        tool_id: str,
        input_data: dict[str, Any],
        path_guard: PathGuard | None = None,
    ) -> None:
        self.store = store
        self.id = backup_id
        self.task_id = task_id
        self.tool_id = tool_id
        self.input_data = input_data
        self.path_guard = path_guard or store.path_guard
        self.files: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self.dir = self.store.root / self.id

    def backup_file(self, path: str | Path) -> None:
        original = self.path_guard.resolve(str(path))
        key = str(original)
        if key in self._seen:
            return
        self._seen.add(key)
        self.dir.mkdir(parents=True, exist_ok=True)

        existed = original.exists()
        record: dict[str, Any] = {
            "path": str(original),
            "existed": bool(existed),
            "size": original.stat().st_size if existed and original.is_file() else 0,
        }
        if existed:
            if not original.is_file():
                raise ValueError(f"cannot backup non-file path: {original}")
            backup_name = f"{len(self.files) + 1:04d}_{uuid.uuid4().hex}{original.suffix}"
            shutil.copy2(str(original), str(self.dir / backup_name))
            record["backup_path"] = backup_name
        self.files.append(record)

    def finish(self, status: str, keep_rounds: int) -> dict[str, Any] | None:
        if not self.files:
            if self.dir.exists():
                shutil.rmtree(self.dir)
            return None
        record = {
            "id": self.id,
            "task_id": self.task_id,
            "tool_id": self.tool_id,
            "input": self.input_data,
            "created_at": now_iso(),
            "status": status,
            "files": self.files,
        }
        return self.store.add_record(record, keep_rounds)
