"""Persistence adapters used by runtime stores.

Store classes remain the runtime-facing repository boundary. This module only
owns the mechanics of the current document-file backend so stores do not each
reimplement JSON parsing and file replacement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4


class DocumentStorage(Protocol):
    """Minimal backend contract for stores persisted as one document."""

    path: Path | None

    def load(self) -> dict[str, Any] | None:
        """Return the stored document, or None when it cannot be loaded."""

    def save(self, payload: dict[str, Any]) -> None:
        """Persist a complete document."""


class AtomicJsonDocumentStorage:
    """UTF-8 JSON document storage using same-directory atomic replacement."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path or not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return value if isinstance(value, dict) else None

    def save(self, payload: dict[str, Any]) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
