from __future__ import annotations

from pathlib import Path
from typing import Iterable


class PathGuard:
    """将本地工具限制在已配置的工作区根目录内。"""

    def __init__(self, workspace_roots: Iterable[Path], *, allow_all: bool = False):
        self.workspace_roots = tuple(root.resolve() for root in workspace_roots)
        self.allow_all = allow_all
        if not self.workspace_roots:
            raise ValueError("At least one workspace root is required")

    def allow_root(self, raw_path: str | Path) -> Path:
        root = Path(raw_path).expanduser().resolve()
        if not any(existing == root for existing in self.workspace_roots):
            self.workspace_roots = (*self.workspace_roots, root)
        return root

    def scoped(
        self,
        raw_base: str | Path,
        *,
        include_existing: bool = False,
        allow_all: bool = False,
    ) -> "PathGuard":
        base = self.allow_root(raw_base)
        if include_existing:
            roots = (base, *(root for root in self.workspace_roots if root != base))
        else:
            roots = (base,)
        return PathGuard(roots, allow_all=allow_all)

    def with_full_access(self) -> "PathGuard":
        return PathGuard(self.workspace_roots, allow_all=True)

    def resolve(self, raw_path: str | None) -> Path:
        if not raw_path:
            raise ValueError("path is required")

        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_roots[0] / candidate

        resolved = candidate.resolve()
        if not self._is_allowed(resolved):
            allowed = ", ".join(str(root) for root in self.workspace_roots)
            raise PermissionError(f"path is outside allowed workspace roots: {resolved}; allowed: {allowed}")
        return resolved

    def _is_allowed(self, path: Path) -> bool:
        if self.allow_all:
            return True
        for root in self.workspace_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False
