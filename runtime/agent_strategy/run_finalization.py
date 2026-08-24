"""模型完成审查所需的 Run 事实入口。"""

from __future__ import annotations

from dataclasses import dataclass


NO_TARGET_DELIVERABLE = "no_target_deliverable"
NO_TASK_EVIDENCE = "no_task_evidence"
COMPLETION_OWNED_BY_MODEL = "completion_owned_by_model"


@dataclass(frozen=True)
class CompletionReviewGate:
    """当前 Run 事实的可观察审查状态。

    此辅助对象不检查验证是否充分，不选择工具，不停止模型策略，也不决定任务成功；
    只报告是否有新任务证据可供模型自行完成审查。"""

    action: str
    reason: str = ""


def build_completion_review_gate(
    *,
    requires_target_deliverable: bool,
    has_target_deliverable: bool,
    has_task_evidence: bool,
) -> CompletionReviewGate:
    """返回当前任务证据是否应交由模型审查。

    Runtime 只报告缺少目标或任务证据的事实，不再插入完成审查轮次。模型在主
    执行循环中自行决定是否继续使用工具以及何时回答；验证缺口进入最终证据包，
    不作为隐藏循环控制。"""

    if not requires_target_deliverable:
        if not has_task_evidence:
            return CompletionReviewGate(
                NO_TASK_EVIDENCE,
                "task evidence not observed",
            )
        return CompletionReviewGate(
            COMPLETION_OWNED_BY_MODEL,
            "completion remains with the main execution model",
        )

    if requires_target_deliverable and not has_target_deliverable:
        return CompletionReviewGate(
            NO_TARGET_DELIVERABLE,
            "target deliverable not observed",
        )
    return CompletionReviewGate(
        COMPLETION_OWNED_BY_MODEL,
        "completion remains with the main execution model",
    )
