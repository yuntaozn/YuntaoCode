from runtime.artifacts import build_run_artifacts, summarize_run_artifacts


def test_build_run_artifacts_unifies_file_visual_debug_and_verification_records() -> None:
    records = build_run_artifacts(
        workspace_path="D:/workspace",
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "declared_roles": ["deliverable"],
                "input": {"path": "D:/workspace/viewer.html"},
                "output": {
                    "path": "D:/workspace/viewer.html",
                    "size": 1200,
                    "validation": {"valid": True, "text_chars": 1100},
                },
            },
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                "declared_roles": ["verification"],
                "output": {
                    "path": "D:/workspace/task-artifacts/preview/viewer.png",
                    "artifacts": ["screenshot", "visual_evidence"],
                    "source_type": "local_html",
                    "source_path": "viewer.html",
                    "width": 1024,
                    "height": 768,
                    "size": 4096,
                    "has_runtime_errors": False,
                },
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "declared_roles": ["verification"],
                "output": {
                    "command": "node --check viewer.html",
                    "exit_code": 0,
                    "stdout": "ok",
                },
            },
        ],
        verification_evidence=[
            {
                "tool": "shell.run_command",
                "path": "viewer.html",
                "strength": "standard",
                "modalities": ["runtime"],
            }
        ],
    )

    final = next(item for item in records if item["role"] == "final")
    assert final["artifact_kind"] == "file"
    assert final["path"] == "viewer.html"
    assert final["source_tool"] == "filesystem.write_file"
    assert final["metadata"]["size"] == 1200
    assert final["metadata"]["validation"] == {"valid": True, "text_chars": 1100}

    screenshot = next(item for item in records if item["role"] == "screenshot")
    assert screenshot["artifact_kind"] == "screenshot"
    assert screenshot["path"] == "task-artifacts/preview/viewer.png"
    assert screenshot["can_preview"] is True
    assert screenshot["can_enter_model_context"] is True
    assert screenshot["verification_relevance"] == "verification"
    assert screenshot["metadata"]["width"] == 1024
    assert screenshot["metadata"]["model_context_path"] == "task-artifacts/preview/viewer.png"

    command_log = next(item for item in records if item["role"] == "log")
    assert command_log["artifact_kind"] == "command_log"
    assert command_log["source_tool"] == "shell.run_command"
    assert command_log["metadata"]["exit_code"] == 0
    assert command_log["verification_relevance"] == "diagnostic"

    verification = [
        item for item in records
        if item["role"] == "verification" and item["path"] == "viewer.html"
    ][0]
    assert verification["artifact_kind"] == "verification"
    assert verification["metadata"]["strength"] == "standard"

    summary = summarize_run_artifacts(records)
    assert summary["schema_version"] == "run_artifact_summary.v1"
    assert summary["count"] == len(records)
    assert summary["by_role"]["final"] == 1
    assert summary["by_role"]["screenshot"] == 1
    assert summary["by_role"]["log"] == 1
    assert summary["by_verification_relevance"]["deliverable"] == 1
    assert summary["by_verification_relevance"]["verification"] >= 2
    assert summary["by_verification_relevance"]["diagnostic"] == 1
    assert summary["changed_paths"] == ["viewer.html"]
    assert summary["visual_paths"] == ["task-artifacts/preview/viewer.png"]
    assert summary["preview_paths"] == [
        "viewer.html",
        "task-artifacts/preview/viewer.png",
    ]
    assert summary["verification_paths"] == [
        "task-artifacts/preview/viewer.png",
        "viewer.html",
    ]
    assert summary["model_context_paths"] == [
        "task-artifacts/preview/viewer.png",
        "viewer.html",
    ]
    indexed = {item["path"]: item for item in summary["path_index"]}
    assert indexed["viewer.html"]["roles"] == ["final", "verification"]
    assert indexed["viewer.html"]["artifact_kinds"] == ["file", "verification"]
    assert indexed["viewer.html"]["can_preview"] is True
    assert indexed["viewer.html"]["can_enter_model_context"] is True
    assert indexed["task-artifacts/preview/viewer.png"]["roles"] == ["screenshot", "verification"]
    assert indexed["task-artifacts/preview/viewer.png"]["artifact_kinds"] == ["screenshot", "verification"]
    assert indexed["task-artifacts/preview/viewer.png"]["can_enter_model_context"] is True
    assert summary["flags"]["has_previewable_artifacts"] is True
    assert summary["flags"]["has_diagnostic_artifacts"] is True
    assert summary["flags"]["has_model_context_artifacts"] is True


def test_build_run_artifacts_keeps_legacy_artifacts_compatible() -> None:
    records = build_run_artifacts(
        workspace_path="D:/workspace",
        legacy_artifacts=[
            {
                "kind": "file",
                "path": "D:/workspace/src/app.py",
                "tool": "code.edit_file",
                "status": "success",
            }
        ],
    )

    assert records == [
        {
            "schema_version": "run_artifact.v1",
            "kind": "run_artifact",
            "artifact_kind": "file",
            "role": "final",
            "path": "src/app.py",
            "url": "",
            "status": "success",
            "source_tool": "code.edit_file",
            "tool": "code.edit_file",
            "source_task_id": "",
            "source_event_index": None,
            "can_preview": True,
            "can_enter_model_context": False,
            "verification_relevance": "deliverable",
            "metadata": {},
            "id": records[0]["id"],
        }
    ]
