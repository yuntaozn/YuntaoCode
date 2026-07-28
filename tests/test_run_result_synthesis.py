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
            "run_artifacts": [
                {
                    "role": "final",
                    "artifact_kind": "html",
                    "path": "viewer.html",
                    "source_tool": "filesystem.write_file",
                    "status": "success",
                    "can_enter_model_context": True,
                    "verification_relevance": "deliverable",
                }
            ],
            "artifact_summary": {
                "schema_version": "run_artifact_summary.v1",
                "kind": "run_artifact_summary",
                "count": 1,
                "by_role": {"final": 1},
                "final_paths": ["viewer.html"],
                "flags": {"has_final_artifacts": True},
            },
            "verification_closure": {
                "schema_version": "verification_closure.v1",
                "kind": "verification_closure",
                "boundary": "evidence_only",
                "result_status": "partial",
                "modalities": {"required": ["visual"], "observed": [], "missing": ["visual"]},
                "flags": {"has_required_gap": True},
                "gap_facts": ["missing_modality:visual"],
            },
            "risks": ["test_not_observed"],
        },
        previous_answer="Done.",
        tool_events=[
            {"tool": "filesystem.write_file", "status": "success", "input": {"path": "viewer.html"}}
        ],
        task_route_evidence={
            "schema_version": "task_route_evidence.v1",
            "kind": "task_route_evidence",
            "boundary": "evidence_only",
            "strategy_owner": "model",
            "safety_owner": "runtime",
            "proposal_count": 1,
            "valid_proposal_count": 1,
            "target_capability_ids": ["code.text_write"],
            "flags": {"has_model_route": True, "all_routes_valid": True},
            "model_facts": ["route_proposals=code.text_write/filesystem.write_file"],
        },
    )

    assert [item["role"] for item in messages] == ["system", "user"]
    assert "Write the final user-facing answer for this run from runtime facts" in messages[0]["content"]
    assert "Completion evidence pack" in messages[0]["content"]
    assert "viewer.html" in messages[0]["content"]
    assert "test_not_observed" in messages[0]["content"]
    assert "missing_modality:visual" in messages[0]["content"]
    assert "route_proposals=code.text_write/filesystem.write_file" in messages[0]["content"]
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
