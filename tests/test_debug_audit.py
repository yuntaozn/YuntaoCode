from runtime.debug_audit import build_debug_audit


def test_debug_audit_summarizes_install_preview_timeout_and_process_facts() -> None:
    audit = build_debug_audit(
        debug_sessions=[
            {
                "schema_version": "debug_session.v1",
                "kind": "debug_session",
                "source_type": "shell.run_command",
                "command": "python -m pip install playwright",
                "executable": "python",
                "cwd": "D:/workspace",
                "exit_code": None,
                "timed_out": True,
                "timeout": 120,
                "duration_seconds": 120.4,
                "stdout_chars": 2048,
                "stderr_chars": 128,
                "stdout_truncated": True,
                "diagnostic_count": 1,
                "status": "timed_out",
                "has_runtime_errors": True,
            },
            {
                "schema_version": "debug_session.v1",
                "kind": "debug_session",
                "source_type": "preview.capture_page",
                "command": "playwright capture http://127.0.0.1:3000",
                "executable": "playwright.chromium",
                "cwd": "D:/workspace",
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 4.2,
                "stdout_chars": 32,
                "stderr_chars": 0,
                "service": {"kind": "browser_preview", "status_code": 200},
                "diagnostic_count": 0,
                "status": "success",
                "has_runtime_errors": False,
            },
            {
                "schema_version": "debug_session.v1",
                "kind": "debug_session",
                "source_type": "shell.run_command",
                "command": "netstat -ano | findstr :3000",
                "executable": "netstat",
                "cwd": "D:/workspace",
                "exit_code": 0,
                "timed_out": False,
                "duration_seconds": 0.2,
                "stdout_chars": 80,
                "stderr_chars": 0,
                "status": "success",
                "has_runtime_errors": False,
            },
        ],
        result_status="partial",
        risks=["model_provider_error"],
    )

    assert audit["schema_version"] == "debug_audit.v1"
    assert audit["boundary"] == "evidence_only"
    assert audit["counts"]["debug_sessions"] == 3
    assert audit["counts"]["dependency_install_sessions"] == 1
    assert audit["counts"]["preview_sessions"] == 1
    assert audit["counts"]["service_sessions"] == 1
    assert audit["counts"]["port_checks"] == 1
    assert audit["counts"]["timed_out_sessions"] == 1
    assert audit["counts"]["long_sessions"] == 1
    assert audit["counts"]["diagnostics"] == 1
    assert audit["counts"]["truncated_streams"] == 1
    assert audit["flags"]["has_dependency_install"] is True
    assert audit["flags"]["has_preview_service"] is True
    assert audit["flags"]["has_port_or_process_check"] is True
    assert audit["flags"]["has_timeout"] is True
    assert audit["flags"]["has_long_session"] is True
    assert audit["dependency_install_sessions"][0]["role"] == "dependency_install"
    assert audit["preview_sessions"][0]["role"] == "preview_service"
    assert audit["risk_codes"] == ["model_provider_error"]


def test_debug_audit_is_empty_when_no_debug_sessions_exist() -> None:
    audit = build_debug_audit()

    assert audit["schema_version"] == "debug_audit.v1"
    assert audit["counts"]["debug_sessions"] == 0
    assert audit["flags"]["has_debug_evidence"] is False


def test_debug_audit_accepts_legacy_compact_debug_records_without_kind() -> None:
    audit = build_debug_audit(
        debug_sessions=[
            {
                "schema_version": "debug_session.v1",
                "source_type": "shell.run_command",
                "command": "tasklist",
                "executable": "tasklist",
                "exit_code": 0,
                "stdout_chars": 128,
                "stderr_chars": 0,
                "status": "success",
            }
        ],
    )

    assert audit["counts"]["debug_sessions"] == 1
    assert audit["counts"]["process_checks"] == 1
    assert audit["records"][0]["kind"] == "debug_session"
    assert audit["records"][0]["role"] == "process_check"
