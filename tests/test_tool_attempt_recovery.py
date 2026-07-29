from runtime.tool_attempt_recovery import (
    TOOL_ATTEMPT_RECOVERY_SCHEMA_VERSION,
    build_tool_attempt_recovery,
    format_tool_attempt_recovery_for_model,
    summarize_tool_attempt_recovery_for_decision,
)
from runtime.tool_call_protocol import build_tool_attempt_observation


def test_tool_attempt_recovery_groups_recoverable_and_hard_boundaries() -> None:
    missing_path = build_tool_attempt_observation(
        tool_id="filesystem.write_file",
        arguments={"content": "hello"},
        reason="invalid_tool_input",
        message="missing path",
        missing_fields=["path"],
    )
    service_down = build_tool_attempt_observation(
        tool_id="mcp_blender.execute_blender_code",
        arguments={"code": "create house"},
        reason="capability_service_unavailable",
        message="Blender MCP is disconnected",
    )
    recovery = build_tool_attempt_recovery([
        {
            "event": "tool",
            "tool": "filesystem.write_file",
            "status": "failure",
            "output": {"observation": missing_path},
            "tool_attempt_observation": missing_path,
        },
        {
            "event": "tool",
            "tool": "mcp_blender.execute_blender_code",
            "status": "failure",
            "output": {"observation": service_down},
            "tool_attempt_observation": service_down,
        },
    ])

    assert recovery["schema_version"] == TOOL_ATTEMPT_RECOVERY_SCHEMA_VERSION
    assert recovery["kind"] == "tool_attempt_recovery"
    assert recovery["boundary"] == "evidence_only"
    assert recovery["counts"]["attempts"] == 2
    assert recovery["counts"]["recoverable_by_model"] == 2
    assert recovery["counts"]["hard_runtime_boundary"] == 1
    assert recovery["reason_counts"] == {
        "capability_service_unavailable": 1,
        "invalid_tool_input": 1,
    }
    assert recovery["boundary_counts"] == {
        "capability_availability": 1,
        "tool_call_protocol": 1,
    }
    assert recovery["flags"]["has_recoverable_attempts"] is True
    assert recovery["flags"]["has_hard_runtime_boundary"] is True
    assert "missing_fields=path" in recovery["model_facts"]

    rendered = format_tool_attempt_recovery_for_model(recovery)
    assert "Tool attempt recovery evidence" in rendered
    assert "capability_service_unavailable" in rendered
    assert "hard_boundary=true" in rendered


def test_tool_attempt_recovery_detects_large_write_like_payload() -> None:
    observation = build_tool_attempt_observation(
        tool_id="filesystem.write_file",
        arguments={"path": "novel.md", "content": "x" * 16000},
        reason="truncated_tool_call",
        message="model output truncated",
    )
    recovery = build_tool_attempt_recovery([
        {
            "event": "tool",
            "tool": "filesystem.write_file",
            "status": "failure",
            "output": {"observation": observation},
            "tool_attempt_observation": observation,
        }
    ])

    assert recovery["counts"]["large_write_like_payload"] == 1
    assert recovery["flags"]["has_large_write_like_payload"] is True
    assert "large_write_like_payload_attempts=1" in recovery["model_facts"]
    assert recovery["attempts"][0]["input_summary"]["content_chars"] == 16000


def test_tool_attempt_recovery_decision_summary_is_compact() -> None:
    observation = build_tool_attempt_observation(
        tool_id="filesystem.write_file",
        arguments={"content": "hello"},
        reason="invalid_tool_input",
        message="missing path",
        missing_fields=["path"],
    )
    recovery = build_tool_attempt_recovery([
        {
            "event": "tool",
            "tool": "filesystem.write_file",
            "status": "failure",
            "output": {"observation": observation},
            "tool_attempt_observation": observation,
        }
    ])
    summary = summarize_tool_attempt_recovery_for_decision(recovery)

    assert summary["schema_version"] == TOOL_ATTEMPT_RECOVERY_SCHEMA_VERSION
    assert summary["attempts"] == 1
    assert summary["recoverable_by_model"] == 1
    assert summary["reason_counts"] == {"invalid_tool_input": 1}
    assert summary["has_recoverable_attempts"] is True
