"""模型完成审查所需的 Run 事实入口。"""

from __future__ import annotations

from dataclasses import dataclass


NO_TARGET_DELIVERABLE = "no_target_deliverable"
NO_TASK_EVIDENCE = "no_task_evidence"
COMPLETION_REVIEW = "completion_review"
EVIDENCE_ALREADY_REVIEWED = "evidence_already_reviewed"


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
    has_unreviewed_evidence: bool,
) -> CompletionReviewGate:
    """返回当前任务证据是否应交由模型审查。

    写入与外部状态任务仍以目标交付物证据作为入口。只读分析和答案证据任务没有
    可观察的文件或外部对象，因此成功的证据收集工具使用同一审查边界。验证缺口
    有意不作为入口条件：它们会进入证据包，由模型决定验证、修复、询问用户，
    或带明确限制结束。"""

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
