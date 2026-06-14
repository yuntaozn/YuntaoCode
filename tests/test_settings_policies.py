from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.settings_store import SettingsStore, default_settings_path


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


def test_runtime_managed_capabilities_ignore_plugin_disable_setting(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.update_plugin_setting("memory", False)
    store.update_plugin_setting("attachment", False)

    assert store.is_plugin_enabled("memory") is True
    assert store.is_plugin_enabled("attachment") is True


def test_default_settings_path_uses_windows_local_app_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("runtime.settings_store.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\demo\AppData\Local")

    assert default_settings_path() == Path(r"C:\Users\demo\AppData\Local") / "YuntaoCode" / "settings.json"


def test_default_settings_path_uses_windows_home_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("runtime.settings_store.sys.platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_settings_path() == tmp_path / "AppData" / "Local" / "YuntaoCode" / "settings.json"


def test_default_settings_path_uses_macos_application_support(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("runtime.settings_store.sys.platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_settings_path() == tmp_path / "Library" / "Application Support" / "YuntaoCode" / "settings.json"


def test_default_settings_path_uses_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("runtime.settings_store.sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert default_settings_path() == tmp_path / "config" / "YuntaoCode" / "settings.json"


def test_default_settings_path_uses_linux_config_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("runtime.settings_store.sys.platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_settings_path() == tmp_path / ".config" / "YuntaoCode" / "settings.json"
