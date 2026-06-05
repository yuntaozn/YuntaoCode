from __future__ import annotations

from pathlib import Path
from typing import Any


AI_PLUGIN_DRAFT_WRITE_TOOLS = {
    "filesystem.write_file",
    "code.apply_patch",
    "code.edit_file",
    "code.replace_text",
}


def ai_plugin_draft_workspace_guard_message(
    *,
    tool_id: str,
    input_data: dict[str, Any],
    workspace_path: str | None,
    data_dir: Path | str | None = None,
) -> str:
    if not workspace_path:
        return ""

    if tool_id in AI_PLUGIN_DRAFT_WRITE_TOOLS:
        for target in _target_paths(tool_id, input_data):
            if target and _path_is_workspace_ai_plugin_draft(target, workspace_path):
                return _ai_plugin_draft_message(data_dir)

    if tool_id == "shell.run_command" and _shell_mentions_workspace_ai_plugins(input_data, workspace_path):
        return _ai_plugin_draft_message(data_dir)

    return ""


def _target_paths(tool_id: str, input_data: dict[str, Any]) -> list[str]:
    if tool_id == "code.apply_patch":
        targets: list[str] = []
        for line in str(input_data.get("patch") or "").splitlines():
            for prefix in ("*** Add File: ", "*** Update File: "):
                if line.startswith(prefix):
                    target = line[len(prefix):].strip()
                    if target:
                        targets.append(target)
        return targets
    target = str(
        input_data.get("path")
        or input_data.get("output_path")
        or input_data.get("file_path")
        or ""
    ).strip()
    return [target] if target else []


def _path_is_workspace_ai_plugin_draft(raw_path: str, workspace_path: str) -> bool:
    try:
        workspace_root = Path(workspace_path).resolve()
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        candidate = candidate.resolve()
        candidate.relative_to((workspace_root / "ai-plugins").resolve())
        return True
    except (OSError, ValueError):
        return False


def _shell_mentions_workspace_ai_plugins(input_data: dict[str, Any], workspace_path: str) -> bool:
    command_text = " ".join(
        str(part)
        for part in [
            input_data.get("command") or "",
            *(_normalize_args(input_data.get("args"))),
            input_data.get("cwd") or "",
        ]
        if part is not None
    )
    lowered = command_text.lower().replace("/", "\\")
    if "ai-plugins" not in lowered:
        return False
    try:
        workspace_root = str(Path(workspace_path).resolve()).lower().replace("/", "\\")
    except OSError:
        workspace_root = str(workspace_path).lower().replace("/", "\\")
    return "ai-plugins" in lowered and (workspace_root in lowered or not Path(command_text).is_absolute())


def _normalize_args(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _ai_plugin_draft_message(data_dir: Path | str | None) -> str:
    data_dir_text = str(data_dir or "").strip()
    expected = (
        f"{data_dir_text}\\ai-plugins\\<plugin-id>"
        if data_dir_text
        else "<YuntaoCode data dir>\\ai-plugins\\<plugin-id>"
    )
    return (
        "AI 自建插件草稿不能写入当前工作区的 ai-plugins/，因为当前工作区可能是开源仓库，"
        "会造成误提交和开发节奏污染。当前阶段请不要注册或启用该草稿；"
        f"只允许在受控草稿位置 {expected} 中创建候选内容，"
        "或等待专用插件草稿创建/注册工具。"
    )
