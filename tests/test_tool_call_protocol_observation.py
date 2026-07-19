from __future__ import annotations

from runtime.tool_call_protocol import (
    TOOL_ATTEMPT_OBSERVATION_SCHEMA_VERSION,
    build_tool_attempt_observation,
    format_tool_attempt_observation,
    tool_attempt_output,
)


def test_tool_attempt_observation_describes_missing_fields_as_recoverable() -> None:
    observation = build_tool_attempt_observation(
        tool_id="filesystem.write_file",
        arguments={"content": "hello"},
        reason="invalid_tool_input",
        message="missing required fields",
        raw_tool_name="filesystem__write_file",
        raw_arguments_text='{"content":"hello"}',
        missing_fields=["path"],
    )

    assert observation["schema_version"] == TOOL_ATTEMPT_OBSERVATION_SCHEMA_VERSION
    assert observation["kind"] == "tool_attempt_observation"
    assert observation["status"] == "not_executed"
    assert observation["boundary"] == "tool_call_protocol"
    assert observation["recoverable_by_model"] is True
    assert observation["missing_fields"] == ["path"]
    assert observation["input_summary"]["content_chars"] == 5
    assert "path" in " ".join(observation["model_decision"])

    output = tool_attempt_output(observation)
    assert output["reason"] == "invalid_tool_input"
    assert output["observation"]["schema_version"] == TOOL_ATTEMPT_OBSERVATION_SCHEMA_VERSION


def test_tool_attempt_observation_guides_large_write_to_incremental_route() -> None:
    observation = build_tool_attempt_observation(
        tool_id="filesystem.write_file",
        arguments={"path": "big.html", "content": "x" * 20000},
        reason="truncated_tool_call",
        message="model output limit",
    )

    rendered = format_tool_attempt_observation(observation)

    assert observation["input_summary"]["content_chars"] == 20000
    assert "Large write-like payload observed" in " ".join(observation["model_decision"])
    assert "content_chars=20000" in rendered
    assert "split the work" in rendered


def test_unknown_tool_observation_keeps_visible_tool_hints_bounded() -> None:
    observation = build_tool_attempt_observation(
        tool_id="code.search",
        arguments={},
        reason="unknown_tool",
        message="unknown tool: code.search",
        available_tool_ids=["code.search_text", "filesystem.scan_folder", "filesystem.read_file"],
    )

    assert observation["boundary"] == "tool_call_protocol"
    assert observation["available_tool_ids"] == [
        "code.search_text",
        "filesystem.scan_folder",
        "filesystem.read_file",
    ]
    assert "canonical tool ID" in " ".join(observation["model_decision"])
