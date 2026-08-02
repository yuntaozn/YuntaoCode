from __future__ import annotations

import inspect

from runtime.agent_strategy.run_finalization import (
    COMPLETION_REVIEW,
    EVIDENCE_ALREADY_REVIEWED,
    NO_TASK_EVIDENCE,
    NO_TARGET_DELIVERABLE,
    build_completion_review_gate,
)


def test_fresh_target_evidence_enters_model_completion_review() -> None:
    gate = build_completion_review_gate(
        requires_target_deliverable=True,
        has_target_deliverable=True,
        has_task_evidence=True,
        has_unreviewed_evidence=True,
    )

    assert gate.action == COMPLETION_REVIEW


def test_reviewed_target_evidence_does_not_force_another_round() -> None:
    gate = build_completion_review_gate(
        requires_target_deliverable=True,
        has_target_deliverable=True,
        has_task_evidence=True,
        has_unreviewed_evidence=False,
    )

    assert gate.action == EVIDENCE_ALREADY_REVIEWED


def test_answer_evidence_enters_review_without_target_deliverable() -> None:
    gate = build_completion_review_gate(
        requires_target_deliverable=False,
        has_target_deliverable=False,
        has_task_evidence=True,
        has_unreviewed_evidence=True,
    )

    assert gate.action == COMPLETION_REVIEW


def test_task_without_observed_evidence_does_not_enter_review() -> None:
    gate = build_completion_review_gate(
        requires_target_deliverable=False,
        has_target_deliverable=False,
        has_task_evidence=False,
        has_unreviewed_evidence=True,
    )

    assert gate.action == NO_TASK_EVIDENCE


def test_target_contract_requires_target_deliverable_before_review() -> None:
    gate = build_completion_review_gate(
        requires_target_deliverable=True,
        has_target_deliverable=False,
        has_task_evidence=True,
        has_unreviewed_evidence=True,
    )

    assert gate.action == NO_TARGET_DELIVERABLE


def test_review_gate_cannot_reintroduce_verification_as_loop_control() -> None:
    parameters = set(inspect.signature(build_completion_review_gate).parameters)

    assert parameters == {
        "requires_target_deliverable",
        "has_target_deliverable",
        "has_task_evidence",
        "has_unreviewed_evidence",
    }
