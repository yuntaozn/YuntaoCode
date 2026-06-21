from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from .memory_service import (
    DEFAULT_MEMORY_SETTINGS,
    build_memory_prompt,
    build_memory_prompt_from_store,
    normalize_memory_settings,
    update_memory_settings,
)
from .memory_store import MemoryStore


DEFAULT_SETTINGS: dict[str, Any] = {
    "settings_version": 10,
    "backend_url": "http://127.0.0.1:8088",
    "default_model": "doubao-seed-2-0-pro-260215",
    "access_scope": "project_only",
    "planning_policy": "auto",
    "confirmation_policy": "auto",
    "backups": {
        "enabled": True,
        "keep_rounds": 50,
    },
    "memories": deepcopy(DEFAULT_MEMORY_SETTINGS),
    "providers": {
        "volcengine": {
            "name": "火山方舟",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "",
            "api_key_required": True,
            "chat_path": "/chat/completions",
            "kind": "openai",
        },
        "qwen": {
            "name": "通义千问 / OpenAI Compatible",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "",
            "api_key_required": True,
            "chat_path": "/chat/completions",
            "kind": "openai",
            "request_options": {
                "enable_search": True,
                "search_options": {"search_strategy": "max"},
            },
        },
        "ollama": {
            "name": "Ollama / OpenAI Compatible",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "api_key_required": False,
            "chat_path": "/chat/completions",
            "kind": "openai",
        },
        "vllm": {
            "name": "vLLM / OpenAI Compatible",
            "base_url": "http://127.0.0.1:8000/v1",
            "api_key": "",
            "api_key_required": False,
            "chat_path": "/chat/completions",
            "kind": "openai",
        },
    },
    "models": [
        {
            "id": "doubao-seed-2-0-pro-260215",
            "name": "豆包 Seed 2.0 Pro",
            "provider": "volcengine",
            "context_limit": 256000,
            "supports_tools": True,
            "thinking_mode": "volcengine",
            "supports_reasoning_effort": True,
        },
        {
            "id": "doubao-seed-2-0-code-preview-260215",
            "name": "豆包 Seed 2.0 编程加强版",
            "provider": "volcengine",
            "context_limit": 256000,
            "supports_tools": True,
            "thinking_mode": "volcengine",
            "supports_reasoning_effort": True,
        },
        {
            "id": "doubao-seed-1-6-251015",
            "name": "豆包 Seed 1.6",
            "provider": "volcengine",
            "context_limit": 128000,
            "supports_tools": True,
            "thinking_mode": "volcengine",
        },
        {
            "id": "doubao-seed-1-8-251228",
            "name": "豆包 Seed 1.8",
            "provider": "volcengine",
            "context_limit": 128000,
            "supports_tools": True,
            "thinking_mode": "volcengine",
        },
        {
            "id": "deepseek-v4-flash",
            "name": "DeepSeek V4 Flash",
            "provider": "qwen",
            "context_limit": 1000000,
            "supports_tools": True,
            "thinking_mode": "",
        },
        {
            "id": "qwen3.6-flash",
            "name": "Qwen3.6 Flash",
            "provider": "qwen",
            "context_limit": 983000,
            "supports_tools": True,
            "thinking_mode": "qwen",
            "allow_disable_thinking": False,
        },
        {
            "id": "qwen3.6-max-preview",
            "name": "Qwen3.6 Max Preview",
            "provider": "qwen",
            "context_limit": 1000000,
            "supports_tools": True,
            "thinking_mode": "qwen",
            "allow_disable_thinking": False,
        },
        {
            "id": "qwen3.7-max",
            "name": "Qwen3.7 Max",
            "provider": "qwen",
            "context_limit": 1000000,
            "supports_tools": True,
            "thinking_mode": "qwen",
            "allow_disable_thinking": False,
        },
        {
            "id": "qwen3.7-max-preview",
            "name": "Qwen3.7 Max Preview",
            "provider": "qwen",
            "context_limit": 1000000,
            "supports_tools": True,
            "thinking_mode": "qwen",
            "allow_disable_thinking": False,
        },
    ],
    "plugins": {
        # 插件启用状态：默认全部启用
        "filesystem": {"enabled": True},
        "document": {"enabled": True},
        "code": {"enabled": True},
        "shell": {"enabled": True},
        "git": {"enabled": True},
        "web": {"enabled": True},
    },
}

VALID_ACCESS_SCOPES = {"project_only", "full_local"}
VALID_PLANNING_POLICIES = {"off", "auto", "always"}
VALID_CONFIRMATION_POLICIES = {"conservative", "auto", "aggressive"}
RUNTIME_MANAGED_PLUGIN_IDS = {"attachment", "memory"}


