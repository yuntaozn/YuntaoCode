"""将模型声明的任务语义映射到内部 profile，不插入执行阶段。"""

from __future__ import annotations


from .profiles import AgentProfile, profile_for_task_intent


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
