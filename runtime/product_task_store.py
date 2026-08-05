"""产品级 Task 及恢复记录的 SQLite 存储。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from runtime.core.task import ProductTask, TASK_STATES
from runtime.run_store import utc_now


CHECKPOINT_SCHEMA_VERSION = "checkpoint.v1"
PRODUCT_TASK_STORE_SCHEMA_VERSION = "product_task_store.v1"


class ProductTaskStore:
    """管理产品级 Task、Checkpoint 和 ContextSnapshot 记录。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()
        self._recover_interrupted()

    def create(
        self,
        *,
        goal: str,
        conversation_id: str = "",
        workspace_id: str = "",
        kind: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProductTask:
        now = utc_now()
        task = ProductTask(
            id=str(uuid4()),
            goal=str(goal or "").strip(),
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            kind=kind,
            state="created",
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        self._upsert(task)
        return task

    def get(self, task_id: str) -> ProductTask | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM product_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def list(
        self,
        *,
        workspace_id: str | None = None,
        conversation_id: str | None = None,
        state: str | None = None,
    ) -> list[ProductTask]:
        clauses: list[str] = []
        values: list[str] = []
        for column, value in (
            ("workspace_id", workspace_id),
            ("conversation_id", conversation_id),
            ("state", state),
        ):
            if value:
                clauses.append(f"{column} = ?")
                values.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM product_tasks {where} ORDER BY updated_at DESC",
                values,
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def attach_run(self, task_id: str, run_id: str, *, state: str = "running") -> ProductTask:
        task = self._require(task_id)
        updated = replace(
            task,
            state=_normalized_state(state),
            current_run_id=run_id,
            run_count=max(0, int(task.run_count)) + 1,
            updated_at=utc_now(),
        )
        self._upsert(updated)
        return updated

    def update_state(self, task_id: str, state: str, *, current_run_id: str | None = None) -> ProductTask:
        task = self._require(task_id)
        updated = replace(
            task,
            state=_normalized_state(state),
            current_run_id=task.current_run_id if current_run_id is None else current_run_id,
            updated_at=utc_now(),
        )
        self._upsert(updated)
        return updated

    def sync_from_run(self, run: Any) -> ProductTask | None:
        task_id = str(getattr(run, "task_id", "") or "")
        if not task_id or not self.get(task_id):
            return None
        state = {
            "running": "running",
            "waiting_confirmation": "waiting_confirmation",
            "paused": "paused",
            "success": "completed",
            "failure": "failed",
            "stopped": "paused",
            "partial": "paused",
            "cancelled": "cancelled",
            "created": "created",
        }.get(str(getattr(run, "status", "") or ""), "running")
        return self.update_state(task_id, state, current_run_id=str(getattr(run, "id", "") or ""))

    def create_checkpoint(
        self,
        *,
        task_id: str,
        run_id: str,
        kind: str,
        state: str,
        context_snapshot_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checkpoint = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "kind": "checkpoint",
            "id": str(uuid4()),
            "task_id": task_id,
            "run_id": run_id,
            "checkpoint_kind": kind,
            "state": state,
            "context_snapshot_id": context_snapshot_id,
            "data": dict(data or {}),
            "created_at": utc_now(),
        }
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO task_checkpoints(
                    id, schema_version, task_id, run_id, checkpoint_kind,
                    state, context_snapshot_id, data_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint["id"],
                    checkpoint["schema_version"],
                    task_id,
                    run_id,
                    kind,
                    state,
                    context_snapshot_id,
                    _json(checkpoint["data"]),
                    checkpoint["created_at"],
                ),
            )
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM task_checkpoints WHERE id = ?",
                (checkpoint_id,),
            ).fetchone()
        return self._checkpoint_row(row) if row else None

    def list_checkpoints(self, *, task_id: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[str] = []
        if task_id:
            clauses.append("task_id = ?")
            values.append(task_id)
        if run_id:
            clauses.append("run_id = ?")
            values.append(run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM task_checkpoints {where} ORDER BY created_at DESC",
                values,
            ).fetchall()
        return [self._checkpoint_row(row) for row in rows]

    def create_context_snapshot(
        self,
        *,
        task_id: str,
        run_id: str,
        phase: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "schema_version": str(snapshot.get("schema_version") or "context_snapshot.v1"),
            "kind": "context_snapshot",
            "id": str(uuid4()),
            "task_id": task_id,
            "run_id": run_id,
            "phase": phase,
            "snapshot": dict(snapshot),
            "created_at": utc_now(),
        }
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO context_snapshots(
                    id, schema_version, task_id, run_id, phase, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["schema_version"],
                    task_id,
                    run_id,
                    phase,
                    _json(record["snapshot"]),
                    record["created_at"],
                ),
            )
        return record

    def get_context_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM context_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
        return self._snapshot_row(row) if row else None

    def list_context_snapshots(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[str] = []
        if task_id:
            clauses.append("task_id = ?")
            values.append(task_id)
        if run_id:
            clauses.append("run_id = ?")
            values.append(run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM context_snapshots {where} ORDER BY created_at DESC",
                values,
            ).fetchall()
        return [self._snapshot_row(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _require(self, task_id: str) -> ProductTask:
        task = self.get(task_id)
        if not task:
            raise KeyError(f"unknown product task: {task_id}")
        return task

    def _upsert(self, task: ProductTask) -> None:
        data = task.to_dict()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO product_tasks(
                    id, schema_version, goal, conversation_id, workspace_id,
                    task_kind, state, current_run_id, run_count,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    goal = excluded.goal,
                    conversation_id = excluded.conversation_id,
                    workspace_id = excluded.workspace_id,
                    task_kind = excluded.task_kind,
                    state = excluded.state,
                    current_run_id = excluded.current_run_id,
                    run_count = excluded.run_count,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    task.id,
                    data["schema_version"],
                    task.goal,
                    task.conversation_id,
                    task.workspace_id,
                    task.kind,
                    task.state,
                    task.current_run_id,
                    task.run_count,
                    _json(task.metadata),
                    task.created_at or utc_now(),
                    task.updated_at or utc_now(),
                ),
            )

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript("""
                CREATE TABLE IF NOT EXISTS product_tasks (
                    id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    current_run_id TEXT NOT NULL,
                    run_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_product_tasks_workspace_updated
                ON product_tasks(workspace_id, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_product_tasks_conversation_updated
                ON product_tasks(conversation_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS context_snapshots (
                    id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES product_tasks(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_context_snapshots_task_created
                ON context_snapshots(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES product_tasks(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL,
                    checkpoint_kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    context_snapshot_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_task_checkpoints_task_created
                ON task_checkpoints(task_id, created_at DESC);
            """)

    def _recover_interrupted(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE product_tasks
                SET state = 'paused', updated_at = ?
                WHERE state IN ('running', 'planning', 'verifying', 'resuming', 'waiting_confirmation')
                """,
                (utc_now(),),
            )

    def _row_to_task(self, row: sqlite3.Row) -> ProductTask:
        return ProductTask(
            id=str(row["id"]),
            goal=str(row["goal"]),
            conversation_id=str(row["conversation_id"]),
            workspace_id=str(row["workspace_id"]),
            kind=str(row["task_kind"]),
            state=_normalized_state(row["state"]),
            current_run_id=str(row["current_run_id"]),
            run_count=int(row["run_count"] or 0),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            metadata=_loads(row["metadata_json"]),
        )

    def _checkpoint_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": str(row["schema_version"]),
            "kind": "checkpoint",
            "id": str(row["id"]),
            "task_id": str(row["task_id"]),
            "run_id": str(row["run_id"]),
            "checkpoint_kind": str(row["checkpoint_kind"]),
            "state": str(row["state"]),
            "context_snapshot_id": str(row["context_snapshot_id"]),
            "data": _loads(row["data_json"]),
            "created_at": str(row["created_at"]),
        }

    def _snapshot_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": str(row["schema_version"]),
            "kind": "context_snapshot",
            "id": str(row["id"]),
            "task_id": str(row["task_id"]),
            "run_id": str(row["run_id"]),
            "phase": str(row["phase"]),
            "snapshot": _loads(row["snapshot_json"]),
            "created_at": str(row["created_at"]),
        }


def _normalized_state(value: Any) -> str:
    state = str(value or "created")
    return state if state in TASK_STATES else "created"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
