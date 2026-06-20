from runtime.run_result import build_run_result


def test_build_run_result_ignores_document_min_chars_for_code_contract() -> None:
    contract = {
        "intent": "write_required",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "expected_min_output_chars": 30000,
        "deliverables": [
            {"kind": "code", "path_hint": "D:/workspace/src/app.js"}
        ],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary={"files": [{"path": "src/app.js"}]},
        requires_code_write=True,
        expected_min_output_chars=30000,
        task_contract=contract,
        tool_events=[
            {
                "tool": "code.edit_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/app.js"},
                "output": {"path": "D:/workspace/src/app.js"},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "node --check src/app.js"},
                "output": {"exit_code": 0},
            },
        ],
    )

    assert result["status"] == "success"
    assert "document_output_too_short" not in result["risks"]


def test_build_run_result_applies_document_min_chars_to_document_contract() -> None:
    contract = {
        "intent": "document_export",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "expected_min_output_chars": 30000,
        "deliverables": [
            {"kind": "document", "path_hint": "D:/workspace/out.docx"}
        ],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="document",
        change_summary={"files": [{"path": "out.docx"}]},
        expected_min_output_chars=30000,
        task_contract=contract,
        tool_events=[
            {
                "tool": "document.export_docx",
                "status": "success",
                "input": {"output_path": "D:/workspace/out.docx"},
                "output": {"path": "D:/workspace/out.docx", "content_chars": 1000},
            }
        ],
    )

    assert result["status"] == "partial"
    assert "document_output_too_short" in result["risks"]


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


def test_build_run_result_applies_min_chars_to_finalized_text_file() -> None:
    contract = {
        "intent": "write_required",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "expected_min_output_chars": 12000,
        "deliverables": [
            {"kind": "document", "path_hint": "D:/workspace/short-story.docx"}
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="document",
        change_summary={"files": [{"path": "short-story.txt"}]},
        expected_min_output_chars=12000,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": "D:/workspace/short-story.txt"},
                "output": {
                    "path": "D:/workspace/short-story.txt",
                    "draft_stats": {"text_chars": 5200},
                    "validation": {"valid": True, "text_chars": 5200},
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["flags"]["observed_text_output_chars"] == 5200
    assert "document_output_too_short" in result["risks"]
    assert result["failures"] == [
        {
            "tool": "filesystem.finalize_text_file",
            "path": "short-story.txt",
            "error": "document output is shorter than requested: expected_min_chars=12000, output_chars=5200",
        }
    ]


def test_build_run_result_requires_text_length_evidence_for_long_document() -> None:
    contract = {
        "intent": "document_export",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "expected_min_output_chars": 12000,
        "deliverables": [
            {"kind": "document", "path_hint": "D:/workspace/story.txt"}
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="document",
        change_summary={"files": [{"path": "story.txt"}]},
        expected_min_output_chars=12000,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": "D:/workspace/story.txt"},
                "output": {
                    "path": "D:/workspace/story.txt",
                    "size": 60000,
                    "validation": {"valid": True},
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["flags"]["text_length_evidence_observed"] is True
    assert result["flags"]["observed_text_output_chars"] == 0
    assert "document_output_length_unknown" in result["risks"]
