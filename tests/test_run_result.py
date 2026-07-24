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
    assert result["artifacts"] == [
        {
            "kind": "file",
            "path": "src/app.py",
            "tool": "code.edit_file",
            "status": "success",
        }
    ]
    final_artifact = next(item for item in result["run_artifacts"] if item["role"] == "final")
    assert final_artifact["artifact_kind"] == "file"
    assert final_artifact["path"] == "src/app.py"
    assert final_artifact["source_tool"] == "code.edit_file"
    assert result["artifact_summary"]["flags"]["has_final_artifacts"] is True
    assert result["counts"]["run_artifacts"] == len(result["run_artifacts"])
    assert result["counts"]["write_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["counts"]["test_successes"] == 1
    assert result["counts"]["debug_sessions"] == 1
    assert result["debug_audit"]["schema_version"] == "debug_audit.v1"
    assert result["debug_audit"]["counts"]["debug_sessions"] == 1
    assert result["debug_audit"]["flags"]["has_debug_evidence"] is True
    assert result["verification_closure"]["schema_version"] == "verification_closure.v1"
    assert result["verification_closure"]["counts"]["final_artifacts"] == 1
    assert result["verification_closure"]["counts"]["debug_sessions"] == 1
    assert result["verification_closure"]["flags"]["has_debug_evidence"] is True
    assert result["debug_sessions"][0]["tool"] == "shell.run_command"
    assert result["debug_sessions"][0]["exit_code"] == 0
    assert result["risks"] == []


def test_build_run_result_succeeds_when_code_write_has_real_test_verification() -> None:
    contract = {
        "intent": "write_required",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {"kind": "code", "path_hint": "D:/workspace/src/app.js"}
        ],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary={"files": [{"path": "src/app.js"}]},
        requires_code_write=True,
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
                "input": {"command": "npm test"},
                "output": {"exit_code": 0},
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["write_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["counts"]["test_successes"] == 1
    assert "write_not_verified" not in result["risks"]
    assert "test_not_observed" not in result["risks"]


def test_build_run_result_does_not_treat_py_compile_as_behavioral_api_verification() -> None:
    contract = {
        "intent": "write_required",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["behavioral"],
        "deliverables": [
            {"kind": "code", "path_hint": "D:/workspace/backend/main.py"}
        ],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "backend/main.py"}]},
        requires_code_write=True,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/backend/main.py"},
                "output": {"path": "D:/workspace/backend/main.py"},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "python -m py_compile main.py"},
                "output": {"exit_code": 0},
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["verification_successes"] == 1
    assert result["counts"]["test_successes"] == 0
    assert result["verification_evidence"][0]["strength"] == "standard"
    assert result["verification_evidence"][0]["modalities"] == ["structural"]
    assert result["missing_verification_modalities"] == ["behavioral"]
    assert "verification_modality_missing" in result["risks"]
    assert "test_not_observed" in result["risks"]


def test_build_run_result_accepts_visual_verification_for_visual_code_task() -> None:
    contract = {
        "intent": "write_required",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [
            {"kind": "code", "path_hint": "D:/workspace/viewer.html"}
        ],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "viewer.html"}]},
        requires_code_write=True,
        task_contract=contract,
        tool_events=[
            {
                "tool": "code.edit_file",
                "status": "success",
                "input": {"path": "D:/workspace/viewer.html"},
                "output": {"path": "D:/workspace/viewer.html"},
            },
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                "input": {"path": "D:/workspace/viewer.html"},
                "output": {
                    "path": "D:/workspace/preview.png",
                    "roles": ["verification"],
                    "artifact_kind": "screenshot",
                    "verification_strength": "standard",
                    "has_runtime_errors": False,
                },
            },
        ],
    )

    assert result["status"] == "success"
    assert result["observed_verification_modalities"] == ["visual"]
    assert result["missing_verification_modalities"] == []
    assert result["counts"]["visual_evidence"] == 1
    assert result["visual_verification"]["schema_version"] == "visual_verification.v1"
    assert result["visual_verification"]["counts"]["visual_evidence"] == 1
    assert result["visual_verification"]["flags"]["visual_observed"] is True
    assert result["visual_evidence"][0]["tool"] == "preview.capture_local_html"
    assert result["visual_evidence"][0]["path"] == "D:/workspace/preview.png"
    assert result["visual_evidence"][0]["model_context_eligible"] is True
    screenshot = next(item for item in result["run_artifacts"] if item["role"] == "screenshot")
    assert screenshot["path"] == "preview.png"
    assert screenshot["can_enter_model_context"] is True
    assert result["artifact_summary"]["visual_paths"] == ["preview.png"]
    assert result["verification_closure"]["counts"]["visual_artifacts"] == 1
    assert result["verification_closure"]["flags"]["has_visual_evidence"] is True
    assert "test_not_observed" not in result["risks"]


