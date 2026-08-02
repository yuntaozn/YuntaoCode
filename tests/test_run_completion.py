from runtime.run_completion import (
    COMPLETION_EVIDENCE_BUDGET,
    build_completion_decision,
    build_completion_evidence_pack,
    extract_completion_self_assessment,
    format_completion_evidence_pack,
)
from runtime.tool_call_protocol import build_tool_attempt_observation


def test_completion_evidence_pack_collects_audits_progress_and_decisions() -> None:
    tool_attempt = build_tool_attempt_observation(
        tool_id="filesystem.write_file",
        arguments={"content": "hello"},
        reason="invalid_tool_input",
        message="missing path",
        missing_fields=["path"],
    )
    pack = build_completion_evidence_pack(
        workspace_path="D:/demo",
        task_contract={"goal": "create and verify an HTML viewer", "intent": "write_required"},
        run_result={
            "status": "partial",
            "target_written_paths": ["viewer/index.html"],
            "run_artifacts": [
                {
                    "role": "final",
                    "artifact_kind": "html",
                    "path": "viewer/index.html",
                    "source_tool": "filesystem.write_file",
                    "status": "success",
                    "can_enter_model_context": True,
                    "verification_relevance": "verification",
                },
                {
                    "role": "screenshot",
                    "artifact_kind": "screenshot",
                    "path": "viewer/preview.png",
                    "source_tool": "preview.capture_file",
                    "status": "success",
                    "can_enter_model_context": True,
                    "verification_relevance": "diagnostic",
                },
            ],
            "artifact_summary": {
                "schema_version": "run_artifact_summary.v1",
                "kind": "run_artifact_summary",
                "count": 2,
                "by_role": {"final": 1, "screenshot": 1},
                "by_artifact_kind": {"html": 1, "screenshot": 1},
                "by_verification_relevance": {"verification": 1, "diagnostic": 1},
                "previewable_count": 2,
                "model_context_eligible_count": 2,
                "verification_relevant_count": 2,
                "changed_paths": ["viewer/index.html"],
                "final_paths": ["viewer/index.html"],
                "visual_paths": ["viewer/preview.png"],
                "preview_paths": ["viewer/index.html", "viewer/preview.png"],
                "model_context_paths": ["viewer/preview.png"],
                "verification_paths": ["viewer/index.html"],
                "diagnostic_paths": ["viewer/preview.png"],
                "path_index": [
                    {
                        "path": "viewer/index.html",
                        "roles": ["final"],
                        "artifact_kinds": ["html"],
                        "source_tools": ["filesystem.write_file"],
                        "verification_relevance": ["verification"],
                        "can_preview": True,
                        "can_enter_model_context": True,
                    },
                    {
                        "path": "viewer/preview.png",
                        "roles": ["screenshot"],
                        "artifact_kinds": ["screenshot"],
                        "source_tools": ["preview.capture_file"],
                        "verification_relevance": ["diagnostic"],
                        "can_preview": True,
                        "can_enter_model_context": True,
                    },
                ],
                "flags": {
                    "has_artifacts": True,
                    "has_final_artifacts": True,
                    "has_visual_artifacts": True,
                    "has_previewable_artifacts": True,
                    "has_model_context_artifacts": True,
                    "has_verification_evidence": True,
                },
            },
            "verification_evidence": [
                {
                    "tool": "preview.capture_file",
                    "path": "viewer/index.html",
                    "strength": "standard",
                    "sufficient": True,
                    "modalities": ["visual", "runtime"],
                }
            ],
            "verification_closure": {
                "schema_version": "verification_closure.v1",
                "kind": "verification_closure",
                "boundary": "evidence_only",
                "result_status": "partial",
                "required_strength": "standard",
                "modalities": {
                    "required": ["visual", "runtime", "behavioral"],
                    "observed": ["visual", "runtime"],
                    "missing": ["behavioral"],
                },
                "counts": {
                    "verification_records": 1,
                    "sufficient_verification_records": 1,
                    "fresh_verification_records": 1,
                    "stale_verification_records": 0,
                    "final_artifacts": 1,
                    "visual_artifacts": 1,
                    "gap_facts": 1,
                },
                "flags": {
                    "has_required_gap": True,
                    "has_verification_evidence": True,
                    "has_sufficient_verification": True,
                    "has_final_artifact": True,
                    "has_visual_evidence": True,
                    "visual_entered_model_context": True,
                    "has_gap_risks": True,
                    "verification_after_latest_change_observed": True,
                },
                "source_kinds": ["verification_evidence", "final_artifact", "visual_evidence"],
                "gap_facts": ["missing_modality:behavioral"],
                "risk_codes": ["test_not_observed"],
                "gap_risks": ["test_not_observed"],
                "artifact_paths": {
                    "final": ["viewer/index.html"],
                    "visual": ["viewer/preview.png"],
                    "model_context": ["viewer/preview.png"],
                },
                "freshness": {
                    "kind": "verification_freshness",
                    "boundary": "evidence_only",
                    "latest_change_event_index": 1,
                    "counts": {"observed": 1, "fresh": 1, "stale": 0, "unknown": 0},
                    "flags": {
                        "has_latest_change": True,
                        "has_fresh_verification": True,
                        "has_stale_verification": False,
                        "verification_after_latest_change_observed": True,
                        "verification_freshness_unknown": False,
                    },
                    "paths": {"fresh": ["viewer/preview.png"], "stale": [], "unknown": []},
                    "facts": [
                        "verification_freshness=latest_change:1; fresh:1; stale:0; unknown:0",
                        "verification_after_latest_change_observed",
                    ],
                },
                "model_facts": [
                    "result_status=partial",
                    "modalities=required:visual, runtime, behavioral; observed:visual, runtime; missing:behavioral",
                ],
            },
            "visual_verification": {
                "schema_version": "visual_verification.v1",
                "kind": "visual_verification",
                "boundary": "evidence_only",
                "counts": {"visual_evidence": 1, "runtime_error_records": 1},
                "flags": {"has_visual_evidence": True, "has_runtime_errors": True},
            },
            "debug_audit": {
                "schema_version": "debug_audit.v1",
                "kind": "debug_audit",
                "boundary": "evidence_only",
                "counts": {"debug_sessions": 1, "preview_sessions": 1},
                "flags": {"has_preview_service": True},
            },
            "capability_evidence": {
                "schema_version": "capability_evidence_summary.v1",
                "requested_capability_ids": ["code.text_write"],
                "observed_capability_ids": ["code.text_write", "preview.visual_debug"],
                "unobserved_requested_capability_ids": [],
            },
            "risks": ["test_not_observed"],
            "counts": {"deliverable_successes": 1, "verification_successes": 1, "failures": 0},
        },
        tool_events=[
            {
                "tool": "shell.run_command",
                "status": "running",
                "progress": {
                    "tool_task": {
                        "kind": "tool_task_progress",
                        "task_id": "task-1",
                        "tool": "shell.run_command",
                        "status": "running",
                        "elapsed_seconds": 120,
                        "stale_seconds": 60,
                        "can_cancel": True,
                        "command": {"role": "dependency_install"},
                        "flags": {"has_heartbeat": True, "has_live_output": True},
                        "last_log": {
                            "level": "info",
                            "kind": "command_heartbeat",
                            "message": "command still running",
                        },
                        "last_heartbeat": {"silent_seconds": 60, "elapsed_seconds": 120},
                    }
                },
            },
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {"content": "hello"},
                "error": "missing path",
                "output": {
                    "type": "tool_attempt_observation",
                    "reason": "invalid_tool_input",
                    "message": "missing path",
                    "observation": tool_attempt,
                },
                "tool_attempt_observation": tool_attempt,
            }
        ],
        completion_decisions=[
            {"review_count": 1, "action": "continue_with_tools", "tool_call_count": 1}
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
            "preflight_target_capability_ids": ["code.text_write"],
            "advisory_codes": [],
            "flags": {
                "has_model_route": True,
                "all_routes_valid": True,
                "has_route_advisories": False,
            },
            "model_facts": [
                "route_proposals=code.text_write/filesystem.write_file",
                "route_validation=valid:1; invalid:0",
            ],
        },
    )
    text = format_completion_evidence_pack(pack)

    assert pack["schema_version"] == "completion_evidence_pack.v1"
    assert pack["boundary"] == "evidence_only"
    assert pack["tool_progress"][0]["role"] == "dependency_install"
    assert pack["tool_attempts"][0]["missing_fields"] == ["path"]
    assert pack["tool_attempt_recovery"]["counts"]["attempts"] == 1
    assert pack["tool_attempt_recovery"]["counts"]["recoverable_by_model"] == 1
    assert pack["tool_attempt_recovery"]["reason_counts"] == {"invalid_tool_input": 1}
    assert "missing_fields=path" in pack["tool_attempt_recovery"]["model_facts"]
    assert pack["artifact_summary"]["by_role"] == {"final": 1, "screenshot": 1}
    assert pack["artifact_summary"]["by_verification_relevance"] == {"diagnostic": 1, "verification": 1}
    assert pack["artifact_summary"]["preview_paths"] == ["viewer/index.html", "viewer/preview.png"]
    assert pack["artifact_summary"]["verification_paths"] == ["viewer/index.html"]
    assert pack["artifact_summary"]["model_context_paths"] == ["viewer/preview.png"]
    assert pack["artifact_summary"]["path_index"][0]["path"] == "viewer/index.html"
    assert pack["artifact_summary"]["path_index"][0]["can_preview"] is True
    assert pack["run_artifacts"][0]["role"] == "final"
    assert pack["verification_closure"]["modalities"]["missing"] == ["behavioral"]
    assert pack["verification_closure"]["gap_facts"] == ["missing_modality:behavioral"]
    assert pack["verification_closure"]["freshness"]["counts"]["fresh"] == 1
    assert pack["visual_verification"]["flags"]["has_runtime_errors"] is True
    assert pack["debug_audit"]["flags"]["has_preview_service"] is True
    assert pack["task_route_evidence"]["strategy_owner"] == "model"
    assert pack["task_route_evidence"]["valid_proposal_count"] == 1
    assert pack["previous_completion_decisions"][0]["action"] == "continue_with_tools"
    assert "Completion evidence pack" in text
    assert "artifact summary" in text
    assert "final artifact paths" in text
    assert "previewable artifact paths" in text
    assert "model-context artifact paths" in text
    assert "artifact path index" in text
    assert "run artifacts" in text
    assert "Verification closure facts" in text
    assert "verification closure" in text
    assert "verification freshness facts" in text
    assert "missing_modality:behavioral" in text
    assert "viewer/index.html" in text
    assert "viewer/preview.png" in text
    assert "recent tool progress" in text
    assert "recent unexecuted tool attempts" in text
    assert "Tool attempt recovery evidence" in text
    assert "missing_fields=path" in text
    assert "dependency_install" in text
    assert "invalid_tool_input" in text
    assert "task route evidence" in text
    assert "route_proposals=code.text_write/filesystem.write_file" in text


