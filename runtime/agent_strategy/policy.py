"""Routing and planning policy for the agent runtime.

This module is the first stop for request-level decisions.  It keeps cheap,
deterministic policy decisions out of the model loop and reserves model-based
planning judgment for genuinely ambiguous requests.
"""

from __future__ import annotations

from dataclasses import dataclass

from .classifiers import looks_like_simple_code_change
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


PROJECT_ANALYSIS_TERMS: tuple[str, ...] = (
    "分析当前项目",
    "当前工作区",
    "项目结构",
    "架构",
    "审查",
    "审核",
    "汇总",
    "对比",
    "整理",
    "生成报告",
    "风险清单",
    "整改清单",
    "多份",
    "全部",
    "完整",
    "计划",
)

COMPLEX_EXECUTION_TERMS: tuple[str, ...] = (
    "实现",
    "重构",
    "修复",
    "测试",
    "验证",
    "方案",
    "迁移",
    "批量",
    "跨文件",
    "多文件",
)

SIMPLE_READ_ONLY_TERMS: tuple[str, ...] = (
    "解释",
    "说明",
    "为什么",
    "是什么",
    "怎么",
    "如何",
    "建议",
    "思路",
)


def resolve_profile(
    task_intent: str,
    mode: str | None,
    *,
    code_change_intent: bool = False,
) -> AgentProfile:
    return profile_for_task_intent(
        task_intent,
        mode,
        code_change_intent=code_change_intent,
    )


def deterministic_plan_gate(
    content: str,
    task_intent: str,
    mode: str | None,
    plan_mode: str,
    *,
    profile: AgentProfile | None = None,
) -> PlanGateDecision:
    """Return a deterministic plan decision or ask the caller to use the model.

    ``enabled is None`` means the request is ambiguous enough that the model
    plan judge can be used.  Everything else is decided without another model
    round.
    """
    normalized_plan_mode = str(plan_mode or "auto").lower()
    if normalized_plan_mode == "off":
        return PlanGateDecision(False, "user", "计划执行已关闭")
    if normalized_plan_mode == "always":
        return PlanGateDecision(True, "user", "已选择总是使用计划执行")

    text = content.lower().strip()
    profile = profile or resolve_profile(task_intent, mode)

    if task_intent == "answer_only" or profile.id == "chat":
        return PlanGateDecision(False, "policy", "简单问答直接回复")
    if looks_like_simple_code_change(content):
        return PlanGateDecision(False, "policy", "简单代码/界面修改直接执行")
    if task_intent in {"document_export", "paper_workflow"}:
        return PlanGateDecision(True, "policy", "文档或论文工作流需要可展示的执行计划")
    if any(term in text for term in PROJECT_ANALYSIS_TERMS):
        return PlanGateDecision(True, "policy", "项目级分析需要分步收集证据")
    if any(term in text for term in COMPLEX_EXECUTION_TERMS) and len(text) > 40:
        return PlanGateDecision(True, "policy", "复杂执行任务需要计划和阶段推进")
    if task_intent == "read_only_analysis" and len(text) < 80:
        if any(term in text for term in SIMPLE_READ_ONLY_TERMS):
            return PlanGateDecision(False, "policy", "轻量分析直接回复或按需读取")
    if len(text) > 160:
        return PlanGateDecision(True, "policy", "长请求默认使用计划约束执行")
    return PlanGateDecision(None, "model", "需要模型判断是否计划执行")


def heuristic_plan_execution(content: str, mode: str | None) -> bool:
    """Fallback heuristic used when model plan judgment is unavailable."""
    text = content.lower()
    simple_terms = ("你好", "介绍下你自己", "你是谁", "是什么", "为什么", "解释一下")
    if len(text) < 24 and any(term in text for term in simple_terms):
        return False
    if mode == "paper":
        paper_plan_terms = (
            "文献综述",
            "系统综述",
            "研究设计",
            "研究问题",
            "论文大纲",
            "论文初稿",
            "审稿意见",
            "审稿回复",
            "投稿",
            "摘要",
            "引言",
            "相关工作",
            "方法论",
            "质量检查",
            "引用",
            "参考文献",
        )
        return len(text) > 80 or any(term in text for term in paper_plan_terms)
    if looks_like_simple_code_change(content):
        return False
    if any(term in text for term in PROJECT_ANALYSIS_TERMS + COMPLEX_EXECUTION_TERMS):
        return True
    return len(text) > 120
