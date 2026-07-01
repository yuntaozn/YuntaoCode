from runtime.debug_session import (
    DEBUG_SESSION_SCHEMA_VERSION,
    build_debug_session,
    debug_session_summary,
    normalize_debug_session,
)


def test_build_debug_session_records_process_streams_and_health() -> None:
    session = build_debug_session(
        source_type="shell.run_command",
        command="node --check app.js",
        executable="node",
        args=["--check", "app.js"],
        cwd="D:/workspace",
        pid=123,
        exit_code=1,
        stdout="",
        stderr="SyntaxError",
        timeout=30,
        diagnostics=[{"code": "syntax_error"}],
        duration_seconds=0.42,
    )

    assert session["schema_version"] == DEBUG_SESSION_SCHEMA_VERSION
    assert session["command"]["display"] == "node --check app.js"
    assert session["process"]["pid"] == 123
    assert session["streams"]["stderr_chars"] == len("SyntaxError")
    assert session["diagnostics"][0]["code"] == "syntax_error"
    assert session["health"]["status"] == "failed"
    assert session["health"]["has_runtime_errors"] is True


def test_normalize_debug_session_accepts_legacy_shell_output() -> None:
    summary = debug_session_summary(normalize_debug_session({
        "command": "pytest",
        "executable": "pytest",
        "args": ["tests"],
        "cwd": "D:/workspace",
        "exit_code": 0,
        "stdout": "passed",
        "stderr": "",
        "timed_out": False,
        "timeout": 60,
    }))

    assert summary is not None
    assert summary["kind"] == "debug_session"
    assert summary["command"] == "pytest"
    assert summary["exit_code"] == 0
    assert summary["timed_out"] is False
    assert summary["status"] == "success"
    assert summary["stdout_chars"] == len("passed")


def test_debug_session_summary_accepts_compact_summary() -> None:
    summary = debug_session_summary({
        "schema_version": "debug_session.v1",
        "kind": "debug_session",
        "source_type": "preview.capture_page",
        "command": "playwright capture http://127.0.0.1:1234/index.html",
        "executable": "playwright.chromium",
        "cwd": "D:/workspace",
        "pid": None,
        "exit_code": 0,
        "timed_out": False,
        "timeout": 20,
        "duration_seconds": 13.165,
        "stdout_chars": 36,
        "stderr_chars": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "service": {"kind": "browser_preview", "status_code": 200},
        "diagnostic_count": 0,
        "status": "success",
        "has_runtime_errors": False,
    })

    assert summary is not None
    assert summary["source_type"] == "preview.capture_page"
    assert summary["command"].startswith("playwright capture")
    assert summary["exit_code"] == 0
    assert summary["duration_seconds"] == 13.165
    assert summary["service"]["status_code"] == 200
    assert summary["status"] == "success"