def test_build_run_result_preserves_compact_visual_and_debug_summaries() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract={
            "requires_write": False,
            "requires_state_change": False,
            "requires_verification": True,
            "required_verification_modalities": ["visual"],
            "deliverables": [{"kind": "answer", "description": "Visual check"}],
        },
        tool_events=[
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                "output": {
                    "roles": ["verification"],
                    "verification_strength": "standard",
                    "artifact_kind": "screenshot",
                    "path": "C:/Users/demo/AppData/Local/YuntaoCode/task-artifacts/run/preview/index.png",
                    "visual_evidence": {
                        "schema_version": "visual_evidence.v1",
                        "kind": "visual_evidence",
                        "source_type": "local_html",
                        "source_url": "http://127.0.0.1:1234/index.html",
                        "source_path": "D:/workspace/index.html",
                        "path": "C:/Users/demo/AppData/Local/YuntaoCode/task-artifacts/run/preview/index.png",
                        "artifact_kind": "screenshot",
                        "format": "png",
                        "width": 1440,
                        "height": 1000,
                        "size": 272301,
                        "captured_at": "2026-07-01T15:22:54Z",
                        "title": "Demo",
                        "status_code": 200,
                        "has_runtime_errors": False,
                        "console_error_count": 0,
                        "page_error_count": 0,
                        "failed_request_count": 1,
                        "model_context_eligible": True,
                        "model_context_modality": "image",
                    },
                    "debug_session": {
                        "schema_version": "debug_session.v1",
                        "kind": "debug_session",
                        "source_type": "preview.capture_page",
                        "command": "playwright capture http://127.0.0.1:1234/index.html",
                        "executable": "playwright.chromium",
                        "cwd": "D:/workspace",
                        "exit_code": 0,
                        "timed_out": False,
                        "timeout": 20,
                        "duration_seconds": 13.165,
                        "stdout_chars": 36,
                        "stderr_chars": 0,
                        "service": {"kind": "browser_preview", "status_code": 200},
                        "diagnostic_count": 0,
                        "status": "success",
                        "has_runtime_errors": False,
                    },
                },
            },
        ],
    )

    assert result["status"] == "success"
    assert result["visual_evidence"][0]["path"].endswith("index.png")
    assert result["visual_evidence"][0]["source_type"] == "local_html"
    assert result["visual_evidence"][0]["width"] == 1440
    assert result["visual_verification"]["counts"]["debug_sessions"] == 1
    assert result["visual_verification"]["counts"]["failed_requests"] == 1
    assert result["debug_audit"]["counts"]["preview_sessions"] == 1
    assert result["debug_audit"]["counts"]["service_sessions"] == 1
    assert result["debug_audit"]["flags"]["has_preview_service"] is True
    assert result["debug_sessions"][0]["command"].startswith("playwright capture")
    assert result["debug_sessions"][0]["exit_code"] == 0
    assert result["debug_sessions"][0]["service"]["status_code"] == 200
    assert any(item["role"] == "screenshot" for item in result["run_artifacts"])
    assert any(item["role"] == "log" for item in result["run_artifacts"])
    assert result["artifact_summary"]["flags"]["has_visual_artifacts"] is True


def test_build_run_result_tracks_verification_only_content_gap() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": True,
        "required_verification_modalities": ["content", "behavioral"],
        "deliverables": [{"kind": "answer", "description": "Verification summary"}],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/app.js"},
                "output": {
                    "path": "D:/workspace/src/app.js",
                    "content": "function renderStep() {}",
                },
            }
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["deliverable_successes"] == 0
    assert result["counts"]["verification_successes"] == 1
    assert result["observed_verification_modalities"] == ["content"]
    assert result["missing_verification_modalities"] == ["behavioral"]
    assert "required_verification_not_satisfied" in result["risks"]
    assert "target_deliverable_not_observed" not in result["risks"]


