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


def test_normalize_mcp_tool_result_extracts_visual_artifact_from_text_path() -> None:
    output = normalize_mcp_tool_result({
        "content": [
            {
                "type": "text",
                "text": r'Render saved to "D:\code\YuntaoCode\task-artifacts\scene.png"',
            }
        ]
    })

    assert output["path"] == r"D:\code\YuntaoCode\task-artifacts\scene.png"
    assert output["artifact_kind"] == "image"
    assert output["format"] == "png"
    assert output["artifacts"] == ["image"]


def test_normalize_mcp_tool_result_extracts_visual_artifact_from_structured_content() -> None:
    output = normalize_mcp_tool_result({
        "content": [{"type": "text", "text": "done"}],
        "structuredContent": {
            "result": {
                "output_path": "/tmp/yuntaocode/viewport.pdf",
            }
        },
    })

    assert output["path"] == "/tmp/yuntaocode/viewport.pdf"
    assert output["artifact_kind"] == "pdf"
    assert output["format"] == "pdf"
    assert output["artifacts"] == ["pdf"]
