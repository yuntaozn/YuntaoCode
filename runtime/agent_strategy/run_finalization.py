"""Pure helpers for deciding when fresh Run evidence needs model review."""

from __future__ import annotations

from dataclasses import dataclass


NO_TARGET_DELIVERABLE = "no_target_deliverable"
NO_TASK_EVIDENCE = "no_task_evidence"
COMPLETION_REVIEW = "completion_review"
EVIDENCE_ALREADY_REVIEWED = "evidence_already_reviewed"


@dataclass(frozen=True)
class CompletionReviewGate:
    """Observable review state for the current Run facts.

    This helper does not inspect verification sufficiency, choose tools, stop a
    model strategy, or decide task success. It only reports whether fresh task
    evidence is available for the model's own completion review.
    """

    action: str
    reason: str = ""


def build_completion_review_gate(
    *,
    requires_target_deliverable: bool,
    has_target_deliverable: bool,
    has_task_evidence: bool,
    has_unreviewed_evidence: bool,
) -> CompletionReviewGate:
    """Return whether current task evidence should be reviewed by the model.

    Write and external-state tasks still use target-deliverable evidence as the
    entry point. Read-only analysis and answer-evidence tasks have no file or
    external object to observe, so successful evidence-gathering tools use the
    same review boundary. Verification gaps are intentionally not an input:
    they are included in the evidence pack and the model decides whether to
    verify, repair, ask the user, or finish with an explicit limitation.
    """

    if requires_target_deliverable and not has_target_deliverable:
        return CompletionReviewGate(
            NO_TARGET_DELIVERABLE,
            "target deliverable not observed",
        )
    if not requires_target_deliverable and not has_task_evidence:
        return CompletionReviewGate(
            NO_TASK_EVIDENCE,
            "task evidence not observed",
        )
    if has_unreviewed_evidence:
        return CompletionReviewGate(
            COMPLETION_REVIEW,
            "fresh task evidence needs model self-review",
        )
    return CompletionReviewGate(
        EVIDENCE_ALREADY_REVIEWED,
        "current task evidence has already been presented to the model",
    )