def test_build_run_result_succeeds_for_verification_only_behavioral_evidence() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": True,
        "required_verification_modalities": ["content", "behavioral"],
        "deliverables": [{"kind": "answer", "description": "Verification summary"}],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/app.js"},
                "output": {
                    "path": "D:/workspace/src/app.js",
                    "content": "function renderStep() {}",
                },
            },
            {
                "tool": "preview.interact_page",
                "status": "success",
                "output": {
                    "roles": ["verification"],
                    "verification_strength": "standard",
                    "artifact_kind": "screenshot",
                    "artifacts": ["screenshot", "interaction_trace", "dom_text"],
                    "path": "D:/workspace/after.png",
                    "interaction": {
                        "action_count": 2,
                        "assertion_failed_count": 0,
                    },
                    "text": "答题交互正常显示反馈",
                    "has_runtime_errors": False,
                },
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["deliverable_successes"] == 0
    assert result["counts"]["verification_successes"] == 2
    assert result["observed_verification_modalities"] == [
        "content",
        "visual",
        "behavioral",
    ]
    assert result["missing_verification_modalities"] == []


def test_build_run_result_marks_model_error_after_write_as_partial() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="paper",
        change_summary={"files": [{"path": "draft.txt"}]},
        tool_events=[
            {
                "tool": "code.replace_text",
                "status": "success",
                "input": {"path": "D:/workspace/draft.txt"},
                "output": {"path": "D:/workspace/draft.txt"},
            }
        ],
        model_error="HTTP 400: invalid enable_thinking",
    )

    assert result["status"] == "partial"
    assert result["flags"]["model_provider_error"] is True
    assert result["flags"]["observed_state_change"] is True
    assert "model_provider_error" in result["risks"]
    assert result["failure_details"] == [
        {
            "tool": "model.provider",
            "path": "",
            "role": "model",
            "impact": "degraded",
        }
    ]


def test_build_run_result_marks_model_error_without_tools_as_failure() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="paper",
        change_summary=None,
        tool_events=[],
        model_error="HTTP 400: invalid request",
    )

    assert result["status"] == "failure"
    assert result["counts"]["blocking_failures"] == 1
    assert result["failure_details"][0]["tool"] == "model.provider"


def test_build_run_result_marks_invalid_final_answer_without_tools_as_failure() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        tool_events=[],
        final_answer_error="model stopped at a pending action instead of answering",
    )

    assert result["status"] == "failure"
    assert result["counts"]["blocking_failures"] == 1
    assert result["failures"] == [
        {
            "tool": "model.final_answer",
            "path": "",
            "error": "model stopped at a pending action instead of answering",
        }
    ]
    assert result["failure_details"][0]["tool"] == "model.final_answer"
    assert result["flags"]["invalid_final_answer"] is True
    assert "invalid_final_answer" in result["risks"]


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


def test_build_run_result_accepts_text_length_check_as_content_verification_after_edit() -> None:
    contract = {
        "intent": "write_required",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["content", "structural"],
        "expected_min_output_chars": 3000,
        "deliverables": [
            {
                "kind": "file",
                "path_hint": "chapter-011",
                "path_policy": "hint",
                "description": "Long-form chapter text",
            }
        ],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "chapter-011-underground-meeting.md"}]},
        requires_code_write=False,
        expected_min_output_chars=3000,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": "D:/workspace/chapter-011-underground-meeting.md"},
                "output": {
                    "path": "D:/workspace/chapter-011-underground-meeting.md",
                    "artifact_kind": "text_file",
                    "size": 12885,
                    "draft_stats": {"text_chars": 4480, "line_count": 171},
                    "validation": {"valid": True, "text_chars": 4480, "line_count": 171},
                },
            },
            {
                "tool": "code.edit_file",
                "status": "success",
                "input": {"path": "D:/workspace/chapter-011-underground-meeting.md"},
                "output": {
                    "path": "D:/workspace/chapter-011-underground-meeting.md",
                    "diff_preview": "- old\n+ new",
                    "encoding": "utf-8",
                },
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {
                    "command": "powershell",
                    "args": [
                        "-Command",
                        "(Get-Content 'D:/workspace/chapter-011-underground-meeting.md' -Raw).Length",
                    ],
                },
                "output": {"exit_code": 0, "stdout": "6765\r\n", "stderr": ""},
            },
            {
                "tool": "code.search_text",
                "status": "success",
                "input": {
                    "path": "D:/workspace/chapter-011-underground-meeting.md",
                    "query": "previous chapter",
                },
                "output": {"matches": []},
            },
        ],
    )

    assert result["status"] == "success"
    assert result["observed_verification_modalities"] == ["structural", "content"]
    assert result["missing_verification_modalities"] == []
    assert "required_verification_not_satisfied" not in result["risks"]
    assert "verification_modality_missing" not in result["risks"]
    assert "execution_contract_failed" not in result["risks"]
    assert "deliverable_path_hint_changed" not in result["risks"]


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


