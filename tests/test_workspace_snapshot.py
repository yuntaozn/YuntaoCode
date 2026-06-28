from runtime.workspace_snapshot import (
    build_workspace_snapshot,
    format_workspace_snapshot_for_prompt,
    workspace_snapshot_summary,
)


def test_workspace_snapshot_collects_bounded_project_facts(tmp_path) -> None:
    (tmp_path / "assets" / "models").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "index.html").write_text("<main></main>", encoding="utf-8")
    (tmp_path / "src" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "assets" / "models" / "wall.glb").write_bytes(b"glb")

    snapshot = build_workspace_snapshot(str(tmp_path))

    assert snapshot["schema_version"] == "workspace_snapshot.v1"
    assert snapshot["kind"] == "workspace_snapshot"
    assert snapshot["name"] == tmp_path.name
    assert snapshot["exists"] is True
    assert snapshot["readable"] is True
    assert snapshot["extension_counts"][".html"] == 1
    assert snapshot["extension_counts"][".js"] == 1
    assert snapshot["extension_counts"][".glb"] == 1
    pattern_ids = {item["id"] for item in snapshot["observed_patterns"]}
    assert "code_files" in pattern_ids
    assert "three_d_assets" in pattern_ids
    assert any(path.endswith("wall.glb") for path in snapshot["notable_paths"])


def test_workspace_snapshot_prompt_marks_facts_as_non_routing_context(tmp_path) -> None:
    (tmp_path / "lesson.html").write_text("<html></html>", encoding="utf-8")

    prompt = format_workspace_snapshot_for_prompt(build_workspace_snapshot(str(tmp_path)))

    assert "Workspace fact snapshot" in prompt
    assert "not instructions or a forced route" in prompt
    assert "lesson.html" in prompt


def test_workspace_snapshot_summary_is_stable_for_missing_path(tmp_path) -> None:
    snapshot = build_workspace_snapshot(str(tmp_path / "missing"))
    summary = workspace_snapshot_summary(snapshot)

    assert summary["exists"] is False
    assert summary["readable"] is False
    assert summary["error"] == "workspace_path_not_found"
