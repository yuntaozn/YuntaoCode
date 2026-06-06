from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_draft_store_root(data_dir: Path | str) -> Path:
    root = Path(data_dir).expanduser().resolve() / "text-artifact-drafts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def text_draft_path(data_dir: Path | str, draft_id: str) -> Path:
    return text_draft_store_root(data_dir) / f"{normalize_text_draft_id(draft_id)}.json"


def normalize_text_draft_id(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", text):
        raise ValueError("draft_id must be 8-80 characters using letters, numbers, '_' or '-'")
    return text


def create_text_draft_record(
    *,
    title: str = "",
    path_hint: str = "",
    language: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "draft_id": f"text_{uuid.uuid4().hex[:16]}",
        "title": str(title or "Untitled Text Artifact").strip() or "Untitled Text Artifact",
        "path_hint": str(path_hint or "").strip(),
        "language": str(language or "").strip(),
        "created_at": now,
        "updated_at": now,
        "metadata": dict(metadata or {}),
        "chunks": [],
    }


def save_text_draft(data_dir: Path | str, record: dict[str, Any]) -> dict[str, Any]:
    record = deepcopy(record)
    record["updated_at"] = utc_now()
    path = text_draft_path(data_dir, record["draft_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def load_text_draft(data_dir: Path | str, draft_id: str) -> dict[str, Any]:
    path = text_draft_path(data_dir, draft_id)
    if not path.exists():
        raise FileNotFoundError(f"text artifact draft not found: {draft_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid text artifact draft: {draft_id}")
    data.setdefault("chunks", [])
    data.setdefault("metadata", {})
    return data


def append_text_chunk(
    record: dict[str, Any],
    *,
    content: str,
    label: str = "",
    sequence: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(content or "")
    if not text:
        raise ValueError("content is required")
    chunks = record.setdefault("chunks", [])
    if sequence is None:
        sequence = len(chunks) + 1
    chunk = {
        "chunk_id": f"chunk_{uuid.uuid4().hex[:12]}",
        "sequence": int(sequence),
        "label": str(label or "").strip(),
        "created_at": utc_now(),
        "content": text,
        "char_count": len(text),
        "metadata": dict(metadata or {}),
    }
    chunks.append(chunk)
    chunks.sort(key=lambda item: int(item.get("sequence") or 0))
    return chunk


def text_draft_content(record: dict[str, Any]) -> str:
    chunks = sorted(record.get("chunks") or [], key=lambda item: int(item.get("sequence") or 0))
    return "".join(str(chunk.get("content") or "") for chunk in chunks)


def text_draft_stats(record: dict[str, Any]) -> dict[str, Any]:
    content = text_draft_content(record)
    return {
        "draft_id": record.get("draft_id"),
        "title": record.get("title"),
        "path_hint": record.get("path_hint"),
        "language": record.get("language"),
        "chunk_count": len(record.get("chunks") or []),
        "text_chars": len(content),
        "line_count": len(content.splitlines()),
    }


def inspect_text_draft_record(record: dict[str, Any], *, preview_chars: int = 1200) -> dict[str, Any]:
    content = text_draft_content(record)
    return {
        "draft_id": record.get("draft_id"),
        "title": record.get("title"),
        "path_hint": record.get("path_hint"),
        "language": record.get("language"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "metadata": record.get("metadata") or {},
        "stats": text_draft_stats(record),
        "chunks": [
            {
                "chunk_id": chunk.get("chunk_id"),
                "sequence": chunk.get("sequence"),
                "label": chunk.get("label"),
                "char_count": chunk.get("char_count"),
            }
            for chunk in record.get("chunks") or []
        ],
        "preview": content[: max(0, int(preview_chars))],
    }