def test_build_run_result_degrades_shell_zero_exit_with_exception_stderr() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary={"files": [{"path": "src/app.js"}]},
        requires_code_write=True,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/app.js"},
                "output": {"path": "D:/workspace/src/app.js"},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "npm run build"},
                "output": {
                    "exit_code": 0,
                    "stdout": "",
                    "stderr": "HttpListenerException: 参数错误。",
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["verification_successes"] == 0
    assert "shell_stderr_warning" in result["risks"]
    assert "write_not_verified" in result["risks"]
    assert "test_not_observed" in result["risks"]


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
    assert result["artifacts"][0]["kind"] == "file"
    assert result["artifacts"][0]["path"] == "index.html"
    assert result["artifacts"][0]["size"] == 44851
    assert result["counts"]["write_successes"] == 1
    assert result["counts"]["verification_successes"] == 2
    assert "write_not_verified" not in result["risks"]
    assert "document_output_too_short" not in result["risks"]
    assert "invalid_verification_method" in result["risks"]
    assert "test_not_observed" in result["risks"]


def test_build_run_result_audits_alternative_hinted_deliverable_path() -> None:
    contract = {
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {
                "kind": "code",
                "path_hint": "D:/workspace/build_house.py",
                "path_policy": "hint",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary={"files": [{"path": "build_house_v2.py"}]},
        requires_code_write=True,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": "D:/workspace/build_house_v2.py"},
                "output": {
                    "path": "D:/workspace/build_house_v2.py",
                    "validation": {"valid": True},
                },
            }
        ],
    )

    assert result["counts"]["deliverable_successes"] == 1
    assert result["written_paths"] == ["build_house_v2.py"]
    assert "target_deliverable_not_observed" not in result["risks"]
    assert "deliverable_path_hint_changed" in result["risks"]
    assert result["deliverable_path_deviations"][0]["actual_paths"] == [
        "d:/workspace/build_house_v2.py"
    ]


def test_build_run_result_keeps_verification_for_each_written_artifact() -> None:
    paths = ["index.html", "style.css", "main.js"]
    contract = {
        "requires_write": True,
        "requires_verification": True,
        "required_verification_modalities": ["structural"],
        "deliverables": [
            {"kind": "code", "path_hint": f"D:/workspace/{path}", "path_policy": "exact"}
            for path in paths
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary={"files": [{"path": path} for path in paths]},
        requires_code_write=True,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": f"D:/workspace/{path}"},
                "output": {
                    "path": f"D:/workspace/{path}",
                    "validation": {"valid": True, "text_chars": 1000},
                },
            }
            for path in paths
        ],
    )

    assert result["counts"]["verification_successes"] == 3
    assert [item["path"] for item in result["verification_evidence"]] == paths
    assert result["missing_verification_modalities"] == []