def test_completion_evidence_pack_applies_presentation_budget() -> None:
    pack = build_completion_evidence_pack(
        workspace_path="D:/demo",
        task_contract={
            "goal": "create a long HTML article and verify it visually",
            "intent": "write_required",
        },
        run_result={
            "status": "partial",
            "target_written_paths": [f"chapter-{index}.html" for index in range(40)],
            "run_artifacts": [
                {
                    "role": "final" if index == 0 else "draft",
                    "artifact_kind": "html",
                    "path": f"chapter-{index}.html",
                    "source_tool": "filesystem.append_text",
                    "status": "success",
                    "can_enter_model_context": index < 3,
                    "verification_relevance": "verification" if index == 0 else "context",
                }
                for index in range(40)
            ],
            "artifact_summary": {
                "schema_version": "run_artifact_summary.v1",
                "kind": "run_artifact_summary",
                "count": 40,
                "by_role": {"final": 1, "draft": 39},
                "final_paths": ["chapter-0.html"],
                "visual_paths": [f"preview-{index}.png" for index in range(40)],
                "preview_paths": [f"chapter-{index}.html" for index in range(40)],
                "model_context_paths": [f"context-{index}.png" for index in range(40)],
                "path_index": [
                    {
                        "path": f"chapter-{index}.html",
                        "roles": ["final" if index == 0 else "draft"],
                        "artifact_kinds": ["html"],
                        "source_tools": ["filesystem.append_text"],
                        "verification_relevance": ["verification" if index == 0 else "context"],
                        "can_preview": True,
                        "can_enter_model_context": index < 3,
                    }
                    for index in range(40)
                ],
                "flags": {
                    "has_final_artifacts": True,
                    "has_visual_artifacts": True,
                    "has_model_context_artifacts": True,
                },
            },
            "verification_closure": {
                "schema_version": "verification_closure.v1",
                "kind": "verification_closure",
                "boundary": "evidence_only",
                "result_status": "partial",
                "required_strength": "standard",
                "modalities": {
                    "required": ["visual"],
                    "observed": [],
                    "missing": ["visual"],
                },
                "flags": {"has_required_gap": True},
                "gap_facts": ["missing_modality:visual:0"],
                "gap_risks": ["visual_verification_not_observed"],
            },
            "failures": [
                {"tool": "preview.capture_file", "error": "screenshot failed"}
                for _ in range(40)
            ],
            "failure_details": [
                {
                    "tool": "preview.capture_file",
                    "impact": "verification_unobserved",
                    "error": "screenshot failed",
                }
                for _ in range(40)
            ],
            "risks": [f"risk-{index}" for index in range(40)],
        },
    )

    assert pack["budget"]["run_artifacts"] == COMPLETION_EVIDENCE_BUDGET["run_artifacts"]
    assert len(pack["run_artifacts"]) == COMPLETION_EVIDENCE_BUDGET["run_artifacts"]
    assert (
        len(pack["artifact_summary"]["visual_paths"])
        == COMPLETION_EVIDENCE_BUDGET["artifact_summary_paths"]
    )
    assert (
        len(pack["artifact_summary"]["model_context_paths"])
        == COMPLETION_EVIDENCE_BUDGET["artifact_summary_paths"]
    )
    assert (
        len(pack["artifact_summary"]["path_index"])
        == COMPLETION_EVIDENCE_BUDGET["artifact_summary_paths"]
    )
    assert len(pack["failures"]) == COMPLETION_EVIDENCE_BUDGET["failure_records"]
    assert len(pack["risks"]) == COMPLETION_EVIDENCE_BUDGET["risks"]
    assert pack["artifact_summary"]["final_paths"] == ["chapter-0.html"]
    assert pack["verification_closure"]["gap_facts"] == ["missing_modality:visual:0"]

    pack["budget"] = {**pack["budget"], "formatted_prompt_chars": 3000}
    text = format_completion_evidence_pack(pack)

    assert len(text) <= 3000
    assert "Completion evidence pack" in text
    assert "evidence pack truncated by presentation budget" in text


