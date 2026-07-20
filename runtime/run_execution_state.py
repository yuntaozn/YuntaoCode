"""Mutable lifecycle state for one conversation Run.

This module records execution facts shared across model rounds. It does not
classify the task, choose tools, evaluate capability fit, or decide which
strategy the model should use next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceGapState:
    """Progress counters for one evidence gap observed across rounds."""

    key: str = ""
    prompt_count: int = 0
    stagnant_rounds: int = 0

    def update(self, *, key: str, prompt_count: int, stagnant_rounds: int) -> None:
        self.key = str(key or "")
        self.prompt_count = max(0, int(prompt_count or 0))
        self.stagnant_rounds = max(0, int(stagnant_rounds or 0))


@dataclass
class CompletionReviewState:
    """Model self-review state after target evidence has been observed."""

    event_count: int = -1
    review_count: int = 0
    pending: bool = False
    latest_result: dict[str, Any] = field(default_factory=dict)
    latest_evidence_pack: dict[str, Any] = field(default_factory=dict)

    def begin(
        self,
        *,
        event_count: int,
        run_result: dict[str, Any],
        evidence_pack: dict[str, Any] | None = None,
    ) -> None:
        self.event_count = int(event_count)
        self.review_count += 1
        self.pending = True
        self.latest_result = dict(run_result)
        self.latest_evidence_pack = dict(evidence_pack or {})

    def consume(self) -> None:
        self.pending = False

    def reset_pending(self) -> None:
        self.pending = False
        self.latest_result = {}
        self.latest_evidence_pack = {}


@dataclass
class RunExecutionState:
    """Explicit mutable state for the model/tool lifecycle of one Run."""

    round_limit: int
    hard_round_limit: int
    round_index: int = -1
    max_rounds_exceeded: bool = False
    last_read_summary_key: str = ""
    completion_review: CompletionReviewState = field(
        default_factory=CompletionReviewState
    )
    consecutive_idle_timeouts: int = 0
    final_answer_mode: bool = False
    verifier_retry_prompted: bool = False
    verification_gap: EvidenceGapState = field(default_factory=EvidenceGapState)
    malformed_tool_call_retries: int = 0
    progress_observer_count: int = 0
    stagnant_rounds: int = 0
    last_progress_key: str = ""
    no_progress_budget_exhausted: bool = False
    argument_observation_threshold: int = 24_000
    large_argument_observations: int = 0
    guidance_count: int = 0
    model_provider_error: str = ""

    @classmethod
    def create(
        cls,
        max_rounds: int,
        *,
        hard_limit_multiplier: int = 3,
    ) -> "RunExecutionState":
        round_limit = max(1, int(max_rounds or 1))
        multiplier = max(1, int(hard_limit_multiplier or 1))
        return cls(
            round_limit=round_limit,
            hard_round_limit=round_limit * multiplier,
        )

    @property
    def round_number(self) -> int:
        return self.round_index + 1

    def can_start_round(self) -> bool:
        return self.round_number < self.round_limit

    def start_round(self) -> int:
        if not self.can_start_round():
            raise RuntimeError("run round budget is exhausted")
        self.round_index += 1
        return self.round_index

    def extend_round_budget(self, increment: int = 10) -> tuple[int, int]:
        previous_limit = self.round_limit
        self.round_limit = min(
            self.hard_round_limit,
            self.round_limit + max(0, int(increment or 0)),
        )
        return previous_limit, self.round_limit

    def record_guidance(self) -> None:
        self.guidance_count += 1
        self.final_answer_mode = False
        self.completion_review.reset_pending()

    @property
    def runtime_intervention_count(self) -> int:
        """Backward-compatible alias for older diagnostic readers."""

        return self.guidance_count

    @runtime_intervention_count.setter
    def runtime_intervention_count(self, value: int) -> None:
        self.guidance_count = max(0, int(value or 0))

    def leave_final_answer_mode(self) -> None:
        self.final_answer_mode = False
        self.completion_review.reset_pending()

    def enter_final_answer_mode(self) -> None:
        self.final_answer_mode = True

    def observe_progress(self, progress_key: str) -> int:
        normalized_key = str(progress_key or "")
        if normalized_key and normalized_key == self.last_progress_key:
            self.stagnant_rounds += 1
        else:
            self.stagnant_rounds = 0
            self.last_progress_key = normalized_key
        return self.stagnant_rounds
