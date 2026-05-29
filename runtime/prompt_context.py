from __future__ import annotations

from typing import Any


def build_system_prompt(
    *,
    settings: Any,
    mode_config: dict[str, Any],
    workspace_path: str,
    user_message: str = "",
) -> str:
    return str(mode_config["system_prompt"]).format(
        workspace_path=workspace_path,
        user_memory=settings.get_memory_prompt(user_message=user_message),
    )
