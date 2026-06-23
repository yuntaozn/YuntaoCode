from __future__ import annotations

from runtime.run_fact_summary import (
    build_run_fact_summary,
    build_tool_failure_fact_summary,
    format_run_fact_summary,
    format_tool_failure_fact_summary,
)


def test_run_fact_summary_packages_status_evidence_and_risks() -> None:
    summary = build_run_fact_summary(
        workspace_path=r"D:\demo",
        tool_events=[],
        run_result={
            "status": "partial",
            "changed_paths": ["viewer.html"],
            "written_paths": ["viewer.html"],
            "verification_evidence": [
                {
                    "tool": "node --check",
                    "path": "viewer.html",
                    "modalities": ["behavioral"],
                    "strength": "strong",
                    "sufficient": True,
                }
            ],
            "failures": [
                {
                    "tool": "filesystem.write_file",
                    "path": "viewer.html",
                    "error": "path is required",
                }
            ],
            "risks": ["partial_write_failure"],
            "counts": {
                "tool_events": 3,
                "write_successes": 1,
                "verification_successes": 1,
                "failures": 1,
            },
        },
        task_contract={"goal": "create viewer", "intent": "coding"},
    )

    assert summary["status"] == "partial"
    assert summary["goal"] == "create viewer"
    assert summary["written_paths"] == ["viewer.html"]
    assert summary["verification"][0]["tool"] == "node --check"
    assert summary["failures"][0]["error"] == "path is required"
    assert "partial_write_failure" in summary["risks"]

    rendered = format_run_fact_summary(summary)
    assert "Runtime fact package" in rendered
    assert "viewer.html" in rendered
    assert "path is required" in rendered
    assert "Do not claim completion" in rendered


def test_tool_failure_fact_summary_detects_repeated_route() -> None:
    events = [
        {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "big.html"},
            "output": {"reason": "truncated_tool_call"},
            "error": "incomplete arguments",
        },
        {
            "tool": "filesystem.write_file",
            "status": "failure",
            "input": {"path": "big.html"},
            "output": {"reason": "truncated_tool_call"},
            "error": "incomplete arguments",
        },
    ]
    summary = build_tool_failure_fact_summary(
        workspace_path=r"D:\demo",
        current_stage="editor",
        tool_events=events,
    )

    assert summary["repeated_route"]
    rendered = format_tool_failure_fact_summary(summary)
    assert "Runtime failure facts" in rendered
    assert "filesystem.write_file" in rendered
    assert "truncated_tool_call" in rendered
