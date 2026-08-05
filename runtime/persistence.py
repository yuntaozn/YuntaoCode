"""Runtime Store 使用的持久化适配器。

Store 类仍是 Runtime 面向存储库的边界。本模块只负责当前文档文件后端的
共享机制，避免各 Store 重复实现 JSON 解析与文件替换。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4


class DocumentStorage(Protocol):
    """以单一文档持久化的存储所需最小后端契约。"""

    path: Path | None

    def load(self) -> dict[str, Any] | None:
        """返回已存储文档；无法加载时返回 None。"""

    def save(self, payload: dict[str, Any]) -> None:
        """持久化完整文档。"""


class AtomicJsonDocumentStorage:
    """使用同目录原子替换的 UTF-8 JSON 文档存储。"""

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
