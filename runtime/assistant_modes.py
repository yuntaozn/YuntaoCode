"""Unified assistant profile for the local intelligent terminal.

The UI exposes a single terminal. Internally, runtime code may still infer
task profiles such as code editing, document export, or paper research, but
those profiles are execution hints rather than user-facing assistant modes.
"""

from __future__ import annotations

from typing import Any

from . import i18n


UNIFIED_MODE = "terminal"
LEGACY_MODE_ALIASES = {
    "document": UNIFIED_MODE,
    "coding": UNIFIED_MODE,
    "paper": UNIFIED_MODE,
}


MODES: dict[str, dict[str, Any]] = {
    UNIFIED_MODE: {
        "name": "YuntaoCode",
        "icon": "terminal",
        "description_key": "system_prompt.description",
        "max_rounds": 24,
        "system_prompt_key": "system_prompt.identity",
        "placeholder_key": "system_prompt.placeholder",
    },
}

DEFAULT_MODE = UNIFIED_MODE


def normalize_mode(mode: str | None) -> str:
    value = str(mode or "").strip()
    if value in MODES:
        return value
    return LEGACY_MODE_ALIASES.get(value, DEFAULT_MODE)


def get_mode_config(mode: str | None, lang: str = "") -> dict[str, Any]:
    """Return the unified mode configuration with i18n-resolved strings."""
    config = MODES[normalize_mode(mode)]
    resolved = dict(config)
    # Resolve i18n keys into actual text
    resolved["system_prompt"] = i18n.t(config["system_prompt_key"], lang)
    resolved["description"] = i18n.t(config["description_key"], lang)
    resolved["placeholder"] = i18n.t(config["placeholder_key"], lang)
    return resolved


def list_modes_public(lang: str = "") -> list[dict[str, Any]]:
    """Return the single user-facing terminal mode."""
    result = []
    for mode_id, config in MODES.items():
        result.append({
            "id": mode_id,
            "name": config["name"],
            "icon": config["icon"],
            "description": i18n.t(config["description_key"], lang),
            "placeholder": i18n.t(config["placeholder_key"], lang),
        })
    return result
