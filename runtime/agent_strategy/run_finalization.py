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


@dataclass(frozen=True)
class FinalizationGate:
    """Observable finalization state for the current run facts.

    This helper does not choose tools, stop a model strategy, or decide task
    success by itself. It only keeps the runner from entering final-answer mode
    while the task contract still needs verification evidence.
    """

    action: str
    reason: str = ""


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
