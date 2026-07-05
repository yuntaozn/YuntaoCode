from __future__ import annotations

import json

from types import SimpleNamespace

from runtime.agent_strategy.task_lineage import (
    collect_task_lineage_candidates,
    format_task_candidates_for_model,
    referenced_candidate_contract,
    task_candidate_from_message,
)


def _message(role: str, content: str, metadata: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content, metadata=metadata or {})


def test_task_lineage_extracts_candidate_from_assistant_contract() -> None:
    candidate = task_candidate_from_message(
        role="assistant",
        content="done",
        metadata={
            "run_id": "run-1",
            "task_contract": {
                "goal": "Create a Blender house",
                "intent": "write_required",
                "requires_write": False,
                "requires_state_change": True,
                "deliverables": [{"kind": "external_state"}],
                "capability_ids": ["mcp.blender"],
            },
        },
        index=1,
    )

    assert candidate is not None
    assert candidate["candidate_id"] == "run-1"
    assert candidate["goal"] == "Create a Blender house"
    assert candidate["deliverable_kinds"] == ["external_state"]
    assert candidate["contract_anchor"]["goal"] == "Create a Blender house"


def test_task_lineage_extracts_runtime_observed_paths_from_run_result() -> None:
    candidate = task_candidate_from_message(
        role="assistant",
        content="partial",
        metadata={
            "run_id": "run-1",
            "task_contract": {
                "goal": "Fix lesson interaction",
                "intent": "write_required",
                "requires_write": True,
                "deliverables": [{"kind": "code", "path_hint": "src/app.js"}],
            },
            "run_result": {
                "status": "partial",
                "changed_paths": ["lesson/src/app.js"],
                "target_written_paths": ["lesson/src/app.js"],
                "observed_written_paths": ["lesson/src/app.js"],
                "verified": [{"path": "artifacts/preview/index.png"}],
                "verification_evidence": [{"path": "artifacts/preview/index.png"}],
            },
        },
        index=1,
    )

    assert candidate is not None
    assert candidate["status"] == "partial"
    assert candidate["target_written_paths"] == ["lesson/src/app.js"]
    assert candidate["changed_paths"] == ["lesson/src/app.js"]
    assert candidate["verified_paths"] == ["artifacts/preview/index.png"]
    assert candidate["actual_paths"][:2] == [
        "lesson/src/app.js",
        "artifacts/preview/index.png",
    ]


def test_task_lineage_reference_anchor_prefers_runtime_observed_write_targets() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "change lesson"),
        _message(
            "assistant",
            "partial",
            {
                "run_id": "run-1",
                "task_contract": {
                    "goal": "Fix lesson interaction",
                    "intent": "write_required",
                    "requires_write": True,
                    "requires_state_change": True,
                    "requires_verification": True,
                    "deliverables": [
                        {
                            "kind": "code",
                            "path_hint": "D:/code/courseware",
                            "path_policy": "hint",
                            "description": "Broad project directory",
                        }
                    ],
                },
                "run_result": {
                    "status": "partial",
                    "target_written_paths": ["lesson/src/app.js"],
                    "changed_paths": ["lesson/src/app.js"],
                },
            },
        ),
        _message("user", "try again"),
    ])

    candidates = collect_task_lineage_candidates(conversation, "try again")
    anchor = referenced_candidate_contract(candidates, "run-1")

    assert anchor is not None
    assert anchor["deliverables"][0]["path_hint"] == "lesson/src/app.js"
    assert anchor["deliverables"][0]["description"] == (
        "Runtime-observed target path from the referenced run"
    )
    assert anchor["deliverables"][1]["path_hint"] == "D:/code/courseware"


def test_task_lineage_skips_answer_only_contracts() -> None:
    candidate = task_candidate_from_message(
        role="assistant",
        content="explanation",
        metadata={
            "task_contract": {
                "goal": "Explain MCP setup",
                "intent": "answer_only",
            }
        },
    )

    assert candidate is None


def test_task_lineage_candidates_can_be_referenced_by_model_contract() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "Create a Blender house"),
        _message(
            "assistant",
            "partial",
            {
                "run_id": "run-1",
                "task_contract": {
                    "goal": "Create a Blender house",
                    "intent": "write_required",
                    "requires_state_change": True,
                    "deliverables": [{"kind": "external_state"}],
                },
            },
        ),
        _message("user", "try again"),
    ])

    candidates = collect_task_lineage_candidates(conversation, "try again")
    anchor = referenced_candidate_contract(candidates, "run-1")

    assert len(candidates) == 1
    assert anchor is not None
    assert anchor["goal"] == "Create a Blender house"
    prompt = format_task_candidates_for_model(candidates)
    assert "task_lineage_context.v1" in prompt
    assert "run-1" in prompt


