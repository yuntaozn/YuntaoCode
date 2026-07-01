from __future__ import annotations

from typing import Any


_PLUGIN_DRAFT_BOUNDARY_ZH = """

## 能力包草稿边界补充
当前阶段，AI 自建能力应优先沉淀为方法型能力包（提示词、步骤、反例、验证清单），写入用户数据目录下的 capability-packs/items/<pack-id>/。只有确实需要新执行能力时，才创建工具适配器草稿。不得创建 runtime.skills.<plugin> Python 模块，不得修改 runtime/skills/__init__.py 来注册工具，也不得把草稿代码作为可信进程内插件执行。用户确认表示进入受控注册/启用流程，不表示允许绕过核心边界。不要在当前工作区或开源仓库根目录创建 ai-plugins/ 或 capability-packs/；如果没有专用草稿创建工具或明确可写的用户数据目录，请先说明边界并询问用户。

## 临时产物边界补充
一次性分析脚本、中间 JSON、探测输出和不应提交的临时文件，应优先使用 filesystem.write_temp_file 写入任务临时目录；运行这些临时脚本时，shell.run_command 可使用 cwd="task_temp" 或 use_task_temp=true。不要把临时脚本写到用户项目目录，除非用户明确要求保留该脚本作为项目产物。
"""

_PLUGIN_DRAFT_BOUNDARY_EN = """

## Capability Pack Draft Boundary Addendum
At this stage, AI-built capabilities should first become method-skill capability packs: prompts, steps, counterexamples, and verification checklists under capability-packs/items/<pack-id>/ in the user data directory. Create tool adapter drafts only when new execution capability is truly required. Do not create runtime.skills.<plugin> Python modules, do not modify runtime/skills/__init__.py to register tools, and do not execute draft code as trusted in-process plugin code. User confirmation means entering a controlled registration or enablement flow, not bypassing the core boundary. Do not create ai-plugins/ or capability-packs/ in the current workspace or open-source repository root; if there is no dedicated draft creation tool or explicit writable user-data directory, explain the boundary and ask the user first.

## Temporary Artifact Boundary Addendum
One-off analysis scripts, intermediate JSON, probe outputs, and files that should not be committed should use filesystem.write_temp_file in the task temp directory. To run those temporary scripts, shell.run_command may use cwd="task_temp" or use_task_temp=true. Do not write temporary scripts into the user's project directory unless the user explicitly asks to keep the script as a project artifact.
"""

_WEB_ACCESS_CAPABILITY_ADDENDUM = """

## Web Access Capability Addendum
When web.* tools are available and the user asks to view, read, inspect,
summarize, or analyze a public website/URL, try web.extract_text first. Use
web.render_page when the page depends on JavaScript rendering or ordinary HTTP
text extraction is insufficient. Do not claim that websites cannot be accessed
until the appropriate web tool has been tried or the capability is unavailable.
If the tool fails, explain the actual tool failure instead of guessing.
When the user asks to collect website materials/assets for redesign or archival,
use web.collect_site_assets instead of generating crawler scripts or writing
large gathered content with filesystem.write_file. When the user asks to save a
webpage as a screenshot or PDF, use web.capture_page.
"""

_PREVIEW_CAPABILITY_ADDENDUM = """

## Preview Capability Addendum
When preview.* tools are available and the task involves HTML, CSS,
JavaScript, UI layout, visual appearance, local pages, localhost, screenshots,
or whether a rendered result looks correct, use preview tools as visual verification evidence. For a local HTML file inside the workspace, prefer
preview.capture_local_html after the write. For a running local or public URL,
use preview.capture_url. Treat console errors, page errors, and failed requests
as evidence for the model to decide whether to repair, continue, or report the
remaining risk. If no preview was captured, keep visual correctness marked as
unobserved instead of treating source-only inspection as visual verification.
Local HTML preview is served through a short-lived 127.0.0.1 static server by
default so module scripts, import maps, relative assets, and Three.js pages are
closer to real browser execution than file:// loading.
"""

_TEXT_WRITE_ROUTE_ADDENDUM = """

## Text Write Route Addendum
Use one text/code write capability for HTML, CSS, JavaScript, Python, Markdown,
JSON, configuration files, and similar text artifacts. Choose the route by
artifact shape, not by file extension:

1. Existing local file, small targeted change: read the relevant snippet, then
   use code.edit_file, code.replace_text, or code.apply_patch.
2. New or rewritten complete text/code artifact with non-trivial length,
   multiple sections, UI/CSS/JS, long prose, reports, novels, translated
   documents, or any risk of exceeding one model output: default to
   filesystem.create_text_draft first, append complete bounded chunks in
   multiple filesystem.append_text_chunk calls, inspect when useful, then write
   once with filesystem.finalize_text_file.
3. New tiny complete file only: filesystem.write_file with path and content is
   acceptable when the full content is comfortably small and can fit in one
   complete tool call.

Do not use draft chunks when a precise edit or small patch is enough, and do
not use filesystem.write_file or a large filesystem.apply_changes payload as
the first route for large complete artifacts. Plan chunk boundaries before the
first write call; do not wait for truncation before switching to draft chunks.
Never retry oversized filesystem.write_file/apply_changes calls after
truncation.
"""

def build_system_prompt(
    *,
    settings: Any,
    mode_config: dict[str, Any],
    workspace_path: str,
    workspace_id: str = "",
    user_message: str = "",
    capability_context: str = "",
) -> str:
    prompt = str(mode_config["system_prompt"]).format(
        workspace_path=workspace_path,
        user_memory=settings.get_memory_prompt(user_message=user_message, workspace_id=workspace_id),
    )
    if capability_context:
        prompt += "\n" + capability_context
        if _has_web_capability_context(capability_context):
            prompt += _WEB_ACCESS_CAPABILITY_ADDENDUM
        if _has_preview_capability_context(capability_context):
            prompt += _PREVIEW_CAPABILITY_ADDENDUM
        if _has_text_write_context(capability_context):
            prompt += _TEXT_WRITE_ROUTE_ADDENDUM
    if "Capability Extension Rules" in prompt:
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
