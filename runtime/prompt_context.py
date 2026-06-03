from __future__ import annotations

from typing import Any


_PLUGIN_DRAFT_BOUNDARY_ZH = """

## 插件草稿边界补充
当前阶段，AI 自建插件草稿只能作为隔离目录中的候选内容；不得创建 runtime.skills.<plugin> Python 模块，不得修改 runtime/skills/__init__.py 来注册工具，也不得把草稿代码作为可信进程内插件执行。用户确认表示进入受控注册/启用流程，不表示允许绕过核心边界。
"""

_PLUGIN_DRAFT_BOUNDARY_EN = """

## Plugin Draft Boundary Addendum
At this stage, AI-built plugin drafts are candidates in isolated directories only. Do not create runtime.skills.<plugin> Python modules, do not modify runtime/skills/__init__.py to register tools, and do not execute draft code as trusted in-process plugin code. User confirmation means entering a controlled registration or enablement flow, not bypassing the core boundary.
"""


def build_system_prompt(
    *,
    settings: Any,
    mode_config: dict[str, Any],
    workspace_path: str,
    user_message: str = "",
    capability_context: str = "",
) -> str:
    prompt = str(mode_config["system_prompt"]).format(
        workspace_path=workspace_path,
        user_memory=settings.get_memory_prompt(user_message=user_message),
    )
    if capability_context:
        prompt += "\n" + capability_context
    if "Capability Extension Rules" in prompt:
        return prompt + _PLUGIN_DRAFT_BOUNDARY_EN
    return prompt + _PLUGIN_DRAFT_BOUNDARY_ZH
