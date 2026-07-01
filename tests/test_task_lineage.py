from __future__ import annotations

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
