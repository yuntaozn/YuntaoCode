"""Unified terminal prompt configuration."""

from __future__ import annotations

from . import i18n


TERMINAL_CONFIG: dict[str, object] = {
    "name": "YuntaoCode",
    "icon": "terminal",
    "description_key": "system_prompt.description",
    "max_rounds": 40,
    "system_prompt_key": "system_prompt.identity",
    "placeholder_key": "system_prompt.placeholder",
}


def get_terminal_config(lang: str = "") -> dict[str, object]:
    """Return the unified terminal configuration with i18n-resolved strings."""
    config = TERMINAL_CONFIG
    resolved = dict(config)
    resolved["system_prompt"] = i18n.t(str(config["system_prompt_key"]), lang)
    resolved["description"] = i18n.t(str(config["description_key"]), lang)
    resolved["placeholder"] = i18n.t(str(config["placeholder_key"]), lang)
    return resolved
