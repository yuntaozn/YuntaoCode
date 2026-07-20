from __future__ import annotations

import pytest

from runtime.run_execution_state import RunExecutionState


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
    state.final_answer_mode = True
    state.completion_review.begin(event_count=4, run_result={"status": "success"})

    state.record_guidance()

    assert state.guidance_count == 1
    assert state.runtime_intervention_count == 1
    assert not state.final_answer_mode
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


def test_progress_stagnation_resets_when_evidence_key_changes() -> None:
    state = RunExecutionState.create(10)

    assert state.observe_progress("read:a") == 0
    assert state.observe_progress("read:a") == 1
    assert state.observe_progress("write:b") == 0
    assert state.last_progress_key == "write:b"


def test_evidence_gap_state_normalizes_counters() -> None:
    state = RunExecutionState.create(10)

    state.verification_gap.update(
        key="missing=visual",
        prompt_count=2,
        stagnant_rounds=3,
    )

    assert state.verification_gap.key == "missing=visual"
    assert state.verification_gap.prompt_count == 2
    assert state.verification_gap.stagnant_rounds == 3
