from __future__ import annotations

from typing import Any


_PLUGIN_DRAFT_BOUNDARY_ZH = """

## 能力包草稿边界补充
当前阶段，AI 自建能力应优先沉淀为方法型能力包（提示词、步骤、反例、验证清单），写入用户数据目录下的 capability-packs/items/<pack-id>/。只有确实需要新执行能力时，才创建工具适配器草稿。不得创建 runtime.skills.<plugin> Python 模块，不得修改 runtime/skills/__init__.py 来注册工具，也不得把草稿代码作为可信进程内插件执行。用户确认表示进入受控注册/启用流程，不表示允许绕过核心边界。不要在当前工作区或开源仓库根目录创建 ai-plugins/ 或 capability-packs/；如果没有专用草稿创建工具或明确可写的用户数据目录，请先说明边界并询问用户。

## 临时产物边界补充
一次性分析脚本、中间 JSON、探测输出和不应提交的临时文件，适合使用 filesystem.write_temp_file 写入任务临时目录；运行这些临时脚本时，shell.run_command 可使用 cwd="task_temp" 或 use_task_temp=true。不要把临时脚本写到用户项目目录，除非用户明确要求保留该脚本作为项目产物。
"""

_PLUGIN_DRAFT_BOUNDARY_EN = """

## Capability Pack Draft Boundary Addendum
At this stage, AI-built capabilities should first become method-skill capability packs: prompts, steps, counterexamples, and verification checklists under capability-packs/items/<pack-id>/ in the user data directory. Create tool adapter drafts only when new execution capability is truly required. Do not create runtime.skills.<plugin> Python modules, do not modify runtime/skills/__init__.py to register tools, and do not execute draft code as trusted in-process plugin code. User confirmation means entering a controlled registration or enablement flow, not bypassing the core boundary. Do not create ai-plugins/ or capability-packs/ in the current workspace or open-source repository root; if there is no dedicated draft creation tool or explicit writable user-data directory, explain the boundary and ask the user first.

## Temporary Artifact Boundary Addendum
One-off analysis scripts, intermediate JSON, probe outputs, and files that should not be committed should use filesystem.write_temp_file in the task temp directory. To run those temporary scripts, shell.run_command may use cwd="task_temp" or use_task_temp=true. Do not write temporary scripts into the user's project directory unless the user explicitly asks to keep the script as a project artifact.
"""

_WEB_ACCESS_CAPABILITY_ADDENDUM = """

## Web Capability Facts
The visible web.* tools can fetch text, render JavaScript pages, collect site
assets, and capture screenshots or PDFs. Their exact descriptions and schemas
define the available operations. A failed call is evidence about that route,
not proof that all network access is unavailable. Choose any visible capability
that fits the goal and report the actual result.
"""

_PREVIEW_CAPABILITY_ADDENDUM = """

## Preview Capability Facts
The visible preview.* tools can capture local HTML, workspace files, and URLs,
or run bounded page interactions. Results may include screenshots, DOM text,
console/page/network diagnostics, interaction traces, and visual evidence.
Local HTML capture uses a short-lived 127.0.0.1 server. Source inspection alone
does not create visual evidence; when no capture exists, visual correctness
remains unobserved. The model decides whether and how these facts are needed.
"""

_TEXT_WRITE_ROUTE_ADDENDUM = """

## Text Write Capability Facts
The visible write tools support targeted edits, complete file writes, patches,
and draft/chunk/finalize workflows. Large single-call arguments can be truncated
by a model or provider before the runtime receives valid JSON; draft tools keep
bounded chunks as Run artifacts before finalization. Targeted edit tools avoid
rewriting unrelated content. These are route tradeoffs, not a prescribed
workflow: the model chooses the method from the artifact and observed results.
"""

def build_system_prompt(
    *,
    settings: Any,
    mode_config: dict[str, Any],
    workspace_path: str,
    workspace_id: str = "",
    user_message: str = "",
    user_memory: str | None = None,
    capability_context: str = "",
) -> str:
    memory_prompt = (
        settings.get_memory_prompt(
            user_message=user_message,
            workspace_id=workspace_id,
        )
        if user_memory is None
        else str(user_memory)
    )
    prompt = str(mode_config["system_prompt"]).format(
        workspace_path=workspace_path,
        user_memory=memory_prompt,
    )
    if capability_context:
        prompt += "\n" + capability_context
        if _has_web_capability_context(capability_context):
            prompt += _WEB_ACCESS_CAPABILITY_ADDENDUM
        if _has_preview_capability_context(capability_context):
            prompt += _PREVIEW_CAPABILITY_ADDENDUM
        if _has_text_write_context(capability_context):
            prompt += _TEXT_WRITE_ROUTE_ADDENDUM
    if str(mode_config.get("prompt_language") or "").lower().startswith("en"):
        return prompt + _PLUGIN_DRAFT_BOUNDARY_EN
    return prompt + _PLUGIN_DRAFT_BOUNDARY_ZH


def _has_web_capability_context(capability_context: str) -> bool:
    text = str(capability_context or "")
    return "web." in text or "web.network_fetch" in text


def _has_preview_capability_context(capability_context: str) -> bool:
    text = str(capability_context or "")
    return "preview." in text or "preview.visual_debug" in text


def _has_text_write_context(capability_context: str) -> bool:
    text = str(capability_context or "")
    return (
        "code.text_write" in text
        or "filesystem.text_artifact_draft" in text
        or "filesystem.finalize_text_file" in text
        or "filesystem.write_file" in text
        or "code.edit_file" in text
        or "code.apply_patch" in text
    )
