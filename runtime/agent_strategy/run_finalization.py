"""Pure helpers for deciding whether a run can enter final answer mode."""

from __future__ import annotations

from dataclasses import dataclass


NO_TARGET_DELIVERABLE = "no_target_deliverable"
NEEDS_VERIFICATION_EVIDENCE = "needs_verification_evidence"
COMPLETION_REVIEW = "completion_review"
FINAL_ANSWER_VERIFIED = "final_answer_verified"
FINAL_ANSWER_CONVERGED = "final_answer_converged"
CONTINUE_VERIFICATION_GAP = "continue_verification_gap"
STOP_STAGNANT_VERIFICATION_GAP = "stop_stagnant_verification_gap"


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


def build_finalization_gate(
    *,
    has_target_deliverable: bool,
    has_target_verification: bool,
    needs_verification_evidence: bool,
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
    if completion_review_stale:
        return FinalizationGate(COMPLETION_REVIEW, "new evidence needs model self-review")
    if has_target_verification:
        return FinalizationGate(FINAL_ANSWER_VERIFIED, "target and verification observed")
    return FinalizationGate(
        FINAL_ANSWER_CONVERGED,
        "model self-review completed without requesting another tool action",
    )


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
