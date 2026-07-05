from runtime.agent_strategy.run_finalization import (
    CHANGE_TARGET_DELIVERABLE_STRATEGY,
    COMPLETION_REVIEW,
    CONTINUE_TARGET_DELIVERABLE_GAP,
    CONTINUE_VERIFICATION_GAP,
    FINAL_ANSWER_CONVERGED,
    FINAL_ANSWER_VERIFIED,
    NEEDS_VERIFICATION_EVIDENCE,
    POST_DELIVERABLE_STAGE,
    STOP_STAGNANT_VERIFICATION_GAP,
    build_finalization_gate,
    build_target_deliverable_gap_decision,
    build_verification_gap_decision,
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


def test_verification_gap_decision_stops_only_after_repeated_stagnation() -> None:
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

    assert decision.action == STOP_STAGNANT_VERIFICATION_GAP


def test_target_deliverable_gap_continues_when_facts_change() -> None:
    first = build_target_deliverable_gap_decision(
        previous_key="",
        current_key="tools=read-file",
        prompt_count=0,
        stagnant_rounds=0,
    )
    second = build_target_deliverable_gap_decision(
        previous_key=first.key,
        current_key="tools=read-file,preview-html",
        prompt_count=first.prompt_count,
        stagnant_rounds=first.stagnant_rounds,
    )

    assert first.action == CONTINUE_TARGET_DELIVERABLE_GAP
    assert second.action == CONTINUE_TARGET_DELIVERABLE_GAP
    assert second.stagnant_rounds == 0


def test_target_deliverable_gap_requests_strategy_change_without_stop_action() -> None:
    decision = build_target_deliverable_gap_decision(
        previous_key="",
        current_key="tools=read-file",
        prompt_count=0,
        stagnant_rounds=0,
        strategy_change_stagnant_rounds=3,
    )
    for _ in range(3):
        decision = build_target_deliverable_gap_decision(
            previous_key=decision.key,
            current_key=decision.key,
            prompt_count=decision.prompt_count,
            stagnant_rounds=decision.stagnant_rounds,
            strategy_change_stagnant_rounds=3,
        )

    assert decision.action == CHANGE_TARGET_DELIVERABLE_STRATEGY
    assert "stop" not in decision.action