def test_build_run_result_accepts_verified_external_state_deliverable() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {
                "kind": "external_state",
                "path_hint": "",
                "description": "Current Blender scene",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        requires_code_write=False,
        task_contract=contract,
        tool_events=[
            {
                "tool": "mcp_blender.execute_blender_code",
                "status": "success",
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            },
            {
                "tool": "mcp_blender.get_scene_info",
                "status": "success",
                "output": {"roles": ["evidence", "verification"]},
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["deliverable_successes"] == 1
    assert result["counts"]["file_write_successes"] == 0
    assert result["counts"]["external_state_changes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert "execution_contract_failed" not in result["risks"]


def test_build_run_result_accepts_verified_file_delete_deliverable() -> None:
    contract = {
        "intent": "write_required",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {
                "kind": "file",
                "path_hint": "obsolete.md",
                "path_policy": "exact",
                "description": "Delete obsolete generated document",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary=None,
        requires_code_write=True,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.delete_file",
                "status": "success",
                "input": {"path": "D:/workspace/obsolete.md"},
                "output": {
                    "path": "D:/workspace/obsolete.md",
                    "deleted": True,
                    "effects": ["file_delete", "local_state_change"],
                    "roles": ["deliverable", "verification"],
                    "verification_strength": "standard",
                },
            }
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["deliverable_successes"] == 1
    assert result["counts"]["file_write_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["written_paths"] == ["obsolete.md"]
    assert "target_deliverable_not_observed" not in result["risks"]
    assert "required_verification_not_satisfied" not in result["risks"]


def test_build_run_result_keeps_auxiliary_failure_auditable_without_failing_analysis() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract={
            "intent": "read_only_analysis",
            "requires_write": False,
            "requires_state_change": False,
            "requires_verification": False,
            "deliverables": [{"kind": "answer"}],
        },
        tool_events=[
            {
                "tool": "filesystem.scan_folder",
                "status": "success",
                "input": {"path": "D:/workspace"},
            },
            {
                "tool": "git.status",
                "status": "failure",
                "input": {"path": "D:/workspace"},
                "error": "not a git repository",
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["incidental_failures"] == 1
    assert result["counts"]["blocking_failures"] == 0
    assert result["failure_details"] == [
        {
            "tool": "git.status",
            "path": ".",
            "role": "unknown",
            "impact": "incidental",
        }
    ]
    assert "incidental_tool_failure" in result["risks"]


def test_build_run_result_treats_read_only_evidence_as_answer_verification() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": True,
        "deliverables": [{"kind": "answer", "description": "Project structure analysis"}],
    }

    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.scan_folder",
                "status": "success",
                "input": {"path": "D:/workspace"},
                "output": {"path": "D:/workspace"},
            },
            {
                "tool": "code.list_project_files",
                "status": "success",
                "input": {"path": "D:/workspace"},
                "output": {"path": "D:/workspace"},
            },
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/README.md"},
                "output": {"path": "D:/workspace/README.md", "content": "# Demo"},
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["verification_successes"] == 3
    assert result["observed_verification_modalities"] == ["structural", "content"]
    assert "required_verification_not_satisfied" not in result["risks"]
    assert "verification_modality_missing" not in result["risks"]
    assert "execution_contract_failed" not in result["risks"]


def test_build_run_result_marks_recovered_delivery_and_weak_verification_partial() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "House model"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "mcp_demo.execute",
                "status": "failure",
                "declared_effects": ["external_state_change"],
                "declared_roles": ["deliverable"],
                "error": "first attempt failed",
            },
            {
                "tool": "mcp_demo.execute",
                "status": "success",
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            },
            {
                "tool": "mcp_demo.screenshot",
                "status": "failure",
                "declared_roles": ["verification"],
                "declared_verification_strength": "standard",
                "error": "screenshot unsupported",
            },
            {
                "tool": "mcp_demo.scene_info",
                "status": "success",
                "output": {
                    "roles": ["evidence", "verification"],
                    "verification_strength": "weak",
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["deliverable_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["counts"]["recovered_failures"] == 1
    assert result["counts"]["degraded_failures"] == 1
    assert result["required_verification_strength"] == "standard"
    assert result["verification_evidence"][0]["strength"] == "weak"
    assert result["verification_evidence"][0]["sufficient"] is False
    assert "required_verification_not_satisfied" in result["risks"]
    assert "verification_evidence_weak" in result["risks"]


def test_build_run_result_accepts_recovered_external_state_with_structured_verification() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "House model"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        contract_failed=True,
        tool_events=[
            {
                "tool": "mcp_demo.execute",
                "status": "failure",
                "declared_effects": ["external_state_change"],
                "declared_roles": ["deliverable"],
                "error": "first attempt failed",
            },
            {
                "tool": "mcp_demo.execute",
                "status": "success",
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            },
            {
                "tool": "mcp_demo.screenshot",
                "status": "failure",
                "declared_roles": ["verification"],
                "declared_verification_strength": "standard",
                "error": "screenshot unsupported",
            },
            {
                "tool": "mcp_demo.scene_info",
                "status": "success",
                "output": {
                    "roles": ["evidence", "verification"],
                    "verification_strength": "weak",
                    "structured_content": {
                        "object_count": 11,
                        "objects": ["house", "roof"],
                    },
                },
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["deliverable_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["counts"]["recovered_failures"] == 2
    assert result["counts"]["degraded_failures"] == 0
    assert result["counts"]["unrecovered_write_failures"] == 0
    assert result["verification_evidence"][0]["strength"] == "standard"
    assert result["verification_evidence"][0]["sufficient"] is True
    assert result["flags"]["contract_failed"] is True
    assert result["flags"]["unresolved_contract_failed"] is False
    assert "required_verification_not_satisfied" not in result["risks"]
    assert "verification_evidence_weak" not in result["risks"]
    assert "execution_contract_failed" not in result["risks"]
    assert "partial_write_failure" not in result["risks"]
    assert "recovered_tool_failure" in result["risks"]


def test_build_run_result_requires_visual_evidence_when_contract_requires_visual_modality() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [{"kind": "external_state", "description": "House appearance"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "mcp_demo.execute",
                "status": "success",
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            },
            {
                "tool": "mcp_demo.scene_info",
                "status": "success",
                "output": {
                    "roles": ["evidence", "verification"],
                    "verification_strength": "weak",
                    "structured_content": {"object_count": 11},
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["required_verification_modalities"] == ["visual"]
    assert result["observed_verification_modalities"] == ["structural"]
    assert result["missing_verification_modalities"] == ["visual"]
    assert result["verification_evidence"][0]["modalities"] == ["structural"]
    assert "visual_verification_not_observed" in result["risks"]
    assert "verification_modality_missing" in result["risks"]
    assert "verification_evidence_weak" not in result["risks"]


def test_build_run_result_accepts_visual_evidence_for_visual_modality() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [{"kind": "external_state", "description": "House appearance"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "mcp_demo.execute",
                "status": "success",
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            },
            {
                "tool": "mcp_demo.get_viewport_screenshot",
                "status": "success",
                "output": {
                    "roles": ["verification"],
                    "verification_strength": "standard",
                    "artifact_kind": "screenshot",
                    "path": "D:/workspace/scene.png",
                },
            },
        ],
    )

    assert result["status"] == "success"
    assert result["observed_verification_modalities"] == ["visual"]
    assert result["missing_verification_modalities"] == []
    assert result["verification_evidence"][0]["modalities"] == ["visual"]
    assert "visual_verification_not_observed" not in result["risks"]


def test_build_run_result_counts_read_only_visual_verification() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [{"kind": "answer", "description": "Visual analysis"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                "output": {
                    "roles": ["verification"],
                    "verification_strength": "standard",
                    "artifact_kind": "screenshot",
                    "path": "D:/workspace/preview.png",
                },
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["verification_successes"] == 1
    assert result["observed_verification_modalities"] == ["visual"]
    assert result["missing_verification_modalities"] == []


def test_build_run_result_counts_visual_artifact_deliverable_with_missing_behavior() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual", "behavioral"],
        "deliverables": [
            {
                "kind": "artifact",
                "description": "Preview screenshot and inspection result",
                "capability_id": "preview.visual_debug",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        contract_failed=True,
        tool_events=[
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                "declared_effects": ["artifact_write"],
                "declared_roles": ["verification"],
                "output": {
                    "roles": ["verification"],
                    "artifacts": ["screenshot", "visual_evidence"],
                    "artifact_kind": "screenshot",
                    "verification_strength": "standard",
                    "path": "D:/workspace/task-artifacts/run/preview/index.png",
                    "has_runtime_errors": False,
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["deliverable_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["artifacts"] == [
        {
            "kind": "screenshot",
            "path": "task-artifacts/run/preview/index.png",
            "tool": "preview.capture_local_html",
            "status": "success",
        }
    ]
    assert result["observed_verification_modalities"] == ["visual"]
    assert result["missing_verification_modalities"] == ["behavioral"]
    assert result["visual_verification"]["flags"]["visual_observed"] is True
    assert result["visual_verification"]["flags"]["visual_missing"] is False
    assert "target_deliverable_not_observed" not in result["risks"]
    assert "visual_verification_not_observed" not in result["risks"]
    assert "verification_modality_missing" in result["risks"]


def test_build_run_result_counts_page_preview_runtime_facts_as_structural() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual", "structural"],
        "deliverables": [
            {
                "kind": "artifact",
                "description": "Preview screenshot and inspection result",
                "capability_id": "preview.visual_debug",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        contract_failed=True,
        tool_events=[
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                "declared_effects": ["artifact_write"],
                "declared_roles": ["verification"],
                "output": {
                    "roles": ["verification"],
                    "artifacts": ["screenshot", "visual_evidence"],
                    "artifact_kind": "screenshot",
                    "verification_strength": "standard",
                    "path": "D:/workspace/task-artifacts/run/preview/index.png",
                    "status_code": 200,
                    "resource_responses": [
                        {"url": "http://127.0.0.1:5002/index.html", "status": 200},
                        {"url": "http://127.0.0.1:5002/css/base.css", "status": 200},
                    ],
                    "dom_snapshot": {"ready_state": "complete", "body_text_chars": 1200},
                    "has_runtime_errors": False,
                    "debug_session": {
                        "status": "success",
                        "service": {"kind": "browser_preview", "status_code": 200},
                    },
                },
            },
        ],
    )

    assert result["status"] == "success"
    assert result["counts"]["deliverable_successes"] == 1
    assert result["counts"]["verification_successes"] == 1
    assert result["observed_verification_modalities"] == ["visual", "structural"]
    assert result["missing_verification_modalities"] == []
    assert result["verification_evidence"][0]["modalities"] == ["visual", "structural"]
    assert "required_verification_not_satisfied" not in result["risks"]
    assert "verification_modality_missing" not in result["risks"]
    assert "execution_contract_failed" not in result["risks"]


def test_build_run_result_marks_read_only_visual_runtime_errors_partial() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [{"kind": "answer", "description": "Visual analysis"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        task_contract=contract,
        tool_events=[
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                "output": {
                    "roles": ["verification"],
                    "verification_strength": "standard",
                    "artifact_kind": "screenshot",
                    "path": "D:/workspace/preview.png",
                    "has_runtime_errors": True,
                    "console_errors": [{"type": "error", "text": "module failed"}],
                },
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["verification_successes"] == 1
    assert result["verification_evidence"][0]["strength"] == "none"
    assert result["verification_evidence"][0]["sufficient"] is False
    assert result["observed_verification_modalities"] == []
    assert result["missing_verification_modalities"] == ["visual"]
    assert "required_verification_not_satisfied" in result["risks"]
    assert "visual_verification_not_observed" in result["risks"]
    assert "verification_modality_missing" in result["risks"]


def test_build_run_result_marks_unverified_external_state_deliverable_partial() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {
                "kind": "external_state",
                "path_hint": "",
                "description": "Current Blender scene",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        requires_code_write=False,
        task_contract=contract,
        contract_failed=True,
        tool_events=[
            {
                "tool": "mcp_blender.execute_blender_code",
                "status": "success",
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            }
        ],
    )

    assert result["status"] == "partial"
    assert result["counts"]["deliverable_successes"] == 1
    assert result["counts"]["verification_successes"] == 0
    assert "deliverable_not_verified" in result["risks"]
    assert "target_deliverable_not_observed" not in result["risks"]


def test_build_run_result_does_not_treat_external_state_as_required_file_write() -> None:
    contract = {
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {
                "kind": "file",
                "path_hint": "D:/workspace/model.blend",
                "description": "Saved Blender model",
            }
        ],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        requires_code_write=True,
        task_contract=contract,
        contract_failed=True,
        tool_events=[
            {
                "tool": "mcp_blender.execute_blender_code",
                "status": "success",
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                },
            }
        ],
    )

    assert result["status"] == "failure"
    assert result["counts"]["deliverable_successes"] == 0
    assert "expected_write_not_observed" in result["risks"]


def test_build_run_result_fails_external_state_contract_without_deliverable() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Current scene"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        requires_code_write=False,
        task_contract=contract,
        tool_events=[],
    )

    assert result["status"] == "failure"
    assert "target_deliverable_not_observed" in result["risks"]


def test_build_run_result_does_not_count_script_file_as_external_state_deliverable() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Blender scene"}],
    }
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary={"files": [{"path": "build_scene.py"}]},
        requires_code_write=False,
        task_contract=contract,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/build_scene.py"},
                "output": {"path": "D:/workspace/build_scene.py"},
            },
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "python -m py_compile build_scene.py"},
                "output": {"exit_code": 0},
            },
        ],
    )

    assert result["status"] == "failure"
    assert result["counts"]["deliverable_successes"] == 0
    assert "target_deliverable_not_observed" in result["risks"]


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


def test_build_run_result_marks_no_progress_budget_without_progress_as_stopped() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary=None,
        no_progress_budget_exhausted=True,
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
    assert result["flags"]["no_progress_budget_exhausted"] is True
    assert "repeated_tool_failure" in result["risks"]
    assert "invalid_tool_call_protocol" in result["risks"]


def test_build_run_result_marks_no_progress_budget_after_write_as_partial() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="coding",
        change_summary=None,
        no_progress_budget_exhausted=True,
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/app.js"},
                "output": {"path": "D:/workspace/src/app.js"},
            },
            {
                "tool": "shell.run_command",
                "status": "failure",
                "input": {"command": "npm run dev"},
                "error": "command timed out",
            },
        ],
    )

    assert result["status"] == "partial"
    assert result["flags"]["no_progress_budget_exhausted"] is True
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


def test_build_run_result_surfaces_runtime_advisory_risks() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        mode="terminal",
        change_summary=None,
        tool_events=[
            {
                "tool": "shell.run_command",
                "status": "success",
                "input": {"command": "python -m http.server"},
                "output": {"exit_code": 0, "stdout": "", "stderr": ""},
                "runtime_risks": [
                    {
                        "code": "verification_runtime_advisory",
                        "blocking": False,
                    }
                ],
            }
        ],
    )

    assert "verification_runtime_advisory" in result["risks"]


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


def test_build_run_result_records_capability_preflight_advisory() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        tool_events=[],
        change_summary=None,
        mode="terminal",
        task_contract={
            "requires_state_change": True,
            "requires_write": False,
            "deliverables": [{"kind": "external_state"}],
        },
        contract_failed=True,
        preflight_advisories=[{
            "code": "missing_external_state_capability",
            "message": "No external-state capability is available.",
        }],
    )

    assert result["status"] == "failure"
    assert result["failures"] == []
    assert result["capability_advisories"][0]["code"] == "missing_external_state_capability"
    assert "capability_preflight_advisory" in result["risks"]
    assert result["failure_details"][0]["impact"] == "advisory"
    assert result["failure_details"][0]["tool"] == "capability.preflight"


def test_build_run_result_includes_capability_evidence_summary() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        tool_events=[
            {
                "tool": "mcp_blender.execute_blender_code",
                "status": "success",
                "declared_capability": "mcp.blender",
                "declared_effects": ["external_state_change"],
                "declared_roles": ["deliverable"],
                "output": {
                    "effects": ["external_state_change"],
                    "roles": ["deliverable"],
                    "artifacts": ["external_state"],
                },
            },
        ],
        change_summary=None,
        mode="terminal",
        task_contract={
            "requires_state_change": True,
            "capability_ids": ["mcp.blender"],
            "deliverables": [{"kind": "external_state", "capability_id": "mcp.blender"}],
        },
    )

    evidence = result["capability_evidence"]
    assert evidence["schema_version"] == "capability_evidence_summary.v1"
    assert evidence["requested_capability_ids"] == ["mcp.blender"]
    assert evidence["observed_capability_ids"] == ["mcp.blender"]
    assert evidence["observed_effects"] == ["external_state_change"]
    assert evidence["artifacts"] == ["external_state"]


def test_build_run_result_treats_copy_file_as_file_deliverable() -> None:
    result = build_run_result(
        workspace_path="D:/workspace/course",
        tool_events=[
            {
                "tool": "filesystem.copy_file",
                "status": "success",
                "input": {
                    "source_path": "D:/workspace/course/other/standing.glb",
                    "destination_path": "D:/workspace/course/assets/standing.glb",
                },
                "output": {
                    "type": "file_copy",
                    "source_path": "D:/workspace/course/other/standing.glb",
                    "path": "D:/workspace/course/assets/standing.glb",
                    "paths": ["D:/workspace/course/assets/standing.glb"],
                    "integrity": {"checked": True, "valid": True},
                    "roles": ["deliverable", "verification"],
                    "effects": ["file_write", "local_state_change"],
                    "artifacts": ["file"],
                    "verification_strength": "standard",
                },
            },
        ],
        change_summary=None,
        mode="terminal",
        task_contract={
            "intent": "write_required",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "deliverables": [
                {
                    "kind": "file",
                    "path_hint": "D:/workspace/course/assets/standing.glb",
                    "path_policy": "hint",
                }
            ],
        },
    )

    assert result["status"] == "success"
    assert result["written_paths"] == ["assets/standing.glb"]
    assert result["target_written_paths"] == ["assets/standing.glb"]
    assert result["artifacts"][0]["path"] == "assets/standing.glb"
    assert result["counts"]["verification_successes"] == 1


def test_build_run_result_fails_when_requested_capability_has_no_tool_evidence() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        tool_events=[],
        change_summary=None,
        mode="terminal",
        task_contract={
            "intent": "read_only_analysis",
            "requires_write": False,
            "requires_state_change": False,
            "capability_ids": ["code.local_project"],
            "deliverables": [{"kind": "answer"}],
            "first_action": "read",
        },
    )

    assert result["status"] == "failure"
    assert result["capability_evidence"]["requested_capability_ids"] == ["code.local_project"]
    assert result["capability_evidence"]["unobserved_requested_capability_ids"] == ["code.local_project"]
    assert result["failures"] == [
        {
            "tool": "capability.evidence",
            "path": "",
            "error": "requested capability not observed: code.local_project",
        }
    ]
    assert result["failure_details"] == [
        {
            "tool": "capability.evidence",
            "path": "",
            "role": "capability",
            "impact": "blocking",
        }
    ]
    assert result["counts"]["blocking_failures"] == 1
    assert result["flags"]["requested_capability_not_observed"] is True
    assert "requested_capability_not_observed" in result["risks"]


def test_build_run_result_marks_unverified_optional_write_partial() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        tool_events=[
            {
                "tool": "code.edit_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/editor.js"},
                "output": {"path": "D:/workspace/src/editor.js"},
            },
        ],
        change_summary={"files": [{"path": "src/editor.js"}]},
        mode="terminal",
        requires_code_write=False,
        task_contract={
            "intent": "read_only_analysis",
            "requires_write": False,
            "requires_state_change": False,
            "deliverables": [{"kind": "answer"}],
        },
    )

    assert result["status"] == "partial"
    assert result["counts"]["file_write_successes"] == 1
    assert result["counts"]["deliverable_successes"] == 0
    assert result["written_paths"] == ["src/editor.js"]
    assert result["observed_written_paths"] == ["src/editor.js"]
    assert result["target_written_paths"] == []
    assert result["flags"]["optional_state_change_observed"] is True
    assert result["flags"]["unverified_optional_write"] is True
    assert "optional_write_not_verified" in result["risks"]


def test_build_run_result_does_not_warn_when_optional_write_is_verified() -> None:
    result = build_run_result(
        workspace_path="D:/workspace",
        tool_events=[
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/editor.js"},
                "output": {"path": "D:/workspace/src/editor.js"},
            },
            {
                "tool": "filesystem.read_file",
                "status": "success",
                "input": {"path": "D:/workspace/src/editor.js"},
                "output": {"path": "D:/workspace/src/editor.js"},
            },
        ],
        change_summary={"files": [{"path": "src/editor.js"}]},
        mode="terminal",
        requires_code_write=False,
    )

    assert result["status"] == "success"
    assert result["flags"]["optional_state_change_observed"] is True
    assert result["flags"]["unverified_optional_write"] is False
    assert result["counts"]["verification_successes"] == 1
    assert "optional_write_not_verified" not in result["risks"]
