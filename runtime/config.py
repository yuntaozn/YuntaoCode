from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class RuntimeConfig:
    host: str
    port: int
    token: str
    workspace_roots: tuple[Path, ...]

    @classmethod
    def build(
        cls,
        host: str,
        port: int,
        token: str,
        workspace_roots: Sequence[str],
    ) -> "RuntimeConfig":
        roots = tuple(Path(root).expanduser().resolve() for root in workspace_roots)
        return cls(host=host, port=port, token=token, workspace_roots=roots)

