from __future__ import annotations

import json
from pathlib import Path

from runtime.settings_store import SettingsStore


def test_legacy_execution_mode_migrates_to_independent_policies(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "settings_version": 3,
            "execution_mode": "aggressive",
        }),
        encoding="utf-8",
    )

    store = SettingsStore(settings_path)

    assert store.get_planning_policy() == "always"
    assert store.get_confirmation_policy() == "auto"
    assert store.get_execution_mode() == "aggressive"


def test_planning_and_confirmation_policies_update_independently(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    public = store.update({
        "planning_policy": "off",
        "confirmation_policy": "conservative",
    })

    assert public["planning_policy"] == "off"
    assert public["confirmation_policy"] == "conservative"
    assert public["execution_mode"] == "conservative"


def test_any_model_can_declare_output_token_capability(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.update({
        "models": [
            {
                "id": "custom-model",
                "provider": "qwen",
                "max_output_tokens": 32768,
                "output_token_param": "max_tokens",
            }
        ],
    })

    model = store.get_model_config("custom-model")

    assert model["max_output_tokens"] == 32768
    assert model["output_token_param"] == "max_tokens"


def test_invalid_output_token_parameter_is_not_sent(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.update({
        "models": [
            {
                "id": "custom-model",
                "provider": "qwen",
                "max_output_tokens": 32768,
                "output_token_param": "vendor_magic_limit",
            }
        ],
    })

    model = store.get_model_config("custom-model")

    assert model["max_output_tokens"] == 32768
    assert model["output_token_param"] == ""