def test_completion_decision_records_continue_with_tools_without_forcing_strategy() -> None:
    decision = build_completion_decision(
        review_count=1,
        run_result={"status": "success", "risks": []},
        tool_calls=[{"name": "filesystem.read_text_preview"}],
        content="",
        finish_reason="tool_calls",
    )

    assert decision["schema_version"] == "completion_decision.v1"
    assert decision["source"] == "model_observed_behavior"
    assert decision["action"] == "continue_with_tools"
    assert decision["tool_call_count"] == 1
    assert decision["result_status"] == "success"
    assert decision["evidence_pack"] == {}


def test_completion_decision_records_final_answer_candidate() -> None:
    content = "I completed the file but did not run tests."
    decision = build_completion_decision(
        review_count=2,
        run_result={"status": "partial", "risks": ["write_not_verified"]},
        tool_calls=[],
        content=content,
        finish_reason="stop",
    )

    assert decision["action"] == "final_answer_candidate"
    assert decision["content_chars"] == len(content)
    assert decision["risks"] == ["write_not_verified"]


def test_completion_self_assessment_extracts_model_judgment_and_answer() -> None:
    content = """{"schema_version":"completion_self_assessment.v1","kind":"completion_self_assessment","goal_closed":false,"remaining_work":["rebuild the generated registry"],"verification_limits":["visual rendering was not checked"]}
The manifest exists, but the catalog is not fully registered."""

    answer, assessment = extract_completion_self_assessment(content)

    assert answer == "The manifest exists, but the catalog is not fully registered."
    assert assessment == {
        "schema_version": "completion_self_assessment.v1",
        "kind": "completion_self_assessment",
        "source": "model_declared",
        "goal_closed": False,
        "remaining_work": ["rebuild the generated registry"],
        "verification_limits": ["visual rendering was not checked"],
    }


