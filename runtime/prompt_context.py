from __future__ import annotations

from typing import Any


_CAPABILITY_BOUNDARY_ZH = "\n能力扩展草稿不能作为可信进程内插件执行；注册、启用与权限由 Runtime 校验。"
_CAPABILITY_BOUNDARY_EN = "\nCapability drafts cannot execute as trusted in-process plugins; the Runtime validates registration, enablement, and permissions."


def build_system_prompt(
    *,
    settings: Any,
    mode_config: dict[str, Any],
    workspace_path: str,
    workspace_id: str = "",
    user_message: str = "",
    user_memory: str | None = None,
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
    if str(mode_config.get("prompt_language") or "").lower().startswith("en"):
        return prompt + _CAPABILITY_BOUNDARY_EN
    return prompt + _CAPABILITY_BOUNDARY_ZH
