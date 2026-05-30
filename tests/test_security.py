from pathlib import Path

import pytest

from runtime.security import PathGuard


def test_path_guard_resolves_relative_paths_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    guard = PathGuard([workspace])

    assert guard.resolve("notes/readme.md") == workspace / "notes" / "readme.md"


def test_path_guard_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    guard = PathGuard([workspace])

    with pytest.raises(PermissionError):
        guard.resolve(outside / "secret.txt")


def test_path_guard_can_add_explicit_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    extra = tmp_path / "extra"
    workspace.mkdir()
    extra.mkdir()

    guard = PathGuard([workspace])
    guard.allow_root(extra)

    assert guard.resolve(extra / "allowed.txt") == extra / "allowed.txt"