def test_completion_self_assessment_does_not_infer_from_ordinary_prose() -> None:
    content = "The file was written, but the generated index was not rebuilt."

    answer, assessment = extract_completion_self_assessment(content)

    assert answer == content
    assert assessment is None


def test_completion_self_assessment_keeps_malformed_header_as_visible_prose() -> None:
    content = """{"schema_version":"completion_self_assessment.v1","goal_closed":false}
The task remains incomplete."""

    answer, assessment = extract_completion_self_assessment(content)

    assert answer == content
    assert assessment is None


def test_completion_decision_records_explicit_model_self_assessment() -> None:
    assessment = {
        "schema_version": "completion_self_assessment.v1",
        "kind": "completion_self_assessment",
        "source": "model_declared",
        "goal_closed": False,
        "remaining_work": ["rebuild registry"],
        "verification_limits": [],
    }

    decision = build_completion_decision(
        review_count=2,
        run_result={"status": "success"},
        tool_calls=[],
        content="The manifest exists, but registration is incomplete.",
        self_assessment=assessment,
    )

    assert decision["action"] == "final_answer_candidate"
    assert decision["self_assessment"] == assessment


def test_completion_decision_records_protocol_repair_evidence() -> None:
    decision = build_completion_decision(
        review_count=1,
        run_result={"status": "partial"},
        tool_calls=[],
        content="<toolcall>filesystem.write_file</toolcall>",
        reason="malformed_tool_call",
    )

    assert decision["action"] == "repair_protocol"
    assert decision["reason"] == "malformed_tool_call"


