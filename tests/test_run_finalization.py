from runtime.agent_strategy.run_finalization import (
    ACCEPT_COMPLETION_CANDIDATE,
    COMPLETION_REVIEW,
    CONTINUE_VERIFICATION_GAP,
    FINAL_ANSWER_CONVERGED,
    FINAL_ANSWER_VERIFIED,
    NEEDS_VERIFICATION_EVIDENCE,
    NO_TASK_EVIDENCE,
    NO_TARGET_DELIVERABLE,
    PAUSE_STAGNANT_VERIFICATION_GAP,
    REENTER_COMPLETION_REVIEW,
    build_completion_reentry_decision,
    build_finalization_gate,
    build_task_evidence_finalization_gate,
    build_verification_gap_decision,
)


def test_missing_verification_evidence_blocks_converged_finalization() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=False,
        needs_verification_evidence=True,
        completion_review_stale=False,
    )

    assert gate.action == NEEDS_VERIFICATION_EVIDENCE


def test_verified_new_evidence_enters_completion_review() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=True,
        needs_verification_evidence=False,
        completion_review_stale=True,
    )

    assert gate.action == COMPLETION_REVIEW


def test_verified_reviewed_evidence_can_enter_final_answer() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=True,
        needs_verification_evidence=False,
        completion_review_stale=False,
    )

    assert gate.action == FINAL_ANSWER_VERIFIED


def test_unverified_target_enters_model_completion_review() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=False,
        needs_verification_evidence=False,
        completion_review_stale=True,
    )

    assert gate.action == COMPLETION_REVIEW


def test_reviewed_target_can_enter_final_answer_without_required_verification() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=False,
        needs_verification_evidence=False,
        completion_review_stale=False,
    )

    assert gate.action == FINAL_ANSWER_CONVERGED


def test_answer_evidence_enters_completion_review_without_target_deliverable() -> None:
    gate = build_task_evidence_finalization_gate(
        requires_target_deliverable=False,
        has_target_deliverable=False,
        has_task_evidence=True,
        has_target_verification=True,
        needs_verification_evidence=False,
        completion_review_stale=True,
    )

    assert gate.action == COMPLETION_REVIEW


def test_task_without_observed_evidence_does_not_enter_completion_review() -> None:
    gate = build_task_evidence_finalization_gate(
        requires_target_deliverable=False,
        has_target_deliverable=False,
        has_task_evidence=False,
        has_target_verification=False,
        needs_verification_evidence=False,
        completion_review_stale=True,
    )

    assert gate.action == NO_TASK_EVIDENCE


def test_target_contract_still_requires_target_deliverable_before_review() -> None:
    gate = build_task_evidence_finalization_gate(
        requires_target_deliverable=True,
        has_target_deliverable=False,
        has_task_evidence=True,
        has_target_verification=True,
        needs_verification_evidence=False,
        completion_review_stale=True,
    )

    assert gate.action == NO_TARGET_DELIVERABLE


def test_verification_gap_decision_continues_when_gap_changes() -> None:
    first = build_verification_gap_decision(
        previous_key="",
        current_key="missing=content",
        prompt_count=0,
        stagnant_rounds=0,
    )
    second = build_verification_gap_decision(
        previous_key=first.key,
        current_key="missing=behavioral",
        prompt_count=first.prompt_count,
        stagnant_rounds=first.stagnant_rounds,
    )

    assert first.action == CONTINUE_VERIFICATION_GAP
    assert second.action == CONTINUE_VERIFICATION_GAP
    assert second.stagnant_rounds == 0


def test_verification_gap_decision_pauses_only_after_repeated_stagnation() -> None:
    decision = build_verification_gap_decision(
        previous_key="",
        current_key="missing=content",
        prompt_count=0,
        stagnant_rounds=0,
    )
    for _ in range(4):
        decision = build_verification_gap_decision(
            previous_key=decision.key,
            current_key=decision.key,
            prompt_count=decision.prompt_count,
            stagnant_rounds=decision.stagnant_rounds,
        )

    assert decision.action == CONTINUE_VERIFICATION_GAP

    decision = build_verification_gap_decision(
        previous_key=decision.key,
        current_key=decision.key,
        prompt_count=decision.prompt_count,
        stagnant_rounds=decision.stagnant_rounds,
    )

    assert decision.action == PAUSE_STAGNANT_VERIFICATION_GAP


def test_completion_reentry_reopens_final_candidate_with_unresolved_gap() -> None:
    decision = build_completion_reentry_decision(
        completion_decision={
            "action": "final_answer_candidate",
            "risks": ["test_not_observed"],
        },
        run_result={
            "status": "partial",
            "risks": ["test_not_observed"],
            "missing_verification_modalities": ["behavioral"],
        },
    )

    assert decision.action == REENTER_COMPLETION_REVIEW
    assert "unresolved verification" in decision.reason


def test_completion_reentry_accepts_candidate_without_unresolved_gap() -> None:
    decision = build_completion_reentry_decision(
        completion_decision={"action": "final_answer_candidate", "risks": []},
        run_result={"status": "success", "risks": [], "missing_verification_modalities": []},
    )

    assert decision.action == ACCEPT_COMPLETION_CANDIDATE


def test_completion_reentry_does_not_override_model_tool_continuation() -> None:
    decision = build_completion_reentry_decision(
        completion_decision={"action": "continue_with_tools"},
        run_result={"status": "partial", "risks": ["test_not_observed"]},
    )

    assert decision.action == ACCEPT_COMPLETION_CANDIDATE
