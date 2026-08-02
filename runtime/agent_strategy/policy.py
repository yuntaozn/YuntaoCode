"""Routing and planning policy for the agent runtime.

Planning has one semantic authority: the task contract model.  This module
only reconciles that declaration with the user's explicit planning setting;
it does not run a second task-classification path.
"""

from __future__ import annotations

from dataclasses import dataclass

from .profiles import AgentProfile, profile_for_task_intent


@dataclass(frozen=True)
class PlanExecutionDecision:
    enabled: bool
    source: str
    reason: str

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


def resolve_plan_execution(
    task_contract: dict[str, object] | None,
    planning_policy: str,
) -> PlanExecutionDecision:
    """Resolve pre-execution plan generation without another model call.

    Explicit user settings remain authoritative.  In auto mode a valid model
    task contract owns ``requires_plan``.  If that auxiliary contract is
    unavailable, execution starts without a separately generated plan and the
    main execution model retains strategy ownership.
    """
    normalized_planning_policy = str(planning_policy or "auto").lower()
    if normalized_planning_policy == "off":
        return PlanExecutionDecision(False, "user", "计划执行已关闭")
    if normalized_planning_policy == "always":
        return PlanExecutionDecision(True, "user", "已选择总是使用计划执行")

    contract = task_contract if isinstance(task_contract, dict) else {}
    if str(contract.get("source") or "").startswith("model"):
        return PlanExecutionDecision(
            bool(contract.get("requires_plan")),
            "task_contract",
            "模型任务契约已给出 requires_plan",
        )
    return PlanExecutionDecision(
        False,
        "main_execution",
        "未获得可用的模型任务契约计划判断；直接进入主执行，由执行模型选择策略",
    )
