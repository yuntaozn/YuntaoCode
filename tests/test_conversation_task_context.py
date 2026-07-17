from __future__ import annotations

from types import SimpleNamespace

from runtime.agent_strategy.conversation_task_context import (
    has_recent_task_context,
    referenced_task_candidate_contract,
    task_lineage_candidates,
)


def _message(role: str, content: str, metadata: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content, metadata=metadata or {})


def test_recent_conversation_requests_model_contract_without_inheriting_semantics() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "Create a lesson page"),
        _message(
            "assistant",
            "partial",
            {
                "run_id": "run-1",
                "task_contract": {
                    "intent": "write_required",
                    "goal": "Create a lesson page",
                    "requires_write": True,
                    "deliverables": [{"kind": "code", "path_hint": "index.html"}],
                },
            },
        ),
    ])

    assert has_recent_task_context(conversation, "try again")
    candidates = task_lineage_candidates(conversation, "try again")
    assert [item["candidate_id"] for item in candidates] == ["run-1"]
    assert referenced_task_candidate_contract(candidates, "") is None
    assert referenced_task_candidate_contract(candidates, "run-1")["goal"] == "Create a lesson page"


def test_diagnostic_feedback_exposes_candidates_without_runtime_routing() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "change home.js to use the FastAPI backend"),
        _message(
            "assistant",
            "updated home.js",
            {
                "run_id": "run-write",
                "task_contract": {
                    "intent": "write_required",
                    "goal": "Modify web/home.js to call the FastAPI backend",
                    "requires_write": True,
                    "requires_state_change": True,
                    "deliverables": [{"kind": "code", "path_hint": "web/home.js"}],
                },
            },
        ),
    ])
    log = (
        "home.js:1 Uncaught TypeError: Cannot set properties of null\n"
        "Failed to load resource: the server responded with a status of 405"
    )

    assert has_recent_task_context(conversation, log)
    candidates = task_lineage_candidates(conversation, log)
    assert candidates[0]["goal"].startswith("Modify web/home.js")
    assert "current_target_match" not in candidates[0]
