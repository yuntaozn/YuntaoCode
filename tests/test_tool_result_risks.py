from runtime.agent_strategy.tool_result_risks import (
    assess_tool_result_risks,
    attach_tool_result_risks,
)
from runtime.api.conversations import ConversationMessagesStreamHandler

import pytest


def test_uniform_pixels_are_nonblocking_facts_not_a_task_failure():
    risks = assess_tool_result_risks("mcp_demo.capture", "success", {
        "inline_images": [{"content_index": 0, "uniform_pixels": True, "pixel_ranges": [[0, 0]] * 3}],
    })
    assert risks[0]["code"] == "visual_pixels_uniform"
    assert risks[0]["blocking"] is False
    assert risks[0]["pixel_ranges"] == [[0, 0]] * 3


def test_external_failure_does_not_imply_rollback():
    risks = assess_tool_result_risks("mcp_demo.execute_code", "failure", {}, error="failed after first mutation")
    assert risks[0]["side_effects"] == "unknown"
    assert risks[0]["rollback_observed"] is False
    assert "partial changes may remain" in risks[0]["message"]


def test_invalid_integrity_becomes_non_blocking_model_facing_risk() -> None:
    risks = assess_tool_result_risks(
        "filesystem.read_file",
        "success",
        {
            "path": "viewer.html",
            "integrity": {
                "checked": True,
                "valid": False,
                "issues": ["html appears escaped as text"],
            },
        },
    )

    assert risks == [
        {
            "code": "artifact_integrity_invalid",
            "severity": "warning",
            "source": "filesystem.read_file",
            "path": "viewer.html",
            "issues": ["html appears escaped as text"],
            "blocking": False,
            "message": "Artifact integrity check reported issues.",
        }
    ]


def test_valid_integrity_does_not_add_risk() -> None:
    payload = attach_tool_result_risks({
        "tool": "filesystem.read_file",
        "status": "success",
        "output": {"integrity": {"checked": True, "valid": True, "issues": []}},
    })

    assert "runtime_risks" not in payload


def test_legacy_runtime_advisory_does_not_become_model_facing_risk() -> None:
    payload = attach_tool_result_risks({
        "tool": "shell.run_command",
        "status": "success",
        "output": {"exit_code": 0, "stdout": "ok", "stderr": ""},
        "runtime_advisories": [
            {
                "reason": "verification_runtime_advisory",
                "message": "long-running service is weak verification",
                "blocking": False,
            }
        ],
    })

    assert "runtime_risks" not in payload
    assert "runtime_advisories" not in payload


def test_shell_success_with_exception_stderr_becomes_degraded_evidence_risk() -> None:
    risks = assess_tool_result_risks(
        "shell.run_command",
        "success",
        {
            "exit_code": 0,
            "stdout": "",
            "stderr": "HttpListenerException: 参数错误。",
        },
    )

    assert risks[0]["code"] == "shell_stderr_warning"
    assert risks[0]["blocking"] is False
    assert "HttpListenerException" in risks[0]["detail"]


def test_shell_failure_with_diagnostic_becomes_model_facing_risk() -> None:
    risks = assess_tool_result_risks(
        "shell.run_command",
        "failure",
        {
            "exit_code": 1,
            "diagnostics": [
                {
                    "code": "node_check_inline_script",
                    "message": "Node -c/--check expects a JavaScript file path.",
                    "suggested_calls": [{"command": "node", "args": ["--check", "app.js"]}],
                }
            ],
        },
        error="command exited with code 1",
    )

    assert risks[0]["code"] == "shell_node_check_inline_script"


def test_encoding_warning_becomes_non_blocking_model_facing_risk() -> None:
    risks = assess_tool_result_risks(
        "filesystem.write_file",
        "success",
        {
            "path": "viewer.html",
            "encoding": "utf-8",
            "encoding_risks": [
                {
                    "code": "html_charset_missing",
                    "message": "HTML 包含非 ASCII 文本但前部未声明 charset。",
                }
            ],
        },
    )

    assert risks[0]["code"] == "text_encoding_risk"
    assert risks[0]["risk_code"] == "html_charset_missing"
    assert risks[0]["blocking"] is False


def test_failed_external_capability_tool_becomes_model_facing_risk() -> None:
    risks = assess_tool_result_risks(
        "mcp_blender.get_viewport_screenshot",
        "failure",
        {"message": "MCP tool call failed: Unknown command type: get_viewport_screenshot"},
    )

    assert risks[0]["code"] == "external_capability_tool_unsupported"
    assert risks[0]["source"] == "mcp_blender.get_viewport_screenshot"
    assert risks[0]["blocking"] is False
    assert "Unknown command type" in risks[0]["detail"]


def test_failed_builtin_tool_does_not_gain_external_capability_risk() -> None:
    risks = assess_tool_result_risks(
        "filesystem.read_file",
        "failure",
        {"message": "file not found"},
    )

    assert risks == []


def test_compact_read_payload_keeps_integrity_and_runtime_risks() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    payload = attach_tool_result_risks({
        "tool": "filesystem.read_file",
        "status": "success",
        "output": {
            "path": "viewer.html",
            "content": "1| &lt;html&gt;",
            "raw_content": "&lt;html&gt;",
            "encoding_risks": [
                {
                    "code": "html_charset_missing",
                    "message": "HTML 包含非 ASCII 文本但前部未声明 charset。",
                }
            ],
            "integrity": {
                "checked": True,
                "valid": False,
                "issues": ["html appears escaped as text"],
            },
        },
    })

    compact = handler._summarize_tool_payload(payload)

    assert compact["output"]["integrity"]["valid"] is False
    assert compact["output"]["encoding_risks"][0]["code"] == "html_charset_missing"
    risk_codes = {risk["code"] for risk in compact["runtime_risks"]}
    assert "artifact_integrity_invalid" in risk_codes
    assert "text_encoding_risk" in risk_codes


def test_compact_tool_message_keeps_risk_before_large_output_truncation() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    payload = attach_tool_result_risks({
        "tool": "filesystem.read_file",
        "status": "success",
        "output": {
            "path": "viewer.html",
            "content": "x" * 60000,
            "raw_content": "x" * 60000,
            "integrity": {
                "checked": True,
                "valid": False,
                "issues": ["html appears escaped as text"],
            },
        },
    })

    compact_message = handler._compact_tool_payload(payload)

    assert "artifact_integrity_invalid" in compact_message
    assert "html appears escaped as text" in compact_message
    assert "suggested_tools" not in compact_message


@pytest.mark.parametrize("tool,status,output", [
    ("mcp_demo.execute", "failure", {"message": "Unknown command"}),
    ("shell.run_command", "failure", {"diagnostics": [{"code": "failed", "message": "bad input", "suggested_calls": [{"command": "alternate"}]}]}),
    ("shell.run_command", "success", {"exit_code": 0, "stderr": "Error: partial result"}),
    ("filesystem.read_file", "success", {"integrity": {"checked": True, "valid": False, "issues": ["escaped HTML"]}}),
    ("filesystem.write_file", "success", {"encoding_risks": [{"code": "charset_missing", "message": "Missing charset"}]}),
    ("mcp_demo.capture", "success", {"inline_images": [{"uniform_pixels": True}]}),
])
def test_risk_projection_preserves_observation_without_runtime_action_or_tool_suggestions(tool, status, output):
    risks = assess_tool_result_risks(tool, status, output)
    assert risks
    for risk in risks:
        assert not {"action", "suggested_tools", "suggested_calls"} & risk.keys()
        assert risk["source"] == tool
        assert risk["blocking"] is False
