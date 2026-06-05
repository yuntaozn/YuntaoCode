from __future__ import annotations

from typing import Any


_PLUGIN_DRAFT_BOUNDARY_ZH = """

## 插件草稿边界补充
当前阶段，AI 自建插件草稿只能作为隔离目录中的候选内容；不得创建 runtime.skills.<plugin> Python 模块，不得修改 runtime/skills/__init__.py 来注册工具，也不得把草稿代码作为可信进程内插件执行。用户确认表示进入受控注册/启用流程，不表示允许绕过核心边界。不要在当前工作区或开源仓库根目录创建 ai-plugins/；如果没有专用草稿创建工具或明确可写的用户数据目录，请先说明边界并询问用户。

## 临时产物边界补充
一次性分析脚本、中间 JSON、探测输出和不应提交的临时文件，应优先使用 filesystem.write_temp_file 写入任务临时目录；运行这些临时脚本时，shell.run_command 可使用 cwd="task_temp" 或 use_task_temp=true。不要把临时脚本写到用户项目目录，除非用户明确要求保留该脚本作为项目产物。
"""

_PLUGIN_DRAFT_BOUNDARY_EN = """

## Plugin Draft Boundary Addendum
At this stage, AI-built plugin drafts are candidates in isolated directories only. Do not create runtime.skills.<plugin> Python modules, do not modify runtime/skills/__init__.py to register tools, and do not execute draft code as trusted in-process plugin code. User confirmation means entering a controlled registration or enablement flow, not bypassing the core boundary. Do not create ai-plugins/ in the current workspace or open-source repository root; if there is no dedicated draft creation tool or explicit writable user-data directory, explain the boundary and ask the user first.

## Temporary Artifact Boundary Addendum
One-off analysis scripts, intermediate JSON, probe outputs, and files that should not be committed should use filesystem.write_temp_file in the task temp directory. To run those temporary scripts, shell.run_command may use cwd="task_temp" or use_task_temp=true. Do not write temporary scripts into the user's project directory unless the user explicitly asks to keep the script as a project artifact.
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
