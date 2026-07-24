from __future__ import annotations

from runtime.run_result_synthesis import (
    RESULT_SYNTHESIS_USER_CONTENT_LIMIT,
    build_result_synthesis_request_context,
    build_result_synthesis_messages,
)


def test_build_result_synthesis_messages_uses_runtime_facts_and_request_reference() -> None:
    user_content = (
        "START: must keep Chinese output and do not rename viewer.html.\n"
        + "a" * (RESULT_SYNTHESIS_USER_CONTENT_LIMIT + 25)
        + "\nEND: save the summary for D:\\demo\\viewer.html"
    )
    messages = build_result_synthesis_messages(
        workspace_path="/tmp/demo",
        user_content=user_content,
        task_contract={"goal": "create viewer"},
        run_result={
            "status": "partial",
            "changed_paths": ["viewer.html"],
            "risks": ["test_not_observed"],
        },
        previous_answer="Done.",
    )

    assert [item["role"] for item in messages] == ["system", "user"]
    assert "Write the final user-facing answer for this run from runtime facts" in messages[0]["content"]
    assert "viewer.html" in messages[0]["content"]
    assert "test_not_observed" in messages[0]["content"]
    assert "Previous assistant draft" in messages[0]["content"]
    assert "User request reference for final answer synthesis" in messages[1]["content"]
    assert "START: must keep Chinese output" in messages[1]["content"]
    assert "END: save the summary" in messages[1]["content"]
    assert "omitted middle chars" in messages[1]["content"]
    assert "presentation_reference_only" in messages[1]["content"]


def test_request_reference_context_keeps_explicit_markers_and_references() -> None:
    context = build_result_synthesis_request_context(
        "请只分析，不要修改。\n"
        "目标文件：D:\\demo\\src\\app.js\n"
        "输出中文，格式用 Markdown。\n"
    )

    assert context["schema_version"] == "result_synthesis_request_context.v1"
    assert context["boundary"] == "presentation_reference_only"
    assert context["marker_lines"] == [
        "请只分析，不要修改。",
        "目标文件：D:\\demo\\src\\app.js",
        "输出中文，格式用 Markdown。",
    ]
    assert "D:\\demo\\src\\app.js" in context["references"]
