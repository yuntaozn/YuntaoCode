from __future__ import annotations

from dataclasses import fields

import pytest

from runtime.run_execution_state import RunExecutionState, TransientModelContext


def test_round_budget_advances_and_extends_to_hard_limit() -> None:
    state = RunExecutionState.create(2, hard_limit_multiplier=3)

    assert state.start_round() == 0
    assert state.start_round() == 1
    assert not state.can_start_round()
    assert state.extend_round_budget(10) == (2, 6)
    assert state.can_start_round()


def test_start_round_rejects_exhausted_budget() -> None:
    state = RunExecutionState.create(1)
    state.start_round()

    with pytest.raises(RuntimeError, match="budget is exhausted"):
        state.start_round()


def test_guidance_resets_transient_finalization_state() -> None:
    state = RunExecutionState.create(10)
    state.completion_review.begin(event_count=4, run_result={"status": "success"})

    state.record_guidance()

    assert state.guidance_count == 1
    assert state.runtime_intervention_count == 1
    assert not state.completion_review.pending
    assert state.completion_review.latest_result == {}
    assert state.completion_review.review_count == 1


def test_completion_review_keeps_auditable_count_after_consumption() -> None:
    state = RunExecutionState.create(10)
    state.completion_review.begin(event_count=7, run_result={"status": "partial"})
    state.completion_review.consume()

    assert state.completion_review.event_count == 7
    assert state.completion_review.review_count == 1
    assert not state.completion_review.pending
    assert state.completion_review.latest_result == {"status": "partial"}


def test_execution_state_does_not_own_convergence_policy() -> None:
    field_names = {item.name for item in fields(RunExecutionState)}

    assert field_names.isdisjoint({
        "progress_observer_count",
        "stagnant_rounds",
        "last_progress_key",
        "no_progress_budget_exhausted",
    })


def test_transient_model_context_is_consumed_by_identity_after_one_response() -> None:
    state = TransientModelContext()
    persistent = {"role": "system", "content": "task contract"}
    transient = {"role": "system", "content": "retry facts"}
    equal_but_distinct = {"role": "system", "content": "retry facts"}
    messages = [persistent, transient, equal_but_distinct]
    state.add(transient)

    remaining = state.consume_from(messages)

    assert remaining == [persistent, equal_but_distinct]
    assert state.pending_messages == []
