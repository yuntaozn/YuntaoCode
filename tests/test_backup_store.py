from __future__ import annotations

from pathlib import Path

from runtime.backup_store import BackupStore
from runtime.security import PathGuard


def test_retention_cleanup_failure_is_best_effort(tmp_path: Path, monkeypatch) -> None:
    store = BackupStore(tmp_path / "backups", PathGuard([tmp_path]))
    old_dir = store.root / "old"
    old_dir.mkdir(parents=True)
    (old_dir / "locked.glb").write_text("asset", encoding="utf-8")
    old_record = {
        "id": "old",
        "task_id": "old-task",
        "tool_id": "code.edit_file",
        "created_at": "2026-06-29T00:00:00+00:00",
        "status": "success",
        "files": [],
    }
    new_record = {
        "id": "new",
        "task_id": "new-task",
        "tool_id": "code.edit_file",
        "created_at": "2026-06-30T00:00:00+00:00",
        "status": "success",
        "files": [],
    }
    store._index = {"backups": [old_record]}

    def fail_rmtree(path: str | Path) -> None:
        raise PermissionError("locked backup file")

    monkeypatch.setattr("runtime.backup_store.shutil.rmtree", fail_rmtree)

    public = store.add_record(new_record, keep_rounds=1)

    assert public["id"] == "new"
    assert public["retention_warnings"] == [{
        "backup_id": "old",
        "path": str(old_dir),
        "error": "locked backup file",
    }]
    assert [item["id"] for item in store._index["backups"]] == ["new", "old"]
