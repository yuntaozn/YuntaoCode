from runtime.mcp_protocol import normalize_mcp_tool_result


def test_normalize_mcp_tool_result_marks_text_execution_error() -> None:
    output = normalize_mcp_tool_result({
        "content": [
            {
                "type": "text",
                "text": "Error executing code: missing material",
            }
        ]
    })

    assert output["error"] is True
    assert output["message"] == "Error executing code: missing material"


def test_normalize_mcp_tool_result_marks_structured_failure() -> None:
    output = normalize_mcp_tool_result({
        "content": [{"type": "text", "text": "finished"}],
        "structuredContent": {"success": False, "message": "remote failed"},
    })

    assert output["error"] is True
    assert output["structured_content"]["success"] is False
