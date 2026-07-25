from pathlib import Path

import pytest

from runtime.run_artifact_access import (
    collect_run_artifact_paths,
    resolve_run_artifact_path_from_evidence,
    run_artifact_image_preview_media_type,
)
from runtime.security import PathGuard


def test_resolve_run_artifact_path_allows_recorded_workspace_and_data_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = tmp_path / "data"
    preview = data_dir / "task-artifacts" / "run-1" / "preview.png"
    workspace.mkdir()
    preview.parent.mkdir(parents=True)
    (workspace / "viewer.html").write_text("<!doctype html>", encoding="utf-8")
    preview.write_bytes(b"png")
    evidence = {
        "artifacts": [
            {"path": "viewer.html"},
            {"path": str(preview), "metadata": {"model_context_path": str(preview)}},
        ],
        "verification_evidence": [{"path": "viewer.html"}],
    }

    assert collect_run_artifact_paths(evidence) == [
        "viewer.html",
        str(preview).replace("\\", "/"),
    ]
    assert resolve_run_artifact_path_from_evidence(
        evidence,
        "viewer.html",
        path_guard=PathGuard([workspace]),
        data_dir=data_dir,
    ) == workspace / "viewer.html"
    assert resolve_run_artifact_path_from_evidence(
        evidence,
        str(preview),
        path_guard=PathGuard([workspace]),
        data_dir=data_dir,
    ) == preview


def test_resolve_run_artifact_path_rejects_unrecorded_workspace_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "secret.txt").write_text("not part of run", encoding="utf-8")

    with pytest.raises(PermissionError, match="not recorded"):
        resolve_run_artifact_path_from_evidence(
            {"artifacts": [{"path": "viewer.html"}]},
            "secret.txt",
            path_guard=PathGuard([workspace]),
            data_dir=tmp_path / "data",
        )


def test_resolve_run_artifact_path_rejects_recorded_path_outside_boundaries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = tmp_path / "data"
    outside = tmp_path / "outside" / "preview.png"
    workspace.mkdir()
    data_dir.mkdir()
    outside.parent.mkdir()
    outside.write_bytes(b"png")

    with pytest.raises(PermissionError, match="outside"):
        resolve_run_artifact_path_from_evidence(
            {"artifacts": [{"path": str(outside)}]},
            str(outside),
            path_guard=PathGuard([workspace]),
            data_dir=data_dir,
        )


def test_run_artifact_image_preview_media_type_only_allows_common_images() -> None:
    assert run_artifact_image_preview_media_type(Path("screen.png")) == "image/png"
    assert run_artifact_image_preview_media_type(Path("photo.JPG")) == "image/jpeg"
    assert run_artifact_image_preview_media_type(Path("page.webp")) == "image/webp"
    assert run_artifact_image_preview_media_type(Path("report.pdf")) == ""
    assert run_artifact_image_preview_media_type(Path("vector.svg")) == ""
