from runtime.agent_strategy.run_finalization import (
    COMPLETION_REVIEW,
    FINAL_ANSWER_CONVERGED,
    FINAL_ANSWER_VERIFIED,
    NEEDS_VERIFICATION_EVIDENCE,
    POST_DELIVERABLE_STAGE,
    build_finalization_gate,
)


def test_missing_verification_evidence_blocks_converged_finalization() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=False,
        needs_verification_evidence=True,
        post_deliverable_mode=True,
        post_deliverable_rounds=5,
        round_had_post_deliverable_verification=True,
        post_deliverable_refusals=0,
        round_had_post_deliverable_change=False,
        completion_review_stale=False,
    )

    assert gate.action == NEEDS_VERIFICATION_EVIDENCE


def test_verified_new_evidence_enters_completion_review() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=True,
        needs_verification_evidence=False,
        post_deliverable_mode=True,
        post_deliverable_rounds=1,
        round_had_post_deliverable_verification=True,
        post_deliverable_refusals=0,
        round_had_post_deliverable_change=False,
        completion_review_stale=True,
    )

    assert gate.action == COMPLETION_REVIEW


def test_verified_reviewed_evidence_can_enter_final_answer() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=True,
        needs_verification_evidence=False,
        post_deliverable_mode=True,
        post_deliverable_rounds=2,
        round_had_post_deliverable_verification=True,
        post_deliverable_refusals=0,
        round_had_post_deliverable_change=False,
        completion_review_stale=False,
    )

    assert gate.action == FINAL_ANSWER_VERIFIED


def test_target_before_followup_enters_post_deliverable_stage() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=False,
        needs_verification_evidence=False,
        post_deliverable_mode=False,
        post_deliverable_rounds=0,
        round_had_post_deliverable_verification=False,
        post_deliverable_refusals=0,
        round_had_post_deliverable_change=False,
        completion_review_stale=False,
    )

    assert gate.action == POST_DELIVERABLE_STAGE


def test_post_deliverable_convergence_can_enter_final_answer_without_required_verification() -> None:
    gate = build_finalization_gate(
        has_target_deliverable=True,
        has_target_verification=False,
        needs_verification_evidence=False,
        post_deliverable_mode=True,
        post_deliverable_rounds=3,
        round_had_post_deliverable_verification=True,
        post_deliverable_refusals=0,
        round_had_post_deliverable_change=False,
        completion_review_stale=False,
    )

    assert gate.action == FINAL_ANSWER_CONVERGED
