"""Agent Runtime 的路由与计划策略。

计划语义只有一个来源：任务契约模型。本模块只负责把模型声明与用户显式的
计划设置合并，不再运行第二条任务分类路径。
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
    """解析执行前是否生成计划，不额外调用一次模型。

    用户显式设置始终优先。自动模式下，由有效模型任务契约中的
    ``requires_plan`` 决定；辅助契约不可用时，不单独生成计划，直接进入主执行，
    继续由执行模型决定策略。
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
