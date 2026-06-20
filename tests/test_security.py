from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from runtime.api.health import HEALTH_SERVICE_NAME
from runtime.security import PathGuard
from runtime.workspace_store import LEGACY_WORKSPACE_ID_NAMESPACE, stable_workspace_id


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


def test_health_service_name_uses_current_product_name() -> None:
    assert HEALTH_SERVICE_NAME == "yuntaocode"


def test_workspace_id_keeps_legacy_namespace_for_compatibility(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    normalized = str(workspace.resolve()).lower()

    assert LEGACY_WORKSPACE_ID_NAMESPACE == "local-intelligent-terminal"
    assert stable_workspace_id(workspace) == str(
        uuid5(NAMESPACE_URL, f"{LEGACY_WORKSPACE_ID_NAMESPACE}:{normalized}")
    )
