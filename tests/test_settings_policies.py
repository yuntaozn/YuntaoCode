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
    saved = json.loads(settings_path.read_text(encoding="utf-8"))

    assert store.get_planning_policy() == "always"
    assert store.get_confirmation_policy() == "auto"
    assert "execution_mode" not in store.public()
    assert "execution_mode" not in saved


def test_planning_and_confirmation_policies_update_independently(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    public = store.update({
        "planning_policy": "off",
        "confirmation_policy": "conservative",
    })

    assert public["planning_policy"] == "off"
    assert public["confirmation_policy"] == "conservative"
    assert "execution_mode" not in public


def test_legacy_assistant_mode_is_removed_on_migration(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "settings_version": 9,
            "assistant_mode": "coding",
        }),
        encoding="utf-8",
    )

    store = SettingsStore(settings_path)
    saved = json.loads(settings_path.read_text(encoding="utf-8"))

    assert "assistant_mode" not in store.public()
    assert "assistant_mode" not in saved


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


def test_model_can_declare_visual_input_capability(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.update({
        "models": [
            {
                "id": "vision-model",
                "provider": "qwen",
                "supports_multimodal": True,
            }
        ],
    })

    model = store.get_model_config("vision-model")

    assert model["supports_vision"] is True


def test_model_visual_input_defaults_enabled_and_can_be_disabled(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.update({
        "models": [
            {"id": "default-vision", "provider": "qwen"},
            {"id": "text-only", "provider": "qwen", "supports_vision": False},
        ],
    })

    assert store.get_model_config("default-vision")["supports_vision"] is True
    assert store.get_model_config("text-only")["supports_vision"] is False


def test_default_settings_include_volcengine_agent_plan_provider(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")

    provider = store.get_provider("volcengine_agent_plan")
    model = store.get_model_config("ark-code-latest")

    assert provider["base_url"] == "https://ark.cn-beijing.volces.com/api/plan/v3"
    assert provider["chat_path"] == "/chat/completions"
    assert provider["kind"] == "openai"
    assert provider["wire_api"] == "chat_completions"
    assert provider["api_key_required"] is True
    assert model["provider"] == "volcengine_agent_plan"
    assert model["api_model"] == "ark-code-latest"
    assert model["context_limit"] == 256000
    assert model["thinking_mode"] == ""


def test_agent_plan_provider_keeps_openai_compatible_chat_completions(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "settings_version": 10,
            "providers": {
                "volcengine_agent_plan": {
                    "name": "火山 Agent Plan / OpenAI Compatible",
                    "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
                    "api_key": "secret",
                    "api_key_required": True,
                    "chat_path": "/chat/completions",
                    "kind": "openai",
                },
            },
        }),
        encoding="utf-8",
    )

    store = SettingsStore(settings_path)
    provider = store.get_provider("volcengine_agent_plan")
    saved = json.loads(settings_path.read_text(encoding="utf-8"))

    assert provider["chat_path"] == "/chat/completions"
    assert provider["wire_api"] == "chat_completions"
    assert saved["settings_version"] == 12
    assert saved["providers"]["volcengine_agent_plan"]["api_key"] == "secret"


def test_agent_plan_provider_migrates_default_responses_profile_back_to_chat_completions(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "settings_version": 11,
            "providers": {
                "volcengine_agent_plan": {
                    "name": "火山 Agent Plan / OpenAI Compatible",
                    "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
                    "api_key": "secret",
                    "api_key_required": True,
                    "chat_path": "/responses",
                    "kind": "openai",
                    "wire_api": "responses",
                },
            },
        }),
        encoding="utf-8",
    )

    store = SettingsStore(settings_path)
    provider = store.get_provider("volcengine_agent_plan")

    assert provider["chat_path"] == "/chat/completions"
    assert provider["wire_api"] == "chat_completions"


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


def test_request_options_do_not_store_runtime_owned_fields(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    public = store.update({
        "providers": {
            "custom": {
                "name": "Custom",
                "base_url": "http://127.0.0.1:9999/v1",
                "request_options": {
                    "temperature": 0.2,
                    "model": "wrong",
                    "messages": [],
                    "tools": [],
                },
            },
        },
        "models": [
            {
                "id": "custom-model",
                "provider": "custom",
                "request_options": {
                    "top_p": 0.9,
                    "reasoning_effort": "high",
                    "max_tokens": 8192,
                    "enable_thinking": False,
                },
            },
        ],
    })

    assert public["providers"]["custom"]["request_options"] == {"temperature": 0.2}
    assert store.get_model_config("custom-model")["request_options"] == {"top_p": 0.9}


def test_runtime_managed_capabilities_ignore_plugin_disable_setting(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.update_plugin_setting("memory", False)
    store.update_plugin_setting("attachment", False)

    assert store.is_plugin_enabled("memory") is True
    assert store.is_plugin_enabled("attachment") is True


def test_local_integration_settings_are_removed_on_migration(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "settings_version": 7,
            "local_integrations": {
                "open_file_target": "system",
                "open_folder_target": "cursor",
                "custom_open_folder_command": r"C:\Tools\Cursor.exe",
            },
        }),
        encoding="utf-8",
    )

    store = SettingsStore(settings_path)
    saved = json.loads(settings_path.read_text(encoding="utf-8"))

    assert "local_integrations" not in store.public()
    assert "local_integrations" not in saved


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
