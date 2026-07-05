"""Pure helpers for deciding whether a run can enter final answer mode."""

from __future__ import annotations

from dataclasses import dataclass


NO_TARGET_DELIVERABLE = "no_target_deliverable"
NEEDS_VERIFICATION_EVIDENCE = "needs_verification_evidence"
POST_DELIVERABLE_STAGE = "post_deliverable_stage"
COMPLETION_REVIEW = "completion_review"
FINAL_ANSWER_VERIFIED = "final_answer_verified"
FINAL_ANSWER_CONVERGED = "final_answer_converged"
CONTINUE_POST_DELIVERABLE = "continue_post_deliverable"
CONTINUE_VERIFICATION_GAP = "continue_verification_gap"
STOP_STAGNANT_VERIFICATION_GAP = "stop_stagnant_verification_gap"
CONTINUE_TARGET_DELIVERABLE_GAP = "continue_target_deliverable_gap"
CHANGE_TARGET_DELIVERABLE_STRATEGY = "change_target_deliverable_strategy"


@dataclass(frozen=True)
class FinalizationGate:
    """Observable finalization state for the current run facts.

    This helper does not choose tools, stop a model strategy, or decide task
    success by itself. It only keeps the runner from entering final-answer mode
    while the task contract still needs verification evidence.
    """

    action: str
    reason: str = ""


@dataclass(frozen=True)
class VerificationGapDecision:
    """Progress-aware decision for missing verification evidence.

    The runner should keep the model in charge of the next strategy. This
    helper only detects whether the same verification gap has remained
    unchanged across repeated model rounds, so the runtime can avoid infinite
    loops without stopping after the first incomplete self-review.
    """

    action: str
    reason: str
    prompt_count: int
    stagnant_rounds: int
    key: str


@dataclass(frozen=True)
class TargetDeliverableGapDecision:
    """Progress-aware advisory for missing target deliverables.

    This decision intentionally has no stop action. A missing write, export, or
    external-state deliverable is a fact the model should see, not a runtime
    reason to terminate by itself. The runner can still stop at global safety
    limits, but this helper only says whether the observable facts changed or
    whether the model should choose a materially different route.
    """

    action: str
    reason: str
    prompt_count: int
    stagnant_rounds: int
    key: str


def build_finalization_gate(
    *,
    has_target_deliverable: bool,
    has_target_verification: bool,
    needs_verification_evidence: bool,
    post_deliverable_mode: bool,
    post_deliverable_rounds: int,
    round_had_post_deliverable_verification: bool,
    post_deliverable_refusals: int,
    round_had_post_deliverable_change: bool,
    completion_review_stale: bool,
) -> FinalizationGate:
    """Return the next finalization action from runtime facts.

    The important invariant is that missing required verification evidence wins
    over convergence. A run may look quiet after producing a target artifact,
    but quietness is not completion when the task contract still asks for
    verification.
    """

    if not has_target_deliverable:
        return FinalizationGate(NO_TARGET_DELIVERABLE, "target deliverable not observed")
    if needs_verification_evidence:
        return FinalizationGate(
            NEEDS_VERIFICATION_EVIDENCE,
            "task contract still needs verification evidence",
        )
    if has_target_verification:
        if completion_review_stale:
            return FinalizationGate(COMPLETION_REVIEW, "new evidence needs model self-review")
        return FinalizationGate(FINAL_ANSWER_VERIFIED, "target and verification observed")
    if not post_deliverable_mode:
        return FinalizationGate(POST_DELIVERABLE_STAGE, "target observed before follow-up stage")
    if post_deliverable_rounds >= 3 and (
        round_had_post_deliverable_verification
        or (
            post_deliverable_refusals > 2
            and not round_had_post_deliverable_change
        )
    ):
        return FinalizationGate(FINAL_ANSWER_CONVERGED, "post-deliverable work converged")
    return FinalizationGate(CONTINUE_POST_DELIVERABLE, "post-deliverable work can continue")


def build_verification_gap_decision(
    *,
    previous_key: str,
    current_key: str,
    prompt_count: int,
    stagnant_rounds: int,
    max_stagnant_rounds: int = 4,
    min_prompts_before_stop: int = 6,
) -> VerificationGapDecision:
    """Decide whether a missing-verification loop still has room to continue.

    ``current_key`` should summarize observable runtime facts such as missing
    modalities, observed modalities, tool count, and deliverable count. If the
    key changes, the model produced some new evidence or changed the run state,
    so the stagnation counter resets.
    """

    next_prompt_count = max(0, prompt_count) + 1
    if current_key and current_key == previous_key:
        next_stagnant_rounds = max(0, stagnant_rounds) + 1
    else:
        next_stagnant_rounds = 0

    if (
        next_prompt_count >= max(1, min_prompts_before_stop)
        and next_stagnant_rounds >= max(1, max_stagnant_rounds)
    ):
        return VerificationGapDecision(
            STOP_STAGNANT_VERIFICATION_GAP,
            "verification gap remained unchanged across repeated rounds",
            next_prompt_count,
            next_stagnant_rounds,
            current_key,
        )
    return VerificationGapDecision(
        CONTINUE_VERIFICATION_GAP,
        "verification gap still has room for model-selected correction",
        next_prompt_count,
        next_stagnant_rounds,
        current_key,
    )


def build_target_deliverable_gap_decision(
    *,
    previous_key: str,
    current_key: str,
    prompt_count: int,
    stagnant_rounds: int,
    strategy_change_stagnant_rounds: int = 3,
) -> TargetDeliverableGapDecision:
    """Return a non-blocking advisory for missing target deliverables.

    ``current_key`` should summarize observable progress facts such as tool
    count, read/preview evidence, failed write attempts, target paths, and
    diagnostics. If that key changes, the model found new facts or changed the
    run state, so the runtime should keep giving it room. If it remains
    unchanged for several rounds, the runtime asks for a route change instead
    of marking the task failed here.
    """

    next_prompt_count = max(0, prompt_count) + 1
    if current_key and current_key == previous_key:
        next_stagnant_rounds = max(0, stagnant_rounds) + 1
    else:
        next_stagnant_rounds = 0

    if next_stagnant_rounds >= max(1, strategy_change_stagnant_rounds):
        return TargetDeliverableGapDecision(
            CHANGE_TARGET_DELIVERABLE_STRATEGY,
            "target deliverable gap is stagnant; ask the model to change route",
            next_prompt_count,
            next_stagnant_rounds,
            current_key,
        )
    return TargetDeliverableGapDecision(
        CONTINUE_TARGET_DELIVERABLE_GAP,
        "target deliverable still has room for model-selected correction",
        next_prompt_count,
        next_stagnant_rounds,
        current_key,
    )