def planning_policy_from_legacy_policy_alias(value: Any) -> str:
    return {
        "conservative": "off",
        "auto": "auto",
        "aggressive": "always",
    }.get(str(value or "").strip().lower(), "auto")


class SettingsStore:
    def __init__(self, settings_path: Path | None = None) -> None:
        self.settings_path = settings_path or default_settings_path()
        self.data_dir = self.settings_path.parent
        self.data_dir.mkdir(parents=True, exist_ok=True)
        loaded = self._load()
        # 初始化时：如果用户配置为空，从 DEFAULT_SETTINGS 复制；否则直接用用户配置
        if not loaded:
            self._settings = deepcopy(DEFAULT_SETTINGS)
        else:
            # 用户配置优先，只合并缺失的顶级键，不要递归合并
            self._settings = deepcopy(loaded)
            for key, default_value in DEFAULT_SETTINGS.items():
                if key not in self._settings:
                    self._settings[key] = deepcopy(default_value)
        self._migrate_settings(loaded)
        # Initialize MemoryStore (independent file, with migration from settings)
        self.memory_store = MemoryStore.migrate_from_settings(
            self.data_dir / "memories.json", self
        )

    def public(self) -> dict[str, Any]:
        providers: dict[str, Any] = {}
        for provider_id, config in self.get_providers().items():
            api_key = config.get("api_key") or ""
            providers[provider_id] = {
                "id": provider_id,
                "name": config.get("name", provider_id),
                "base_url": config.get("base_url", ""),
                "chat_path": config.get("chat_path", "/chat/completions"),
                "kind": config.get("kind", "openai"),
                "api_key_required": bool(config.get("api_key_required", True)),
                "request_options": config.get("request_options") if isinstance(config.get("request_options"), dict) else {},
                "has_api_key": bool(api_key),
                "api_key_hint": mask_key(api_key),
            }
        return {
            "backend_url": self._settings.get("backend_url", DEFAULT_SETTINGS["backend_url"]),
            "default_model": self.get_default_model(),
            "models": self.get_models(),
            "access_scope": self.get_access_scope(),
            "planning_policy": self.get_planning_policy(),
            "confirmation_policy": self.get_confirmation_policy(),
            "backups": self.get_backup_settings(),
            "memories": self.get_memory_settings(),
            "providers": providers,
            "settings_path": str(self.settings_path),
        }

    def _migrate_settings(self, loaded: dict[str, Any]) -> None:
        try:
            version = int(loaded.get("settings_version") or 1) if isinstance(loaded, dict) else 1
        except (TypeError, ValueError):
            version = 1
        if version < 2:
            backups = self._settings.setdefault("backups", {})
            try:
                keep_rounds = int(backups.get("keep_rounds") or 0)
            except (TypeError, ValueError):
                keep_rounds = 0
            if keep_rounds == 5:
                backups["keep_rounds"] = DEFAULT_SETTINGS["backups"]["keep_rounds"]
        if version < 3:
            self._settings["memories"] = normalize_memory_settings(
                self._settings.get("memories", DEFAULT_MEMORY_SETTINGS)
            )
            if not self._settings.get("providers"):
                self._settings["providers"] = deepcopy(DEFAULT_SETTINGS["providers"])
            if not self._settings.get("models"):
                self._settings["models"] = deepcopy(DEFAULT_SETTINGS["models"])
        if version < 4:
            loaded_planning_policy = loaded.get("planning_policy") if isinstance(loaded, dict) else None
            loaded_confirmation_policy = loaded.get("confirmation_policy") if isinstance(loaded, dict) else None
            self._settings["planning_policy"] = (
                str(loaded_planning_policy)
                if loaded_planning_policy in VALID_PLANNING_POLICIES
                else planning_policy_from_legacy_policy_alias(
                    loaded.get("execution_mode") if isinstance(loaded, dict) else None
                )
            )
            self._settings["confirmation_policy"] = (
                str(loaded_confirmation_policy)
                if loaded_confirmation_policy in VALID_CONFIRMATION_POLICIES
                else DEFAULT_SETTINGS["confirmation_policy"]
            )
        if version < 5:
            plugins = self._settings.get("plugins")
            if isinstance(plugins, dict):
                plugins.pop("blender", None)
        if version < 8:
            # One-shot cleanup for the removed local opener customization UI/API.
            self._settings.pop("local_integrations", None)
        if version < 9:
            # One-shot cleanup for the removed public execution_mode alias.
            self._settings.pop("execution_mode", None)
        if version < 10:
            # One-shot cleanup for the removed user-facing assistant mode setting.
            self._settings.pop("assistant_mode", None)
        if version < DEFAULT_SETTINGS["settings_version"]:
            self._settings["settings_version"] = DEFAULT_SETTINGS["settings_version"]
            self._save()

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("backend_url"):
            self._settings["backend_url"] = str(payload["backend_url"]).rstrip("/")
        if payload.get("default_model"):
            self._settings["default_model"] = str(payload["default_model"])
        if payload.get("access_scope"):
            access_scope = str(payload["access_scope"])
            if access_scope in VALID_ACCESS_SCOPES:
                self._settings["access_scope"] = access_scope
        if payload.get("planning_policy"):
            planning_policy = str(payload["planning_policy"])
            if planning_policy in VALID_PLANNING_POLICIES:
                self._settings["planning_policy"] = planning_policy
        if payload.get("confirmation_policy"):
            confirmation_policy = str(payload["confirmation_policy"])
            if confirmation_policy in VALID_CONFIRMATION_POLICIES:
                self._settings["confirmation_policy"] = confirmation_policy
        if isinstance(payload.get("backups"), dict):
            incoming_backups = payload["backups"]
            backups = self._settings.setdefault("backups", {})
            if "enabled" in incoming_backups:
                backups["enabled"] = bool(incoming_backups["enabled"])
            if "keep_rounds" in incoming_backups:
                try:
                    keep_rounds = int(incoming_backups["keep_rounds"])
                except (TypeError, ValueError):
                    keep_rounds = DEFAULT_SETTINGS["backups"]["keep_rounds"]
                backups["keep_rounds"] = max(1, min(keep_rounds, 100))
        if isinstance(payload.get("memories"), dict):
            self._settings["memories"] = update_memory_settings(
                self._settings.get("memories", {}),
                payload["memories"],
            )
        if isinstance(payload.get("providers"), dict):
            current_providers = self._settings.setdefault("providers", {})
            for provider_id, incoming in payload["providers"].items():
                if not isinstance(incoming, dict):
                    continue
                provider_id = normalize_id(provider_id)
                if not provider_id:
                    continue
                target = current_providers.setdefault(provider_id, {})
                if "enabled" in incoming:
                    target["enabled"] = bool(incoming["enabled"])
                if incoming.get("name"):
                    target["name"] = str(incoming["name"]).strip()
                if "base_url" in incoming:
                    target["base_url"] = str(incoming.get("base_url") or "").rstrip("/")
                if "chat_path" in incoming:
                    target["chat_path"] = normalize_chat_path(incoming.get("chat_path"))
                if "kind" in incoming:
                    target["kind"] = str(incoming.get("kind") or "openai").strip() or "openai"
                if "api_key_required" in incoming:
                    target["api_key_required"] = bool(incoming["api_key_required"])
                if isinstance(incoming.get("request_options"), dict):
                    target["request_options"] = incoming["request_options"]
                if "api_key" in incoming and incoming["api_key"]:
                    target["api_key"] = str(incoming["api_key"]).strip()
                if incoming.get("clear_api_key"):
                    target["api_key"] = ""
        if isinstance(payload.get("deleted_provider_ids"), list):
            current_providers = self._settings.setdefault("providers", {})
            for provider_id in payload["deleted_provider_ids"]:
                provider_id = normalize_id(provider_id)
                if provider_id:
                    current_providers.setdefault(provider_id, {})["enabled"] = False

        if isinstance(payload.get("models"), list):
            previous_models = {
                str(model.get("id")): model
                for model in self.get_models(include_disabled=True)
                if model.get("id")
            }
            previous_active_ids = {
                model_id
                for model_id, model in previous_models.items()
                if model.get("enabled", True) is not False
            }
            disabled_ids = {
                model_id
                for model_id, model in previous_models.items()
                if model.get("enabled", True) is False
            }
            incoming_models: list[dict[str, Any]] = []
            incoming_ids: set[str] = set()
            for item in payload["models"]:
                if not isinstance(item, dict):
                    continue
                model = normalize_model_config(item)
                model_id = str(model.get("id") or "")
                if not model_id:
                    continue
                model["enabled"] = model.get("enabled", True) is not False
                incoming_models.append(model)
                incoming_ids.add(model_id)

            explicit_deleted_ids = {
                normalize_id(model_id)
                for model_id in (payload.get("deleted_model_ids") or [])
                if normalize_id(model_id)
            }
            missing_active_ids = previous_active_ids - incoming_ids
            disabled_ids.update(explicit_deleted_ids)
            disabled_ids.update(missing_active_ids)
            disabled_ids.difference_update(incoming_ids)

            stored_models = incoming_models[:]
            for model_id in sorted(disabled_ids):
                marker = deepcopy(previous_models.get(model_id) or {"id": model_id, "name": model_id})
                marker["id"] = model_id
                marker["enabled"] = False
                stored_models.append(marker)
            self._settings["models"] = stored_models
        elif isinstance(payload.get("deleted_model_ids"), list):
            models = {
                str(model["id"]): model
                for model in self.get_models(include_disabled=True)
                if model.get("id")
            }
            for model_id in payload["deleted_model_ids"]:
                model_id = normalize_id(model_id)
                if model_id:
                    item = models.setdefault(model_id, {"id": model_id, "name": model_id})
                    item["enabled"] = False
            self._settings["models"] = list(models.values())

        self._save()
        return self.public()

    def get_provider(self, provider_id: str) -> dict[str, Any]:
        return self.get_providers(include_disabled=True).get(provider_id, {})

    def get_providers(self, *, include_disabled: bool = False) -> dict[str, dict[str, Any]]:
        providers: dict[str, dict[str, Any]] = {}
        configured = self._settings.get("providers", {}) if isinstance(self._settings.get("providers"), dict) else {}
        for provider_id, config in DEFAULT_SETTINGS.get("providers", {}).items():
            merged = merge_settings(config, configured.get(provider_id, {}) if isinstance(configured.get(provider_id), dict) else {})
            if include_disabled or merged.get("enabled", True) is not False:
                providers[provider_id] = merged
        for provider_id, config in configured.items():
            if provider_id in providers or provider_id in DEFAULT_SETTINGS.get("providers", {}):
                continue
            if not isinstance(config, dict):
                continue
            merged = merge_settings(default_provider_config(provider_id), config)
            if include_disabled or merged.get("enabled", True) is not False:
                providers[provider_id] = merged
        return providers

    def get_models(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        models: dict[str, dict[str, Any]] = {}
        for item in DEFAULT_SETTINGS.get("models", []):
            if isinstance(item, dict) and item.get("id"):
                models[str(item["id"])] = normalize_model_config(item)
        for item in self._settings.get("models", []) if isinstance(self._settings.get("models"), list) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            base = models.get(model_id, {"id": model_id})
            models[model_id] = merge_settings(base, normalize_model_config(item))
        return [
            item for item in models.values()
            if include_disabled or item.get("enabled", True) is not False
        ]

    def get_model_config(self, model_id: str) -> dict[str, Any]:
        for model in self.get_models(include_disabled=True):
            if model.get("id") == model_id:
                return model
        return {
            "id": model_id,
            "name": model_id,
            "provider": "qwen",
            "context_limit": 128000,
            "max_output_tokens": 0,
            "output_token_param": "",
            "supports_tools": True,
            "thinking_mode": "",
            "request_options": {},
        }

    def resolve_model(self, model_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        model = self.get_model_config(model_id)
        provider_id = str(model.get("provider") or "qwen")
        provider = self.get_provider(provider_id)
        return model, provider, provider_id

    def get_default_model(self) -> str:
        model_id = str(self._settings.get("default_model") or DEFAULT_SETTINGS["default_model"])
        active_ids = [str(model.get("id")) for model in self.get_models() if model.get("id")]
        if model_id in active_ids:
            return model_id
        return active_ids[0] if active_ids else str(DEFAULT_SETTINGS["default_model"])

    def get_access_scope(self) -> str:
        scope = str(self._settings.get("access_scope") or DEFAULT_SETTINGS["access_scope"])
        return scope if scope in VALID_ACCESS_SCOPES else DEFAULT_SETTINGS["access_scope"]

    def get_planning_policy(self) -> str:
        policy = str(self._settings.get("planning_policy") or "").strip().lower()
        if policy in VALID_PLANNING_POLICIES:
            return policy
        return DEFAULT_SETTINGS["planning_policy"]

    def get_confirmation_policy(self) -> str:
        policy = str(self._settings.get("confirmation_policy") or "").strip().lower()
        return policy if policy in VALID_CONFIRMATION_POLICIES else DEFAULT_SETTINGS["confirmation_policy"]

    def get_backup_settings(self) -> dict[str, Any]:
        backups = merge_settings(
            DEFAULT_SETTINGS["backups"],
            self._settings.get("backups", {}),
        )
        try:
            keep_rounds = int(backups.get("keep_rounds") or DEFAULT_SETTINGS["backups"]["keep_rounds"])
        except (TypeError, ValueError):
            keep_rounds = DEFAULT_SETTINGS["backups"]["keep_rounds"]
        return {
            "enabled": bool(backups.get("enabled", True)),
            "keep_rounds": max(1, min(keep_rounds, 100)),
        }

    def get_memory_settings(self) -> dict[str, Any]:
        return normalize_memory_settings(self._settings.get("memories", {}))

    def get_memory_prompt(self, *, user_message: str = "", workspace_id: str = "") -> str:
        """Build memory prompt with optional relevance filtering."""
        mem_settings = self.get_memory_settings()
        prompt, _ = build_memory_prompt_from_store(
            self.memory_store,
            enabled=mem_settings.get("enabled", True),
            max_active=mem_settings.get("max_active", 30),
            user_message=user_message,
            workspace_id=workspace_id,
        )
        return prompt

    def is_memory_auto_extract_enabled(self) -> bool:
        mem_settings = self.get_memory_settings()
        return bool(mem_settings.get("enabled", True) and mem_settings.get("auto_extract", True))
    
    def get_plugin_settings(self) -> dict[str, Any]:
        """获取插件设置"""
        return merge_settings(
            DEFAULT_SETTINGS.get("plugins", {}),
            self._settings.get("plugins", {}),
        )
    
    def is_plugin_enabled(self, plugin_id: str) -> bool:
        if plugin_id in RUNTIME_MANAGED_PLUGIN_IDS:
            return True
        config = self.get_plugin_settings().get(plugin_id)
        if not isinstance(config, dict):
            return True
        return bool(config.get("enabled", True))

    def is_tool_enabled(self, tool_id: str) -> bool:
        plugin_id = str(tool_id or "").split(".", 1)[0]
        return self.is_plugin_enabled(plugin_id)

    def update_plugin_setting(self, plugin_id: str, enabled: bool) -> None:
        """更新单个插件的设置"""
        plugins = self._settings.setdefault("plugins", {})
        plugin_config = plugins.setdefault(plugin_id, {})
        plugin_config["enabled"] = bool(enabled)
        self._save()

    def _load(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _save(self) -> None:
        self.settings_path.write_text(
            json.dumps(self._settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def default_settings_path() -> Path:
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "YuntaoCode" / "settings.json"
        return Path.home() / "AppData" / "Local" / "YuntaoCode" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "YuntaoCode" / "settings.json"
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "YuntaoCode" / "settings.json"
    return Path.home() / ".config" / "YuntaoCode" / "settings.json"


def normalize_id(value: Any) -> str:
    return str(value or "").strip()


def normalize_chat_path(value: Any) -> str:
    path = str(value or "/chat/completions").strip() or "/chat/completions"
    return path if path.startswith("/") else f"/{path}"


def default_provider_config(provider_id: str) -> dict[str, Any]:
    return {
        "name": provider_id,
        "base_url": "",
        "api_key": "",
        "api_key_required": True,
        "chat_path": "/chat/completions",
        "kind": "openai",
        "request_options": {},
        "enabled": True,
    }


def normalize_model_config(value: dict[str, Any]) -> dict[str, Any]:
    model_id = normalize_id(value.get("id") or value.get("model"))
    if not model_id:
        return {}
    try:
        context_limit = int(value.get("context_limit") or value.get("max_context_tokens") or 128000)
    except (TypeError, ValueError):
        context_limit = 128000
    try:
        max_output_tokens = int(value.get("max_output_tokens") or 0)
    except (TypeError, ValueError):
        max_output_tokens = 0
    output_token_param = str(value.get("output_token_param") or "").strip()
    if output_token_param not in {"", "max_tokens", "max_completion_tokens", "max_output_tokens"}:
        output_token_param = ""
    model = {
        "id": model_id,
        "name": str(value.get("name") or value.get("label") or model_id).strip(),
        "provider": normalize_id(value.get("provider") or value.get("provider_id") or "qwen"),
        "api_model": normalize_id(value.get("api_model") or value.get("model_name") or model_id),
        "context_limit": max(4096, min(context_limit, 2_000_000)),
        "max_output_tokens": max(0, min(max_output_tokens, 1_000_000)),
        "output_token_param": output_token_param,
        "supports_tools": bool(value.get("supports_tools", True)),
        "supports_stream": bool(value.get("supports_stream", True)),
        "thinking_mode": str(value.get("thinking_mode") or "").strip(),
        "allow_disable_thinking": bool(value.get("allow_disable_thinking", False)),
        "supports_reasoning_effort": bool(value.get("supports_reasoning_effort", False)),
        "request_options": value.get("request_options") if isinstance(value.get("request_options"), dict) else {},
        "enabled": bool(value.get("enabled", True)),
    }
    return model


def merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_settings(result[key], value)
        else:
            result[key] = value
    return result


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
