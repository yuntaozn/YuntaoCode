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
    assert result["counts"]["test_successes"] == 1
    assert result["risks"] == []


def test_build_run_result_does_not_count_directory_listing_as_code_verification() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "model-viewer.html"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/model-viewer.html"},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {
                    "command": "python",
                    "args": ["-c", "import os; print(os.listdir('D:/workspace'))"],
                },
                "output": {"exit_code": 0, "stdout": "['model-viewer.html']"},
            },
        ],
    )

    assert result["counts"]["verification_successes"] == 0
    assert result["counts"]["test_successes"] == 0
    assert "write_not_verified" in result["risks"]
    assert "test_not_observed" in result["risks"]


def test_build_run_result_counts_reading_written_file_but_marks_no_test() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "model-viewer.html"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/model-viewer.html"},
            },
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/model-viewer.html"},
            },
        ],
    )

    assert result["counts"]["verification_successes"] == 1
    assert result["counts"]["test_successes"] == 0
    assert result["status"] == "partial"
    assert "write_not_verified" not in result["risks"]
    assert "test_not_observed" in result["risks"]


def test_build_run_result_does_not_count_read_before_write_as_verification() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "model-viewer.html"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/model-viewer.html"},
            },
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/model-viewer.html"},
            },
        ],
    )

    assert result["counts"]["verification_successes"] == 0
    assert "write_not_verified" in result["risks"]


def test_build_run_result_does_not_count_test_before_latest_write() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary={"files": [{"path": "app.py"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "pytest"},
                "output": {"exit_code": 0},
            },
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/app.py"},
            },
        ],
    )

    assert result["counts"]["verification_successes"] == 0
    assert result["counts"]["test_successes"] == 0
    assert result["status"] == "partial"
    assert "test_not_observed" in result["risks"]


def test_build_run_result_does_not_count_truncated_preview_as_verification() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "model-viewer.html"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/model-viewer.html"},
            },
            {
                "tool": "filesystem.read_text_preview",
                "status": "success",
                "input": {"path": "D:/workspace/model-viewer.html", "max_bytes": 5000},
                "output": {
                    "path": "D:/workspace/model-viewer.html",
                    "truncated": True,
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["verification_successes"] == 0
    assert "write_not_verified" in result["risks"]
    assert "test_not_observed" in result["risks"]


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


def test_build_run_result_marks_resumable_partial_write() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="document",
        change_summary=None,
        tool_events=[
            {
                "tool": "document.translate_docx",
                "status": "partial",
                "input": {"path": "D:/workspace/book.docx"},
                "output": {
                    "status": "partial_resumable",
                    "partial_resumable": True,
                    "path": "D:/workspace/book_zh.docx",
                    "manifest_path": "D:/workspace/book_zh.docx.translate.json",
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["written_paths"] == ["book_zh.docx"]
    assert result["counts"]["write_partials"] == 1
    assert "partial_write_resumable" in result["risks"]
    assert result["failures"] == []


def test_build_run_result_treats_shell_nonzero_exit_as_failure() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        tool_events=[
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "python -c bad"},
                "output": {
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "SyntaxError: invalid syntax",
                },
            },
        ],
    )

    assert result["status"] == "failure"
    assert result["counts"]["failures"] == 1
    assert result["counts"]["verification_successes"] == 0
    assert result["failures"] == [
        {
            "tool": "shell.run_command",
            "path": "",
            "error": "SyntaxError: invalid syntax",
        }
    ]


def test_build_run_result_reports_shell_timeout_before_exit_code() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        tool_events=[
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "python -m http.server 8000", "timeout": 10},
                "output": {"exit_code": 1, "timed_out": True},
                "error": "command exited with code 1",
            },
        ],
    )

    assert result["status"] == "failure"
    assert result["failures"] == [
        {
            "tool": "shell.run_command",
            "path": "",
            "error": "command timed out after 10s",
        }
    ]


