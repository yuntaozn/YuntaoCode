"""Runtime-owned storage for user-provided conversation attachments."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AttachmentRecord:
    id: str
    workspace_id: str
    conversation_id: str
    message_id: str
    original_name: str
    relative_path: str
    media_type: str
    size: int
    sha256: str
    created_at: str

    @property
    def is_image(self) -> bool:
        return self.media_type in {
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "image/bmp",
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.original_name,
            "media_type": self.media_type,
            "size": self.size,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "is_image": self.is_image,
            "content_url": f"/attachments/{self.id}/content",
        }


class AttachmentStore:
    """Stores immutable attachment bytes on disk and metadata in SQLite."""

    def __init__(self, database_path: Path, files_root: Path) -> None:
        self.database_path = database_path
        self.files_root = files_root
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def create(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        original_name: str,
        media_type: str,
        content: bytes,
    ) -> AttachmentRecord:
        attachment_id = str(uuid4())
        safe_name = _safe_original_name(original_name)
        suffix = _safe_suffix(safe_name)
        relative_path = f"{attachment_id}/original{suffix}"
        target = self.files_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=False)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        record = AttachmentRecord(
            id=attachment_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id="",
            original_name=safe_name,
            relative_path=relative_path,
            media_type=_normalized_media_type(media_type, safe_name),
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            created_at=utc_now(),
        )
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO attachments (
                        id, workspace_id, conversation_id, message_id, original_name,
                        relative_path, media_type, size, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.workspace_id,
                        record.conversation_id,
                        record.message_id,
                        record.original_name,
                        record.relative_path,
                        record.media_type,
                        record.size,
                        record.sha256,
                        record.created_at,
                    ),
                )
        except Exception:
            target.unlink(missing_ok=True)
            try:
                target.parent.rmdir()
            except OSError:
                pass
            raise
        return record

    def get(self, attachment_id: str) -> AttachmentRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM attachments WHERE id = ?",
                (str(attachment_id),),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_by_ids(self, attachment_ids: Iterable[str]) -> list[AttachmentRecord]:
        return [
            record
            for attachment_id in attachment_ids
            if (record := self.get(str(attachment_id))) is not None
        ]

    def list_for_conversation(self, conversation_id: str) -> list[AttachmentRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM attachments WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def bind_message(self, attachment_ids: Iterable[str], message_id: str) -> None:
        ids = [str(item) for item in attachment_ids if str(item)]
        if not ids:
            return
        with self._lock, self._connection:
            self._connection.executemany(
                "UPDATE attachments SET message_id = ? WHERE id = ? AND message_id = ''",
                [(message_id, attachment_id) for attachment_id in ids],
            )

    def validate_for_message(
        self,
        attachment_ids: Iterable[str],
        *,
        workspace_id: str,
        conversation_id: str,
    ) -> list[AttachmentRecord]:
        requested = [str(item) for item in attachment_ids if str(item)]
        records = self.list_by_ids(requested)
        if len(records) != len(requested):
            raise ValueError("one or more attachments were not found")
        for record in records:
            if record.workspace_id != workspace_id or record.conversation_id != conversation_id:
                raise ValueError("attachment does not belong to this workspace and conversation")
            if record.message_id:
                raise ValueError("attachment is already bound to a message")
        return records

    def delete_for_conversation(self, conversation_id: str) -> int:
        records = self.list_for_conversation(conversation_id)
        for record in records:
            self.delete(record.id, require_unbound=False)
        return len(records)

    def read_bytes(self, attachment_id: str) -> bytes:
        record = self.get(attachment_id)
        if not record:
            raise KeyError(f"unknown attachment: {attachment_id}")
        return self.path_for(record).read_bytes()

    def read_text(self, attachment_id: str, *, max_chars: int = 100_000) -> tuple[str, bool]:
        content = self.read_bytes(attachment_id)
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = content.decode(encoding)
                return text[:max_chars], len(text) > max_chars
            except UnicodeDecodeError:
                continue
        raise ValueError("attachment is not a supported text file")

    def data_url(self, attachment_id: str) -> str:
        record = self.get(attachment_id)
        if not record:
            raise KeyError(f"unknown attachment: {attachment_id}")
        encoded = base64.b64encode(self.read_bytes(attachment_id)).decode("ascii")
        return f"data:{record.media_type};base64,{encoded}"

    def path_for(self, record: AttachmentRecord) -> Path:
        path = (self.files_root / record.relative_path).resolve()
        path.relative_to(self.files_root.resolve())
        return path

    def delete(self, attachment_id: str, *, require_unbound: bool = True) -> bool:
        record = self.get(attachment_id)
        if not record:
            return False
        if require_unbound and record.message_id:
            raise ValueError("bound attachments cannot be deleted directly")
        path = self.path_for(record)
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return True

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _migrate(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL DEFAULT '',
                    original_name TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_attachments_conversation_created
                ON attachments(conversation_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_attachments_message
                ON attachments(message_id);
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> AttachmentRecord:
        return AttachmentRecord(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            conversation_id=str(row["conversation_id"]),
            message_id=str(row["message_id"]),
            original_name=str(row["original_name"]),
            relative_path=str(row["relative_path"]),
            media_type=str(row["media_type"]),
            size=int(row["size"]),
            sha256=str(row["sha256"]),
            created_at=str(row["created_at"]),
        )


def _safe_original_name(value: str) -> str:
    name = Path(str(value or "attachment")).name.strip()
    name = "".join(char for char in name if char not in {"\r", "\n", "\0"})
    return name[:240] or "attachment"


def _safe_suffix(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if not suffix or len(suffix) > 16:
        return ""
    return suffix if all(char.isalnum() or char == "." for char in suffix) else ""


def _normalized_media_type(value: str, name: str) -> str:
    media_type = str(value or "").split(";", 1)[0].strip().lower()
    if "/" in media_type:
        return media_type
    return mimetypes.guess_type(name)[0] or "application/octet-stream"
