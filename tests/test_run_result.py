from runtime.run_result import build_run_result


def test_build_run_result_records_writes_verification_and_risks() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary={"files": [{"path": "src/app.py"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "code.edit_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/app.py"},
                "output": {"path": "D:/workspace/src/app.py"},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "pytest"},
                "output": {"exit_code": 0},
            },
        ],
    )

    assert result["schema_version"] == "0.1"
    assert result["kind"] == "run_result"
    assert result["status"] == "success"
    assert result["changed_paths"] == ["src/app.py"]
    assert result["written_paths"] == ["src/app.py"]
    assert result["counts"]["write_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["risks"] == []


def test_build_run_result_marks_partial_write_failures() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary=None,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/README.md"},
            },
            {
                "tool": "code.edit_file",
                "status": "failure",
                "input": {"path": "D:/workspace/runtime/app.py"},
                "error": "old_text not found",
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["written_paths"] == ["README.md"]
    assert result["failures"] == [
        {
            "tool": "code.edit_file",
            "path": "runtime/app.py",
            "error": "old_text not found",
        }
    ]
    assert "partial_write_failure" in result["risks"]
    assert "write_not_verified" in result["risks"]