def test_build_run_result_marks_invalid_verification_method_partial_after_write() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "viewer.html"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/viewer.html"},
                "output": {"path": "D:/workspace/viewer.html"},
            },
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/viewer.html"},
                "output": {"path": "D:/workspace/viewer.html"},
            },
            {
                "tool": "shell.run_command",
                "status": "failure",
                "input": {"command": "python -m http.server 8080", "timeout": 5},
                "output": {"exit_code": 1, "timed_out": True, "timeout": 5},
                "error": "command timed out after 5s",
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["write_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["counts"]["failures"] == 1
    assert "invalid_verification_method" in result["risks"]
    assert "runtime_verification_not_observed" in result["risks"]
    assert "test_not_observed" in result["risks"]


def test_build_run_result_uses_contract_deliverable_instead_of_any_state_write() -> None:
    contract = {
        "requires_write": True,
        "requires_verification": True,
        "workspace_path": "D:/workspace/site",
        "expected_min_output_chars": 2000,
        "deliverables": [
            {
                "kind": "code",
                "path_hint": "D:/workspace/site/index.html",
                "description": "Homepage HTML",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace/site",
        mode="coding",
        change_summary={"files": [{"path": "index.html"}]},
        requires_code_write=True,
        expected_min_output_chars=2000,
        task_contract=contract,
        tool_events=[
            {
                "tool": "web.collect_site_assets",
                "status": "success",
                "input": {"output_dir": "D:/workspace/site/site_assets"},
                "output": {"index_path": "D:/workspace/site/site_assets/site-index.json"},
            },
            {
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": "D:/workspace/site/index.html"},
                "output": {
                    "path": "D:/workspace/site/index.html",
                    "size": 44851,
                    "draft_stats": {"text_chars": 39559},
                    "validation": {"valid": True, "text_chars": 39559},
                },
            },
            {
                "tool": "shell.run_command",
                "status": "failure",
                "input": {"command": "python -m http.server 12345 --bind 127.0.0.1"},
                "output": {"reason": "invalid_verification_method", "exit_code": 1},
                "error": "long-running service is not a valid verification command",
            },
            {
                "tool": "filesystem.read_text_preview",
                "status": "success",
                "input": {"path": "D:/workspace/site/index.html"},
                "output": {
                    "path": "D:/workspace/site/index.html",
                    "size": 44851,
                    "truncated": False,
                    "integrity": {"checked": True, "valid": True},
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["written_paths"] == ["index.html"]
    assert result["counts"]["write_successes"] == 1
    assert result["counts"]["verification_successes"] == 2
    assert "write_not_verified" not in result["risks"]
    assert "document_output_too_short" not in result["risks"]
    assert "invalid_verification_method" in result["risks"]
    assert "test_not_observed" in result["risks"]


def test_build_run_result_allows_recovered_non_write_failure() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "report.docx"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "shell.run_command",
                "status": "failure",
                "input": {"command": "python bad.py"},
                "output": {"exit_code": 1, "stderr": "SyntaxError"},
                "error": "command exited with code 1",
            },
            {
                "tool": "document.export_docx",
                "status": "success",
                "input": {"path": "D:/workspace/report.docx"},
                "output": {
                    "path": "D:/workspace/report.docx",
                    "content_chars": 5000,
                    "paragraph_count": 80,
                },
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "Get-Item report.docx"},
                "output": {"exit_code": 0, "stdout": "report.docx"},
            },
        ],
    )

    assert result["status"] == "success"
    assert "recovered_tool_failure" in result["risks"]
    assert result["counts"]["failures"] == 1


def test_build_run_result_marks_low_document_coverage_partial() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="document",
        change_summary={"files": [{"path": "book_zh.docx"}]},
        requires_code_write=True,
        expected_document_coverage=True,
        tool_events=[
            {
                "tool": "document.extract_docx_outline",
                "status": "success",
                "input": {"path": "D:/workspace/book.docx"},
                "output": {
                    "path": "D:/workspace/book.docx",
                    "paragraph_count": 900,
                    "text_chars": 300000,
                },
            },
            {
                "tool": "document.export_docx",
                "status": "success",
                "input": {"path": "D:/workspace/book_zh.docx"},
                "output": {
                    "path": "D:/workspace/book_zh.docx",
                    "content_chars": 3148,
                    "paragraph_count": 12,
                    "nonempty_paragraph_count": 10,
                },
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "Get-Item book_zh.docx"},
                "output": {"exit_code": 0, "stdout": "book_zh.docx"},
            },
        ],
    )

    assert result["status"] == "partial"
    assert "document_output_coverage_low" in result["risks"]
    assert result["failures"] == [
        {
            "tool": "document.export_docx",
            "path": "book_zh.docx",
            "error": (
                "document output coverage is too low: "
                "source_paragraphs=900, output_paragraphs=12, "
                "source_chars=300000, output_chars=3148"
            ),
        }
    ]


def test_build_run_result_marks_document_output_too_short_partial() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="document",
        change_summary={"files": [{"path": "report.docx"}]},
        requires_code_write=True,
        expected_min_output_chars=20000,
        tool_events=[
            {
                "tool": "document.export_draft_docx",
                "status": "success",
                "input": {"path": "D:/workspace/report.docx"},
                "output": {
                    "path": "D:/workspace/report.docx",
                    "content_chars": 12132,
                    "draft_stats": {"text_chars": 11475},
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert "document_output_too_short" in result["risks"]
    assert result["failures"] == [
        {
            "tool": "document.export_draft_docx",
            "path": "report.docx",
            "error": "document output is shorter than requested: expected_min_chars=20000, output_chars=12132",
        }
    ]


def test_build_run_result_marks_repeated_failure_convergence_stop() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary=None,
        convergence_stopped=True,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {},
                "output": {"reason": "invalid_tool_input"},
                "error": "missing required: path, content",
            },
        ],
    )

    assert result["status"] == "stopped"
    assert result["flags"]["convergence_stopped"] is True
    assert "repeated_tool_failure" in result["risks"]


def test_build_run_result_surfaces_tool_call_protocol_failures() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {},
                "error": "The runtime did not execute incomplete arguments.",
                "output": {"reason": "truncated_tool_call"},
            },
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {},
                "error": "Malformed tool arguments.",
                "output": {"reason": "malformed_tool_arguments"},
            },
        ],
        change_summary=None,
        mode="terminal",
        requires_code_write=True,
    )

    assert result["status"] == "failure"
    assert "model_output_truncated" in result["risks"]
    assert "invalid_tool_call_protocol" in result["risks"]


def test_build_run_result_surfaces_runtime_tool_result_risks() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        tool_events=[
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/viewer.html"},
                "output": {
                    "path": "D:/workspace/viewer.html",
                    "integrity": {
                        "checked": True,
                        "valid": False,
                        "issues": ["html appears escaped as text"],
                    },
                },
                "runtime_risks": [
                    {
                        "code": "artifact_integrity_invalid",
                        "blocking": False,
                    }
                ],
            }
        ],
    )

    assert "artifact_integrity_invalid" in result["risks"]


def test_build_run_result_records_all_apply_patch_paths() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        tool_events=[
            {
                "tool": "code.apply_patch",
                "status": "success",
                "input": {"patch": "*** Begin Patch\n*** End Patch"},
                "output": {
                    "paths": [
                        "D:/workspace/src/app.js",
                        "D:/workspace/src/styles.css",
                    ],
                },
            },
        ],
        change_summary=None,
        mode="terminal",
        requires_code_write=True,
    )

    assert result["written_paths"] == ["src/app.js", "src/styles.css"]
