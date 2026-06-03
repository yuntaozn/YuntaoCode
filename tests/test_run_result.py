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