def test_completion_decision_records_compact_evidence_pack_summary() -> None:
    decision = build_completion_decision(
        review_count=2,
        run_result={"status": "partial", "risks": ["visual_verification_not_observed"]},
        tool_calls=[],
        content="Still missing visual verification.",
        evidence_pack={
            "schema_version": "completion_evidence_pack.v1",
            "kind": "completion_evidence_pack",
            "boundary": "evidence_only",
            "result_status": "partial",
            "risks": ["visual_verification_not_observed"],
            "missing_verification_modalities": ["visual"],
            "artifact_summary": {
                "count": 2,
                "by_role": {"final": 1, "screenshot": 1},
                "final_paths": ["viewer/index.html"],
                "visual_paths": ["viewer/preview.png"],
                "model_context_paths": ["viewer/preview.png"],
                "flags": {
                    "has_final_artifacts": True,
                    "has_visual_artifacts": True,
                    "has_model_context_artifacts": True,
                },
            },
            "verification_closure": {
                "result_status": "partial",
                "modalities": {"missing": ["visual"]},
                "gap_facts": ["missing_modality:visual"],
                "gap_risks": ["visual_verification_not_observed"],
                "flags": {
                    "has_required_gap": True,
                    "has_sufficient_verification": False,
                    "has_runtime_errors": False,
                },
            },
            "tool_progress": [
                {"tool": "preview.capture_file", "status": "failure", "role": "preview_service"}
            ],
            "tool_attempts": [
                {"tool": "filesystem.write_file", "reason": "invalid_tool_input"}
            ],
            "tool_attempt_recovery": {
                "schema_version": "tool_attempt_recovery.v1",
                "kind": "tool_attempt_recovery",
                "boundary": "evidence_only",
                "counts": {
                    "attempts": 1,
                    "recoverable_by_model": 1,
                    "hard_runtime_boundary": 0,
                    "large_write_like_payload": 0,
                },
                "reason_counts": {"invalid_tool_input": 1},
                "boundary_counts": {"tool_call_protocol": 1},
                "flags": {
                    "has_recoverable_attempts": True,
                    "has_hard_runtime_boundary": False,
                    "has_large_write_like_payload": False,
                },
                "model_facts": ["missing_fields=path"],
            },
            "task_route_evidence": {
                "schema_version": "task_route_evidence.v1",
                "kind": "task_route_evidence",
                "proposal_count": 1,
                "valid_proposal_count": 0,
                "target_capability_ids": ["preview.visual_debug"],
                "advisory_codes": ["unknown_capability"],
                "flags": {
                    "has_model_route": True,
                    "all_routes_valid": False,
                    "has_unknown_capability": True,
                },
            },
        },
    )

    assert decision["evidence_pack"]["schema_version"] == "completion_evidence_pack.v1"
    assert decision["evidence_pack"]["result_status"] == "partial"
    assert decision["evidence_pack"]["missing_verification_modalities"] == ["visual"]
    assert decision["evidence_pack"]["artifact_summary"]["final_paths"] == ["viewer/index.html"]
    assert decision["evidence_pack"]["artifact_summary"]["model_context_paths"] == [
        "viewer/preview.png"
    ]
    assert decision["evidence_pack"]["artifact_summary"]["has_visual_artifacts"] is True
    assert decision["evidence_pack"]["verification_closure"]["missing_modalities"] == ["visual"]
    assert decision["evidence_pack"]["verification_closure"]["gap_facts"] == [
        "missing_modality:visual"
    ]
    assert decision["evidence_pack"]["tool_progress"][0]["tool"] == "preview.capture_file"
    assert decision["evidence_pack"]["tool_attempts"][0]["tool"] == "filesystem.write_file"
    assert decision["evidence_pack"]["tool_attempt_recovery"]["attempts"] == 1
    assert decision["evidence_pack"]["tool_attempt_recovery"]["has_recoverable_attempts"] is True
    assert decision["evidence_pack"]["tool_attempt_recovery"]["model_facts"] == [
        "missing_fields=path"
    ]
    assert decision["evidence_pack"]["task_route_evidence"]["target_capability_ids"] == [
        "preview.visual_debug"
    ]
    assert decision["evidence_pack"]["task_route_evidence"]["has_unknown_capability"] is True
