"""Persistence repositories for runs and run events."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from .persistence import DocumentStorage


OPERATIONAL_DB_SCHEMA_VERSION = 1
LEGACY_RUNS_IMPORT_KEY = "legacy_runs_json_import_v1"


class RunRepository(Protocol):
    """Storage boundary used by RunStore."""

    path: Path | None

    def create(self, record: dict[str, Any]) -> None: ...

    def get(self, run_id: str) -> dict[str, Any] | None: ...

    def list(
        self,
        *,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def update(self, record: dict[str, Any]) -> None: ...

    def append_event(self, record: dict[str, Any], event: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


class JsonRunRepository:
    """Compatibility repository backed by the historical runs JSON document."""

    def __init__(self, storage: DocumentStorage, *, keep_runs: int) -> None:
        self.storage = storage
        self.path = storage.path
        self.keep_runs = keep_runs
        self._records: dict[str, dict[str, Any]] = {}
        value = storage.load()
        runs = value.get("runs") if isinstance(value, dict) else []
        if isinstance(runs, list):
            for item in runs:
                if isinstance(item, dict) and item.get("id"):
                    self._records[str(item["id"])] = deepcopy(item)

    def create(self, record: dict[str, Any]) -> None:
        self._records[str(record["id"])] = deepcopy(record)
        self._save()

    def get(self, run_id: str) -> dict[str, Any] | None:
        record = self._records.get(run_id)
        return deepcopy(record) if record else None

    def list(
        self,
        *,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        records = list(self._records.values())
        if conversation_id:
            records = [item for item in records if item.get("conversation_id") == conversation_id]
        if workspace_id:
            records = [item for item in records if item.get("workspace_id") == workspace_id]
        if status:
            records = [item for item in records if item.get("status") == status]
        return [
            deepcopy(item)
            for item in sorted(records, key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        ]

    def update(self, record: dict[str, Any]) -> None:
        self._records[str(record["id"])] = deepcopy(record)
        self._save()

    def append_event(self, record: dict[str, Any], event: dict[str, Any]) -> None:
        self.update(record)

    def close(self) -> None:
        return

    def _save(self) -> None:
        records = sorted(
            self._records.values(),
            key=lambda item: str(item.get("created_at") or ""),
        )[-self.keep_runs:]
        self.storage.save({
            "schema_version": "0.1",
            "record_kind": "run_store",
            "runs": records,
        })


class SqliteRunRepository:
    """Transactional, indexed repository for operational run history."""

    def __init__(self, path: Path, *, keep_runs: int, keep_events: int) -> None:
        self.path = path
        self.keep_runs = keep_runs
        self.keep_events = keep_events
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def create(self, record: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._upsert_run(record)
            self._prune_runs()

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            events = self._load_events(run_id)
            return self._row_to_record(row, events=events, event_count=len(events))

    def list(
        self,
        *,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[str] = []
        for column, value in (
            ("conversation_id", conversation_id),
            ("workspace_id", workspace_id),
            ("status", status),
        ):
            if value:
                clauses.append(f"r.{column} = ?")
                values.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT r.*, COUNT(e.id) AS event_count
            FROM runs AS r
            LEFT JOIN run_events AS e ON e.run_id = r.id
            {where}
            GROUP BY r.id
            ORDER BY r.updated_at DESC
        """
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
        return [
            self._row_to_record(row, events=[], event_count=int(row["event_count"] or 0))
            for row in rows
        ]

    def update(self, record: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._upsert_run(record)

    def append_event(self, record: dict[str, Any], event: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._upsert_run(record)
            sequence = int(self._connection.execute(
                "SELECT COALESCE(MAX(sequence), -1) + 1 FROM run_events WHERE run_id = ?",
                (str(record["id"]),),
            ).fetchone()[0])
            self._insert_event(str(record["id"]), sequence, event)
            self._connection.execute(
                """
                DELETE FROM run_events
                WHERE run_id = ? AND sequence < ?
                """,
                (str(record["id"]), max(0, sequence - self.keep_events + 1)),
            )
            self._prune_runs()

    def import_legacy_document(self, storage: DocumentStorage) -> int:
        """Import a valid legacy runs document once without modifying it."""
        with self._lock:
            imported = self._metadata_value(LEGACY_RUNS_IMPORT_KEY)
            if imported is not None:
                return 0
            value = storage.load()
            runs = value.get("runs") if isinstance(value, dict) else None
            if not isinstance(runs, list):
                return 0
            imported_count = 0
            with self._connection:
                for item in runs[-self.keep_runs:]:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    cursor = self._insert_run_if_missing(item)
                    if cursor.rowcount != 1:
                        continue
                    events = item.get("events") if isinstance(item.get("events"), list) else []
                    for sequence, event in enumerate(events[-self.keep_events:]):
                        if isinstance(event, dict):
                            self._insert_event(str(item["id"]), sequence, event)
                    imported_count += 1
                self._prune_runs()
                self._set_metadata(LEGACY_RUNS_IMPORT_KEY, str(storage.path or "document"))
            return imported_count

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def schema_version(self) -> int:
        with self._lock:
            return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    def _migrate(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current > OPERATIONAL_DB_SCHEMA_VERSION:
            self._connection.close()
            raise RuntimeError(
                f"operational database schema {current} is newer than supported "
                f"schema {OPERATIONAL_DB_SCHEMA_VERSION}"
            )
        if current < 1:
            with self._connection:
                self._connection.executescript("""
                    CREATE TABLE IF NOT EXISTS runtime_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS runs (
                        id TEXT PRIMARY KEY,
                        schema_version TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        user_content TEXT NOT NULL,
                        status TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS run_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                        sequence INTEGER NOT NULL,
                        event_time TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        UNIQUE(run_id, sequence)
                    );

                    CREATE INDEX IF NOT EXISTS idx_runs_conversation_updated
                    ON runs(conversation_id, updated_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_runs_workspace_updated
                    ON runs(workspace_id, updated_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_runs_status_updated
                    ON runs(status, updated_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence
                    ON run_events(run_id, sequence);
                """)
                self._connection.execute(f"PRAGMA user_version = {OPERATIONAL_DB_SCHEMA_VERSION}")

    def _upsert_run(self, record: dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO runs (
                id, schema_version, conversation_id, workspace_id, mode,
                user_content, status, stage, message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                schema_version = excluded.schema_version,
                conversation_id = excluded.conversation_id,
                workspace_id = excluded.workspace_id,
                mode = excluded.mode,
                user_content = excluded.user_content,
                status = excluded.status,
                stage = excluded.stage,
                message = excluded.message,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            self._run_values(record),
        )

    def _insert_run_if_missing(self, record: dict[str, Any]) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT OR IGNORE INTO runs (
                id, schema_version, conversation_id, workspace_id, mode,
                user_content, status, stage, message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._run_values(record),
        )

    def _run_values(self, record: dict[str, Any]) -> tuple[str, ...]:
        return (
            str(record.get("id") or ""),
            str(record.get("schema_version") or "0.1"),
            str(record.get("conversation_id") or ""),
            str(record.get("workspace_id") or ""),
            str(record.get("mode") or "terminal"),
            str(record.get("user_content") or ""),
            str(record.get("status") or "running"),
            str(record.get("stage") or "created"),
            str(record.get("message") or ""),
            str(record.get("created_at") or ""),
            str(record.get("updated_at") or ""),
        )

    def _insert_event(self, run_id: str, sequence: int, event: dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO run_events(run_id, sequence, event_time, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                sequence,
                str(event.get("time") or ""),
                json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def _load_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT payload_json FROM run_events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
        return events

    def _row_to_record(
        self,
        row: sqlite3.Row,
        *,
        events: list[dict[str, Any]],
        event_count: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": str(row["schema_version"]),
            "record_kind": "run",
            "id": str(row["id"]),
            "conversation_id": str(row["conversation_id"]),
            "workspace_id": str(row["workspace_id"]),
            "mode": str(row["mode"]),
            "user_content": str(row["user_content"]),
            "status": str(row["status"]),
            "stage": str(row["stage"]),
            "message": str(row["message"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "event_count": event_count,
            "events": events,
        }

    def _prune_runs(self) -> None:
        self._connection.execute(
            """
            DELETE FROM runs
            WHERE id IN (
                SELECT id FROM runs
                ORDER BY created_at DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self.keep_runs,),
        )

    def _metadata_value(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM runtime_metadata WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else None

    def _set_metadata(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO runtime_metadata(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