def test_task_lineage_candidates_are_ordered_most_recent_first_with_paths() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "old task"),
        _message(
            "assistant",
            "old partial",
            {
                "run_id": "old-run",
                "task_contract": {
                    "goal": "Old lesson change",
                    "intent": "write_required",
                    "requires_write": True,
                    "deliverables": [{"kind": "code", "path_hint": "src/old.js"}],
                },
                "run_result": {
                    "status": "partial",
                    "target_written_paths": ["src/old.js"],
                    "changed_paths": ["src/old.js"],
                },
            },
        ),
        _message("user", "new task"),
        _message(
            "assistant",
            "new partial",
            {
                "run_id": "new-run",
                "task_contract": {
                    "goal": "New lesson change",
                    "intent": "write_required",
                    "requires_write": True,
                    "deliverables": [{"kind": "code", "path_hint": "src/app.js"}],
                },
                "run_result": {
                    "status": "partial",
                    "target_written_paths": ["src/app.js"],
                    "changed_paths": ["src/app.js"],
                },
            },
        ),
        _message("user", "still not verified"),
    ])

    candidates = collect_task_lineage_candidates(conversation, "still not verified")
    prompt = format_task_candidates_for_model(candidates)

    assert [candidate["candidate_id"] for candidate in candidates] == [
        "new-run",
        "old-run",
    ]
    assert candidates[0]["recency_rank"] == 1
    assert candidates[0]["lineage_rank"] == 1
    assert candidates[0]["actual_paths"] == ["src/app.js"]
    assert prompt.index("new-run") < prompt.index("old-run")
    assert "src/app.js" in prompt
    payload = json.loads(prompt)
    assert payload["active_target"]["candidate_id"] == "new-run"
    assert payload["active_target"]["target_paths"] == ["src/app.js"]


def test_task_lineage_target_correction_prefers_matching_observed_path_over_recency() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "change target subproject"),
        _message(
            "assistant",
            "right target partial",
            {
                "run_id": "right-target-run",
                "task_contract": {
                    "goal": "Fix interaction behavior in the correct subproject",
                    "intent": "write_required",
                    "requires_write": True,
                    "deliverables": [{"kind": "code", "path_hint": "独立基础施工全过程/交互动画/src/app.js"}],
                },
                "run_result": {
                    "status": "partial",
                    "target_written_paths": ["独立基础施工全过程/交互动画/src/app.js"],
                    "changed_paths": ["独立基础施工全过程/交互动画/src/app.js"],
                },
            },
        ),
        _message("user", "try again"),
        _message(
            "assistant",
            "wrong target partial",
            {
                "run_id": "wrong-target-run",
                "task_contract": {
                    "goal": "Retry interaction behavior",
                    "intent": "write_required",
                    "requires_write": True,
                    "deliverables": [{"kind": "code", "path_hint": "无机磨石施工工艺/2d_interactive_demo.html"}],
                },
                "run_result": {
                    "status": "partial",
                    "target_written_paths": ["无机磨石施工工艺/2d_interactive_demo.html"],
                    "changed_paths": ["无机磨石施工工艺/2d_interactive_demo.html"],
                },
            },
        ),
        _message("user", "上一轮改错了子项目，要改的是 独立基础施工全过程 的交互动画"),
    ])

    candidates = collect_task_lineage_candidates(
        conversation,
        "上一轮改错了子项目，要改的是 独立基础施工全过程 的交互动画",
    )
    prompt = format_task_candidates_for_model(candidates)

    assert [candidate["candidate_id"] for candidate in candidates[:2]] == [
        "right-target-run",
        "wrong-target-run",
    ]
    assert candidates[0]["current_target_match"] is True
    assert candidates[0]["current_target_affinity"] > 0
    assert candidates[1]["current_target_match"] is False
    assert "current_target_match" in prompt
    assert prompt.index("right-target-run") < prompt.index("wrong-target-run")


def test_task_lineage_prioritizes_recent_target_paths_over_failed_verification_attempt() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "change lesson"),
        _message(
            "assistant",
            "partial",
            {
                "run_id": "write-run",
                "task_contract": {
                    "goal": "Fix lesson interaction",
                    "intent": "write_required",
                    "requires_write": True,
                    "deliverables": [{"kind": "code", "path_hint": "src/app.js"}],
                },
                "run_result": {
                    "status": "partial",
                    "target_written_paths": ["src/app.js"],
                    "changed_paths": ["src/app.js"],
                },
            },
        ),
        _message("user", "verify it"),
        _message(
            "assistant",
            "failed verification",
            {
                "run_id": "verify-run",
                "task_contract": {
                    "goal": "Verify lesson interaction",
                    "intent": "read_only_analysis",
                    "requires_verification": True,
                    "deliverables": [{"kind": "answer"}],
                },
                "run_result": {
                    "status": "failure",
                    "verified": [{"path": "src/app_optimized.js"}],
                    "changed_paths": [],
                    "target_written_paths": [],
                },
            },
        ),
        _message("user", "still not verified"),
    ])

    candidates = collect_task_lineage_candidates(conversation, "still not verified")
    prompt = format_task_candidates_for_model(candidates)

    assert [candidate["candidate_id"] for candidate in candidates] == [
        "write-run",
        "verify-run",
    ]
    assert candidates[0]["recency_rank"] == 2
    assert candidates[0]["lineage_rank"] == 1
    assert candidates[0]["actual_paths"] == ["src/app.js"]
    assert candidates[1]["actual_paths"] == ["src/app_optimized.js"]
    assert "should not replace the target paths" in prompt
