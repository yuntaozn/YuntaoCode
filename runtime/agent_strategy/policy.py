"""Routing and planning policy for the agent runtime.

This module is the first stop for request-level decisions.  It keeps cheap,
deterministic policy decisions out of the model loop and reserves model-based
planning judgment for genuinely ambiguous requests.
"""

from __future__ import annotations

from dataclasses import dataclass

from .profiles import AgentProfile, profile_for_task_intent


@dataclass(frozen=True)
class PlanGateDecision:
    enabled: bool | None
    source: str
    reason: str

    @property
    def needs_model_judge(self) -> bool:
        return self.enabled is None

    def to_public_dict(self, mode: str) -> dict[str, object]:
        return {
            "mode": mode,
            "enabled": bool(self.enabled),
            "reason": self.reason,
            "source": self.source,
        }


def resolve_profile(
    task_intent: str,
    mode: str | None,
    *,
    code_change_intent: bool = False,
    state_change_intent: bool = False,
    first_action: str | None = None,
) -> AgentProfile:
    return profile_for_task_intent(
        task_intent,
        mode,
        code_change_intent=code_change_intent,
        state_change_intent=state_change_intent,
        first_action=first_action,
    )


def deterministic_plan_gate(
    content: str,
    task_intent: str,
    mode: str | None,
    planning_policy: str,
    *,
    profile: AgentProfile | None = None,
) -> PlanGateDecision:
    """Apply only the user's explicit planning policy.

    In auto mode the model owns the planning decision. Content keywords and
    request length are not runtime routing rules.
    """
    normalized_planning_policy = str(planning_policy or "auto").lower()
    if normalized_planning_policy == "off":
        return PlanGateDecision(False, "user", "计划执行已关闭")
    if normalized_planning_policy == "always":
        return PlanGateDecision(True, "user", "已选择总是使用计划执行")

    _ = (content, task_intent, mode, profile)
    return PlanGateDecision(None, "model", "自动模式由模型判断是否需要计划执行")


def heuristic_plan_execution(content: str, mode: str | None) -> bool:
    """Neutral fallback when the plan-judge call is unavailable."""
    _ = (content, mode)
    return False
