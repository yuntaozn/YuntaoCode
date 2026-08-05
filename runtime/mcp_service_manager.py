from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .mcp_protocol import McpStdioSession, McpToolDefinition, normalize_mcp_tool_result
from .tool_registry import ToolRegistry, ToolSpec

MCP_SERVICE_SCHEMA_VERSION = "mcp_service.v8"
SUPPORTED_TRANSPORTS = {"stdio", "streamable_http", "legacy_sse"}
TRANSPORT_ALIASES = {
    "http": "streamable_http",
    "sse": "legacy_sse",
    "streamable-http": "streamable_http",
}
SUPPORTED_ACTIONS = {"check", "probe", "start", "stop", "restart"}
SERVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MAX_LOG_LINES = 120
MAX_LOG_MESSAGE_CHARS = 1600
MAX_TOOL_DIAGNOSTICS = 120
MAX_TOOL_DIAGNOSTIC_ERROR_CHARS = 500
MAX_PROBE_TOOLS = 8
MAX_PROBE_MESSAGE_CHARS = 220
PERMISSION_VALUES = {
    "filesystem": {"none", "workspace", "full_local"},
    "network": {"false", "confirm_each", "allow"},
    "external_state": {"false", "confirm_each", "allow"},
    "arbitrary_code": {"false", "confirm_each", "allow"},
}
BLENDER_TIMEOUT_UPGRADES = {
    "get_scene_info": {10.0: 25.0},
    "get_object_info": {10.0: 25.0},
    "get_viewport_screenshot": {20.0: 60.0},
    "execute_blender_code": {60.0: 120.0},
}

DEFAULT_MCP_SERVICES: tuple[dict[str, Any], ...] = ({
    "id": "blender",
    "name": "Blender MCP",
    "description": "Example MCP connection for controlling Blender through the BlenderMCP add-on.",
    "enabled": False,
    "installation": {
        "kind": "package_runner",
        "package": "blender-mcp",
        "managed": False,
    },
    "transport": {
        "type": "stdio",
        "command": "uvx",
        "args": ["blender-mcp"],
        "env": {
            "BLENDER_MCP_DISABLE_TELEMETRY": "1",
        },
    },
    "timeouts": {
        "call": 30.0,
    },
    "prerequisites": [
        {
            "id": "blender-addon",
            "label": "Blender Add-on",
            "kind": "tcp",
            "host": "127.0.0.1",
            "port": 9876,
        },
        {
            "id": "uvx",
            "label": "uvx package runner",
            "kind": "executable",
            "command": "uvx",
        },
    ],
    "permissions": {
        "filesystem": "workspace",
        "network": "confirm_each",
        "external_state": "confirm_each",
        "arbitrary_code": "confirm_each",
    },
    "tool_policies": {
        "get_scene_info": {
            "risk": "read_only",
            "roles": ["evidence", "verification"],
            "verification_strength": "weak",
            "call_timeout": 25.0,
        },
        "get_object_info": {
            "risk": "read_only",
            "roles": ["evidence", "verification"],
            "verification_strength": "standard",
            "call_timeout": 25.0,
        },
        "get_viewport_screenshot": {
            "risk": "read_only",
            "roles": ["verification"],
            "artifacts": ["screenshot"],
            "verification_strength": "standard",
            "call_timeout": 60.0,
        },
        "execute_blender_code": {
            "risk": "state_change",
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
            "call_timeout": 120.0,
        },
        "get_polyhaven_categories": {"risk": "read_only"},
        "search_polyhaven_assets": {"risk": "read_only"},
        "get_polyhaven_status": {"risk": "read_only"},
        "get_hyper3d_status": {"risk": "read_only"},
        "poll_rodin_job_status": {"risk": "read_only"},
        "get_hunyuan3d_status": {"risk": "read_only"},
        "poll_hunyuan_job_status": {"risk": "read_only"},
        "get_sketchfab_status": {"risk": "read_only"},
        "search_sketchfab_models": {"risk": "read_only"},
        "get_sketchfab_model_preview": {"risk": "read_only"},
        "download_polyhaven_asset": {"risk": "state_change", "effects": ["external_state_change"]},
        "download_sketchfab_model": {"risk": "state_change", "effects": ["external_state_change"]},
        "set_texture": {"risk": "state_change", "effects": ["external_state_change"]},
        "generate_hyper3d_model_via_text": {
            "risk": "state_change",
            "effects": ["external_state_change"],
        },
        "generate_hyper3d_model_via_images": {
            "risk": "state_change",
            "effects": ["external_state_change"],
        },
        "generate_hunyuan3d_model": {
            "risk": "state_change",
            "effects": ["external_state_change"],
        },
        "import_generated_asset": {"risk": "state_change", "effects": ["external_state_change"]},
        "import_generated_asset_hunyuan": {
            "risk": "state_change",
            "effects": ["external_state_change"],
        },
    },
},)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tool_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
    return normalized or "tool"


def _service_id_from_capability_id(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("mcp."):
        return ""
    service_id = text.removeprefix("mcp.").strip()
    return service_id if SERVICE_ID_PATTERN.fullmatch(service_id) else ""


def _normalize_timeout_seconds(value: Any, default: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return default
    if timeout <= 0:
        return default
    return min(timeout, 3600.0)


def _normalize_tool_diagnostics(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    diagnostics: dict[str, dict[str, Any]] = {}
    for remote_name, item in value.items():
        name = str(remote_name or "").strip()
        if not name or not isinstance(item, dict):
            continue
        health = str(item.get("health") or "").strip().lower()
        if health not in {"degraded", "unknown"}:
            continue
        last_error = str(item.get("last_error") or "").strip()
        updated_at = str(item.get("updated_at") or "").strip()
        try:
            failure_count = int(item.get("failure_count") or 1)
        except (TypeError, ValueError):
            failure_count = 1
        diagnostics[name] = {
            "health": health,
            "last_error": last_error[:MAX_TOOL_DIAGNOSTIC_ERROR_CHARS],
            "updated_at": updated_at,
            "failure_count": max(1, min(failure_count, 9999)),
        }
        if len(diagnostics) >= MAX_TOOL_DIAGNOSTICS:
            break
    return diagnostics


def _merge_seeded_service(default: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(default)
    for key, value in existing.items():
        # 即使磁盘上原本不存在该字段，旧版规范化配置也会包含空列表。
        # 因此需要保留新引入的种子前置条件。
        if key == "prerequisites" and not value and merged.get(key):
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged_value = {**merged[key], **value}
            if key == "transport":
                default_env = merged[key].get("env")
                existing_env = value.get("env")
                if isinstance(default_env, dict) and isinstance(existing_env, dict):
                    merged_value["env"] = {**default_env, **existing_env}
            if key == "tool_policies":
                merged_value = deepcopy(merged[key])
                for tool_name, policy in value.items():
                    default_policy = merged_value.get(tool_name)
                    if isinstance(default_policy, dict) and isinstance(policy, dict):
                        merged_value[tool_name] = {**default_policy, **policy}
                    else:
                        merged_value[tool_name] = policy
                if str(merged.get("id") or "") == "blender":
                    _upgrade_blender_seed_timeouts(merged_value)
            merged[key] = merged_value
        else:
            merged[key] = value
    return merged


def _upgrade_blender_seed_timeouts(tool_policies: dict[str, Any]) -> None:
    for tool_name, upgrades in BLENDER_TIMEOUT_UPGRADES.items():
        policy = tool_policies.get(tool_name)
        if not isinstance(policy, dict):
            continue
        try:
            current = float(policy.get("call_timeout"))
        except (TypeError, ValueError):
            continue
        upgraded = upgrades.get(current)
        if upgraded is not None:
            policy["call_timeout"] = upgraded


def normalize_mcp_service(value: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = existing or {}
    service_id = str(value.get("id") or current.get("id") or "").strip()
    if not SERVICE_ID_PATTERN.fullmatch(service_id):
        raise ValueError("service id must use letters, numbers, dot, underscore, or hyphen")

    incoming_transport = value.get("transport")
    if incoming_transport is None:
        incoming_transport = current.get("transport", {})
    if not isinstance(incoming_transport, dict):
        raise ValueError("transport must be an object")
    transport_type = str(incoming_transport.get("type") or "stdio").strip().lower()
    transport_type = TRANSPORT_ALIASES.get(transport_type, transport_type)
    if transport_type not in SUPPORTED_TRANSPORTS:
        raise ValueError(f"unsupported MCP transport: {transport_type}")

    transport: dict[str, Any] = {"type": transport_type}
    if transport_type == "stdio":
        command = str(incoming_transport.get("command") or "").strip()
        if not command:
            raise ValueError("stdio transport requires command")
        raw_args = incoming_transport.get("args") or []
        if not isinstance(raw_args, list):
            raise ValueError("stdio transport args must be an array")
        raw_env = incoming_transport.get("env")
        if raw_env is None:
            raw_env = (current.get("transport") or {}).get("env", {})
        if not isinstance(raw_env, dict):
            raise ValueError("stdio transport env must be an object")
        transport.update({
            "command": command,
            "args": [str(item) for item in raw_args],
            "cwd": str(incoming_transport.get("cwd") or "").strip(),
            "env": {str(key): str(item) for key, item in raw_env.items() if str(key).strip()},
        })
    else:
        url = str(incoming_transport.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"{transport_type} transport requires an http(s) url")
        raw_headers = incoming_transport.get("headers")
        if raw_headers is None:
            raw_headers = (current.get("transport") or {}).get("headers", {})
        if not isinstance(raw_headers, dict):
            raise ValueError(f"{transport_type} transport headers must be an object")
        transport.update({
            "url": url,
            "health_url": str(incoming_transport.get("health_url") or "").strip(),
            "headers": {
                str(key): str(item)
                for key, item in raw_headers.items()
                if str(key).strip()
            },
        })

    incoming_timeouts = value.get("timeouts")
    if incoming_timeouts is None:
        incoming_timeouts = current.get("timeouts", {})
    if not isinstance(incoming_timeouts, dict):
        incoming_timeouts = {}
    timeouts = {
        "call": _normalize_timeout_seconds(incoming_timeouts.get("call"), 30.0),
    }

    lifecycle = value.get("lifecycle")
    if lifecycle is None:
        lifecycle = current.get("lifecycle", {})
    if not isinstance(lifecycle, dict):
        lifecycle = {}
    permissions = value.get("permissions")
    if permissions is None:
        permissions = current.get("permissions", {})
    if not isinstance(permissions, dict):
        permissions = {}
    normalized_permissions = {
        "filesystem": str(permissions.get("filesystem") or "workspace"),
        "network": str(permissions.get("network") or "confirm_each"),
        "external_state": str(permissions.get("external_state") or "confirm_each"),
        "arbitrary_code": str(permissions.get("arbitrary_code") or "confirm_each"),
    }
    for permission, allowed_values in PERMISSION_VALUES.items():
        if normalized_permissions[permission] not in allowed_values:
            raise ValueError(
                f"unsupported {permission} permission: {normalized_permissions[permission]}"
            )

    incoming_installation = value.get("installation")
    if incoming_installation is None:
        incoming_installation = current.get("installation", {})
    if not isinstance(incoming_installation, dict):
        incoming_installation = {}
    default_installation_kind = "local_command" if transport_type == "stdio" else "remote_endpoint"
    installation_kind = str(incoming_installation.get("kind") or default_installation_kind).strip()
    incoming_tool_policies = value.get("tool_policies")
    if incoming_tool_policies is None:
        incoming_tool_policies = current.get("tool_policies", {})
    if not isinstance(incoming_tool_policies, dict):
        incoming_tool_policies = {}
    tool_policies: dict[str, dict[str, Any]] = {}
    for tool_name, policy in incoming_tool_policies.items():
        if not isinstance(policy, dict):
            continue
        normalized_policy: dict[str, Any] = {}
        risk = str(policy.get("risk") or "").strip()
        if risk in {"read_only", "state_change", "unknown"}:
            normalized_policy["risk"] = risk
        for key in ("effects", "roles", "artifacts"):
            values = policy.get(key)
            if isinstance(values, list):
                normalized_policy[key] = [
                    str(item).strip()
                    for item in values
                    if str(item).strip()
                ][:12]
        verification_strength = str(policy.get("verification_strength") or "").strip().lower()
        if verification_strength in {"none", "weak", "standard", "strong"}:
            normalized_policy["verification_strength"] = verification_strength
        if "call_timeout" in policy:
            normalized_policy["call_timeout"] = _normalize_timeout_seconds(
                policy.get("call_timeout"),
                timeouts["call"],
            )
        if normalized_policy:
            tool_policies[str(tool_name)] = normalized_policy
    incoming_prerequisites = value.get("prerequisites")
    if incoming_prerequisites is None:
        incoming_prerequisites = current.get("prerequisites", [])
    if not isinstance(incoming_prerequisites, list):
        incoming_prerequisites = []
    prerequisites: list[dict[str, Any]] = []
    for item in incoming_prerequisites:
        if not isinstance(item, dict):
            continue
        prerequisite_id = str(item.get("id") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not prerequisite_id or kind not in {"tcp", "executable"}:
            continue
        prerequisite: dict[str, Any] = {
            "id": prerequisite_id,
            "label": str(item.get("label") or prerequisite_id).strip(),
            "kind": kind,
        }
        if kind == "tcp":
            host = str(item.get("host") or "127.0.0.1").strip()
            try:
                port = int(item.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            if not host or port < 1 or port > 65535:
                continue
            prerequisite.update({"host": host, "port": port})
        else:
            command = str(item.get("command") or "").strip()
            if not command:
                continue
            prerequisite["command"] = command
        prerequisites.append(prerequisite)

    incoming_tool_diagnostics = value.get("tool_diagnostics")
    if incoming_tool_diagnostics is None:
        incoming_tool_diagnostics = current.get("tool_diagnostics", {})

    return {
        "schema_version": MCP_SERVICE_SCHEMA_VERSION,
        "id": service_id,
        "name": str(value.get("name") or current.get("name") or service_id).strip() or service_id,
        "description": str(value.get("description") or current.get("description") or "").strip(),
        "enabled": bool(value.get("enabled", current.get("enabled", False))),
        "installation": {
            "kind": installation_kind,
            "package": str(incoming_installation.get("package") or "").strip(),
            "managed": bool(incoming_installation.get("managed", False)),
        },
        "transport": transport,
        "timeouts": timeouts,
        "lifecycle": {
            "auto_start": bool(lifecycle.get("auto_start", False)),
            "restart_policy": "manual",
        },
        "permissions": normalized_permissions,
        "tool_policies": tool_policies,
        "tool_diagnostics": _normalize_tool_diagnostics(incoming_tool_diagnostics),
        "prerequisites": prerequisites,
    }


def public_mcp_service(config: dict[str, Any], runtime: "McpServiceRuntime | None" = None) -> dict[str, Any]:
    transport = dict(config.get("transport") or {})
    env = transport.pop("env", {})
    headers = transport.pop("headers", {})
    transport["env_keys"] = sorted(str(key) for key in env)
    transport["header_keys"] = sorted(str(key) for key in headers)
    raw_state = runtime.state if runtime else ("stopped" if config.get("enabled") else "disabled")
    process_running = bool(runtime and runtime.process and runtime.process.returncode is None)
    protocol_connected = bool(runtime and runtime.protocol_connected)
    capability_bindings = list(runtime.capability_bindings) if runtime else []
    degraded_bindings = [
        binding
        for binding in capability_bindings
        if str(binding.get("health") or "available") != "available"
    ]
    state = _public_session_state(config, raw_state, process_running, protocol_connected)
    issue_code = _mcp_session_issue_code(config, state, process_running, protocol_connected)
    if not issue_code and degraded_bindings:
        issue_code = "tool_degraded"
    tool_health_state = (
        "unavailable"
        if not protocol_connected
        else "degraded"
        if degraded_bindings
        else "available"
        if capability_bindings
        else "unknown"
    )
    tool_health = {
        "state": tool_health_state,
        "healthy": tool_health_state == "available",
        "degraded_count": len(degraded_bindings),
        "degraded_tool_ids": [
            str(binding.get("tool_id") or "")
            for binding in degraded_bindings
            if str(binding.get("tool_id") or "")
        ],
        "message": _mcp_tool_health_message(tool_health_state, degraded_bindings),
    }
    status = {
        "state": state,
        "raw_state": raw_state,
        "message": runtime.message if runtime else "",
        "pid": runtime.process.pid if runtime and runtime.process else None,
        "started_at": runtime.started_at if runtime else "",
        "checked_at": runtime.checked_at if runtime else "",
        "logs": list(runtime.logs) if runtime else [],
        "tool_ids": list(runtime.tool_ids) if runtime else [],
        "process_running": process_running,
        "protocol_connected": protocol_connected,
        "requires_attention": bool(issue_code),
        "issue_code": issue_code,
        "recommended_action": _mcp_session_recommended_action(issue_code),
        "tool_roundtrip_healthy": tool_health["healthy"],
        "tool_health": tool_health,
        "tool_health_state": tool_health_state,
        "degraded_tool_count": len(degraded_bindings),
        "protocol_version": runtime.session.protocol_version if runtime and runtime.session else "",
        "server_info": dict(runtime.session.server_info) if runtime and runtime.session else {},
        "prerequisites": list(runtime.prerequisite_checks) if runtime else [],
        "last_probe_at": runtime.last_probe_at if runtime else "",
        "probe_results": list(runtime.probe_results) if runtime else [],
        "probe_candidate_count": (
            len(_probe_candidate_bindings(capability_bindings))
            if capability_bindings
            else 0
        ),
    }
    definition = {
        key: config.get(key)
        for key in (
            "schema_version",
            "id",
            "name",
            "description",
            "enabled",
            "timeouts",
            "lifecycle",
            "permissions",
        )
    }
    return {
        **config,
        "transport": transport,
        "server_definition": definition,
        "connection_profile": transport,
        "session": status,
        "status": status,
        "capability_bindings": capability_bindings,
    }


def _mcp_tool_health_message(state: str, degraded_bindings: list[dict[str, Any]]) -> str:
    if state == "available":
        return "All discovered tools are healthy."
    if state == "degraded":
        first = degraded_bindings[0] if degraded_bindings else {}
        name = str(first.get("remote_name") or first.get("tool_id") or "tool")
        error = str(first.get("last_error") or "last call failed")
        if len(error) > 180:
            error = f"{error[:180]}..."
        return f"{len(degraded_bindings)} tool(s) degraded; {name}: {error}"
    if state == "unavailable":
        return "MCP protocol is not connected."
    return "No successful tool roundtrip has been observed yet."


def _public_session_state(
    config: dict[str, Any],
    raw_state: str,
    process_running: bool,
    protocol_connected: bool,
) -> str:
    if not config.get("enabled"):
        return "disabled"
    transport = config.get("transport") if isinstance(config.get("transport"), dict) else {}
    if transport.get("type") == "stdio" and process_running and not protocol_connected:
        return "protocol_disconnected"
    return raw_state or "stopped"


def _mcp_session_issue_code(
    config: dict[str, Any],
    state: str,
    process_running: bool,
    protocol_connected: bool,
) -> str:
    if not config.get("enabled"):
        return "service_disabled"
    transport = config.get("transport") if isinstance(config.get("transport"), dict) else {}
    if transport.get("type") == "stdio" and process_running and not protocol_connected:
        return "protocol_disconnected"
    if state in {"failed", "degraded"}:
        return f"service_{state}"
    if state == "stopped":
        return "service_stopped"
    if transport.get("type") in {"streamable_http", "legacy_sse"} and not protocol_connected and state != "reachable":
        return "endpoint_unreachable"
    return ""


def _mcp_session_recommended_action(issue_code: str) -> str:
    if issue_code == "service_disabled":
        return "enable"
    if issue_code in {"protocol_disconnected", "service_failed", "service_degraded", "tool_degraded"}:
        return "restart"
    if issue_code == "service_stopped":
        return "start"
    if issue_code == "endpoint_unreachable":
        return "check"
    return ""


def _has_external_state_policy(config: dict[str, Any]) -> bool:
    policies = config.get("tool_policies") if isinstance(config.get("tool_policies"), dict) else {}
    for policy in policies.values():
        if not isinstance(policy, dict):
            continue
        effects = policy.get("effects") if isinstance(policy.get("effects"), list) else []
        if "external_state_change" in {str(item) for item in effects}:
            return True
    return False


def _probe_candidate_bindings(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        if str(binding.get("risk") or "") != "read_only":
            continue
        required_fields = binding.get("required_input_fields")
        if isinstance(required_fields, list) and required_fields:
            continue
        roles = {str(item) for item in binding.get("roles") or []}
        artifacts = {str(item) for item in binding.get("artifacts") or []}
        verification_strength = str(binding.get("verification_strength") or "")
        health = str(binding.get("health") or "available")
        if (
            roles & {"evidence", "verification"}
            or artifacts
            or verification_strength in {"weak", "standard", "strong"}
            or health != "available"
        ):
            candidates.append(binding)
    return candidates


def _required_input_fields(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    return [str(item).strip() for item in required if str(item).strip()]


def _truncate_probe_message(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= MAX_PROBE_MESSAGE_CHARS:
        return text
    omitted = len(text) - MAX_PROBE_MESSAGE_CHARS
    return f"{text[:MAX_PROBE_MESSAGE_CHARS]} ... [{omitted} chars omitted]"


@dataclass
class McpServiceRuntime:
    state: str = "stopped"
    message: str = ""
    process: asyncio.subprocess.Process | None = None
    started_at: str = ""
    checked_at: str = ""
    logs: list[dict[str, str]] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    protocol_connected: bool = False
    session: McpStdioSession | None = None
    capability_bindings: list[dict[str, Any]] = field(default_factory=list)
    prerequisite_checks: list[dict[str, Any]] = field(default_factory=list)
    last_probe_at: str = ""
    probe_results: list[dict[str, Any]] = field(default_factory=list)
    watch_task: asyncio.Task[None] | None = None
    stderr_task: asyncio.Task[None] | None = None


class McpServiceManager:
    """管理 MCP 服务配置以及进程、连接生命周期。

    协议发现与工具调用有意分离。仅进程正在运行并不代表协议已连接；
    必须由 MCP 适配器调用 ``mark_connected`` 后才报告为协议已连接。"""

    def __init__(self, path: Path, *, registry: ToolRegistry | None = None) -> None:
        self.path = path
        self.secrets_path = path.with_name("mcp-service-secrets.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stored_schema_version = self._stored_schema_version()
        self.registry = registry
        self._secrets = self._load_secrets()
        self._configs = self._load()
        self._runtime: dict[str, McpServiceRuntime] = {}
        if stored_schema_version != MCP_SERVICE_SCHEMA_VERSION:
            for value in DEFAULT_MCP_SERVICES:
                service_id = str(value.get("id") or "")
                existing = self._configs.get(service_id)
                self._configs[service_id] = normalize_mcp_service(
                    _merge_seeded_service(value, existing) if existing else value
                )
            self._save()

    def list_public(self) -> list[dict[str, Any]]:
        return [
            public_mcp_service(config, self._runtime.get(service_id))
            for service_id, config in sorted(self._configs.items())
        ]

    def capability_issues(self) -> list[dict[str, Any]]:
        """返回供任务预检使用的紧凑 MCP 能力就绪问题。

        此处有意避开日志和密钥。Task Runtime 只需知道已配置 MCP 能力
        当前是否可用，以及应通过什么操作恢复。"""
        issues: list[dict[str, Any]] = []
        for service_id, config in sorted(self._configs.items()):
            if not _has_external_state_policy(config):
                continue
            public = public_mcp_service(config, self._runtime.get(service_id))
            status = public.get("status") if isinstance(public.get("status"), dict) else {}
            degraded_bindings = [
                binding
                for binding in public.get("capability_bindings") or []
                if isinstance(binding, dict)
                and str(binding.get("health") or "available") != "available"
            ]
            if bool(status.get("protocol_connected")) and public.get("capability_bindings") and not degraded_bindings:
                continue
            issue_code = str(status.get("issue_code") or "capability_unavailable")
            state = str(status.get("state") or "")
            message = str(status.get("message") or "").strip()
            name = str(config.get("name") or service_id)
            if degraded_bindings:
                for binding in degraded_bindings[:6]:
                    tool_id = str(binding.get("tool_id") or "")
                    remote_name = str(binding.get("remote_name") or tool_id or "tool")
                    last_error = str(binding.get("last_error") or "recent call failed")
                    issues.append({
                        "code": "tool_degraded",
                        "source_type": "mcp",
                        "source_id": service_id,
                        "capability_id": f"mcp.{service_id}",
                        "tool_id": tool_id,
                        "remote_name": remote_name,
                        "name": name,
                        "state": state,
                        "message": (
                            f"MCP service {name} is connected, but tool {remote_name} is degraded: "
                            f"{last_error}. Prefer a small roundtrip test, restart the MCP service, "
                            "or choose another safe strategy before relying on this tool."
                        ),
                        "recommended_action": "restart",
                    })
                continue
            if issue_code == "protocol_disconnected":
                reason = (
                    f"MCP service {name} is running, but the MCP protocol is not connected; "
                    "restart the service from the MCP Services page."
                )
            elif issue_code == "service_disabled":
                reason = f"MCP service {name} is disabled; enable and start it before retrying."
            elif issue_code == "service_stopped":
                reason = f"MCP service {name} is stopped; start it before retrying."
            elif message:
                reason = f"MCP service {name} is unavailable: {message}"
            else:
                reason = f"MCP service {name} is unavailable for this run."
            issues.append({
                "code": issue_code,
                "source_type": "mcp",
                "source_id": service_id,
                "capability_id": f"mcp.{service_id}",
                "name": name,
                "state": state,
                "message": reason,
                "recommended_action": str(status.get("recommended_action") or ""),
            })
        return issues

    def tool_runtime_metadata(self, tool_id: str, *, source_id: str = "") -> dict[str, Any]:
        """返回已注册工具的实时 MCP 绑定健康信息。

        这些元数据只供工具和能力快照参考，不决定模型能否调用工具；
        可用性仍取决于服务、协议连接和明确的权限门禁。"""
        normalized_tool_id = str(tool_id or "").strip()
        if not normalized_tool_id:
            return {}
        candidate_services = [source_id] if source_id else list(self._runtime)
        for service_id in candidate_services:
            runtime = self._runtime.get(str(service_id or ""))
            if not runtime:
                continue
            for binding in runtime.capability_bindings:
                if str(binding.get("tool_id") or "") != normalized_tool_id:
                    continue
                return {
                    "tool_health": str(binding.get("health") or "available"),
                    "tool_last_error": str(binding.get("last_error") or ""),
                    "remote_name": str(binding.get("remote_name") or ""),
                    "call_timeout": binding.get("call_timeout"),
                }
        return {}

    def get_public(self, service_id: str) -> dict[str, Any]:
        return public_mcp_service(self.get_config(service_id), self._runtime.get(service_id))

    def get_config(self, service_id: str) -> dict[str, Any]:
        try:
            return self._configs[service_id]
        except KeyError as exc:
            raise KeyError(f"unknown MCP service: {service_id}") from exc

    def upsert(self, value: dict[str, Any], *, service_id: str = "") -> dict[str, Any]:
        requested_id = str(service_id or value.get("id") or "").strip()
        existing = self._configs.get(requested_id)
        payload = dict(value)
        if service_id:
            payload["id"] = service_id
        config = normalize_mcp_service(payload, existing=existing)
        if service_id and config["id"] != service_id:
            raise ValueError("service id cannot be changed")
        self._configs[config["id"]] = config
        runtime = self._runtime.get(config["id"])
        if runtime and not config["enabled"] and runtime.process is None:
            runtime.state = "disabled"
        self._save()
        return self.get_public(config["id"])

    def delete(self, service_id: str) -> None:
        runtime = self._runtime.get(service_id)
        if runtime and (
            (runtime.process and runtime.process.returncode is None)
            or runtime.protocol_connected
        ):
            raise RuntimeError("stop the MCP service before deleting it")
        self.get_config(service_id)
        self._configs.pop(service_id, None)
        self._secrets.pop(service_id, None)
        self._runtime.pop(service_id, None)
        if self.registry is not None:
            self.registry.unregister_source(source_type="mcp", source_id=service_id)
        self._save()

    async def action(self, service_id: str, action: str) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in SUPPORTED_ACTIONS:
            raise ValueError(f"unsupported MCP service action: {normalized_action}")
        if normalized_action == "check":
            await self.check(service_id)
        elif normalized_action == "probe":
            await self.probe(service_id)
        elif normalized_action == "start":
            await self.start(service_id)
        elif normalized_action == "stop":
            await self.stop(service_id)
        else:
            await self.stop(service_id)
            await self.start(service_id)
        return self.get_public(service_id)

    async def start_auto_services(self) -> list[dict[str, Any]]:
        """启动已启用且明确选择自动启动的服务。

        启动采用尽力而为方式：损坏的可选 MCP 服务应只让对应能力降级，
        不能阻止本地 Runtime 打开。"""
        results: list[dict[str, Any]] = []
        for service_id, config in sorted(self._configs.items()):
            lifecycle = config.get("lifecycle") if isinstance(config.get("lifecycle"), dict) else {}
            if not config.get("enabled") or not lifecycle.get("auto_start"):
                continue
            try:
                await self.start(service_id)
            except Exception as exc:
                runtime = self._runtime_for(service_id)
                runtime.state = "failed"
                runtime.message = f"auto-start failed: {exc}"
                self._append_log(runtime, "error", runtime.message)
            results.append(self.get_public(service_id))
        return results

    async def start_capability_services(
        self,
        capability_ids: list[str],
        *,
        require_auto_start: bool = True,
    ) -> list[dict[str, Any]]:
        """尽力启动任务所指向的 MCP 服务。

        这是 ``start_auto_services`` 的按需版本。它不扩大模型权限，也不强制策略；
        只是在模型收到最终工具快照前，让被明确指向且已启用的 MCP Provider 可用。"""
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for capability_id in capability_ids:
            service_id = _service_id_from_capability_id(capability_id)
            if not service_id or service_id in seen or service_id not in self._configs:
                continue
            seen.add(service_id)
            config = self._configs[service_id]
            lifecycle = config.get("lifecycle") if isinstance(config.get("lifecycle"), dict) else {}
            if require_auto_start and not lifecycle.get("auto_start"):
                continue
            if not config.get("enabled"):
                continue
            public = public_mcp_service(config, self._runtime.get(service_id))
            status = public.get("status") if isinstance(public.get("status"), dict) else {}
            if bool(status.get("protocol_connected")):
                continue
            try:
                await self.start(service_id)
                result_status = "started"
                message = "MCP service started for targeted task capability."
            except Exception as exc:
                result_status = "failed"
                message = str(exc)
            results.append({
                "service_id": service_id,
                "capability_id": f"mcp.{service_id}",
                "status": result_status,
                "message": message,
            })
        return results

    async def start(self, service_id: str) -> None:
        config = self.get_config(service_id)
        if not config.get("enabled"):
            raise RuntimeError("enable the MCP service before starting it")
        runtime = self._runtime_for(service_id)
        if runtime.process and runtime.process.returncode is None:
            if runtime.protocol_connected:
                await self.check(service_id)
            else:
                runtime.state = "protocol_disconnected"
                runtime.message = (
                    "MCP process is running but the protocol is not connected; "
                    "restart the service before using its tools"
                )
                self._append_log(runtime, "error", runtime.message)
                raise RuntimeError(runtime.message)
            return
        transport = config["transport"]
        if transport["type"] != "stdio":
            await self.check(service_id)
            return

        runtime.prerequisite_checks = await self._check_prerequisites(config)
        missing_prerequisites = [
            item for item in runtime.prerequisite_checks
            if not item.get("ready")
        ]
        if missing_prerequisites:
            labels = ", ".join(str(item.get("label") or item.get("id") or "") for item in missing_prerequisites)
            runtime.state = "failed"
            runtime.message = f"MCP prerequisites are not ready: {labels}"
            self._append_log(runtime, "error", runtime.message)
            raise RuntimeError(runtime.message)

        runtime.state = "starting"
        runtime.message = "starting MCP stdio process"
        self._append_log(runtime, "info", runtime.message)
        env = os.environ.copy()
        env.update(transport.get("env") or {})
        cwd = transport.get("cwd") or None
        if cwd and not Path(cwd).is_dir():
            runtime.state = "failed"
            runtime.message = f"working directory does not exist: {cwd}"
            self._append_log(runtime, "error", runtime.message)
            raise RuntimeError(runtime.message)
        try:
            command = self._resolve_executable(transport["command"])
            if not command:
                raise FileNotFoundError(f"executable not found: {transport['command']}")
            runtime.process = await asyncio.create_subprocess_exec(
                command,
                *transport.get("args", []),
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
        except Exception as exc:
            runtime.state = "failed"
            runtime.message = f"failed to start MCP service: {exc}"
            self._append_log(runtime, "error", runtime.message)
            raise RuntimeError(runtime.message) from exc
        runtime.started_at = _now_iso()
        runtime.state = "running"
        runtime.message = "process running; starting MCP handshake"
        self._append_log(runtime, "info", runtime.message)
        runtime.watch_task = asyncio.create_task(self._watch_process(service_id, runtime.process))
        runtime.stderr_task = asyncio.create_task(self._read_stderr(service_id, runtime.process))
        await self._connect_stdio(service_id)

    async def stop(self, service_id: str) -> None:
        self.get_config(service_id)
        runtime = self._runtime_for(service_id)
        process = runtime.process
        await self._disconnect_session(service_id, "MCP protocol disconnected")
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        runtime.process = None
        runtime.state = "stopped" if self._configs[service_id].get("enabled") else "disabled"
        runtime.message = "service stopped"
        self._append_log(runtime, "info", runtime.message)

    async def check(self, service_id: str) -> None:
        config = self.get_config(service_id)
        runtime = self._runtime_for(service_id)
        runtime.checked_at = _now_iso()
        runtime.prerequisite_checks = await self._check_prerequisites(config)
        if not config.get("enabled"):
            runtime.state = "disabled"
            ready_count = sum(1 for item in runtime.prerequisite_checks if item.get("ready"))
            total_count = len(runtime.prerequisite_checks)
            runtime.message = (
                f"MCP connection disabled; prerequisites ready {ready_count}/{total_count}"
                if total_count
                else "MCP connection disabled"
            )
            return
        transport = config["transport"]
        if transport["type"] == "stdio":
            if runtime.process and runtime.process.returncode is None:
                runtime.state = "connected" if runtime.protocol_connected else "protocol_disconnected"
                runtime.message = (
                    "MCP protocol connected"
                    if runtime.protocol_connected
                    else "process running; MCP protocol is not connected; restart the service"
                )
            elif runtime.process and runtime.process.returncode is not None:
                runtime.state = "failed"
                runtime.message = f"process exited with code {runtime.process.returncode}"
            else:
                runtime.state = "stopped"
                runtime.message = "service not started"
            return
        url = transport.get("health_url") or transport.get("url")
        headers = transport.get("headers") or {}
        try:
            async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
            runtime.state = "reachable" if response.status_code < 500 else "degraded"
            runtime.message = f"endpoint responded with HTTP {response.status_code}"
        except Exception as exc:
            runtime.state = "failed"
            runtime.message = f"endpoint check failed: {exc}"
        self._append_log(runtime, "info" if runtime.state == "reachable" else "error", runtime.message)

    async def probe(self, service_id: str, *, limit: int = MAX_PROBE_TOOLS) -> list[dict[str, Any]]:
        """对可观察的 MCP 能力执行小型只读工具探测。

        探测有意与检查和启动分离。由于它可能调用 MCP 工具，所以只选择无需
        必填输入且角色属于证据、验证、产物或此前已降级的只读工具。探测结果
        只是能力快照的参考事实，绝不注销或阻止工具。"""
        self.get_config(service_id)
        runtime = self._runtime_for(service_id)
        runtime.checked_at = _now_iso()
        if not runtime.protocol_connected or runtime.session is None:
            await self.check(service_id)
        if not runtime.protocol_connected or runtime.session is None:
            raise RuntimeError("MCP protocol is not connected; start the service before probing tools")

        candidates = _probe_candidate_bindings(runtime.capability_bindings)
        if limit > 0:
            candidates = candidates[:limit]
        results: list[dict[str, Any]] = []
        for binding in candidates:
            remote_name = str(binding.get("remote_name") or "").strip()
            tool_id = str(binding.get("tool_id") or "").strip()
            if not remote_name:
                continue
            output = await self.call_tool(service_id, remote_name, {})
            error = str(output.get("message") or output.get("content") or "").strip() if output.get("error") else ""
            content = str(output.get("content") or output.get("message") or "").strip()
            results.append({
                "tool_id": tool_id,
                "remote_name": remote_name,
                "status": "failure" if output.get("error") else "success",
                "message": _truncate_probe_message(error or content),
                "checked_at": _now_iso(),
            })

        runtime.last_probe_at = _now_iso()
        runtime.probe_results = results
        runtime.message = (
            f"MCP tool probe completed; {sum(1 for item in results if item['status'] == 'success')}/"
            f"{len(results)} probe candidate(s) succeeded"
            if results
            else "MCP tool probe completed; no safe no-argument probe candidates"
        )
        self._append_log(runtime, "info", runtime.message)
        return results

    async def _check_prerequisites(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in config.get("prerequisites") or []:
            kind = str(item.get("kind") or "")
            result = {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or item.get("id") or ""),
                "kind": kind,
                "ready": False,
                "message": "",
            }
            if kind == "executable":
                command = str(item.get("command") or "")
                path = self._resolve_executable(command)
                result["ready"] = bool(path)
                result["message"] = path or f"executable not found: {command}"
            elif kind == "tcp":
                host = str(item.get("host") or "127.0.0.1")
                port = int(item.get("port") or 0)
                try:
                    _reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port),
                        timeout=1.5,
                    )
                    writer.close()
                    await writer.wait_closed()
                    result["ready"] = True
                    result["message"] = f"{host}:{port} is reachable"
                except Exception as exc:
                    result["message"] = f"{host}:{port} is not reachable: {exc}"
            results.append(result)
        return results

    @staticmethod
    def _resolve_executable(command: str) -> str:
        value = str(command or "").strip()
        if not value:
            return ""
        direct = Path(value)
        if direct.is_file():
            return str(direct)
        resolved = shutil.which(value)
        if resolved:
            return resolved
        if os.name == "nt":
            executable_name = value if value.lower().endswith(".exe") else f"{value}.exe"
            python_dir = Path(sys.executable).resolve().parent
            for candidate in (
                python_dir / "Scripts" / executable_name,
                python_dir / executable_name,
            ):
                if candidate.is_file():
                    return str(candidate)
        return ""

    def mark_connected(self, service_id: str, tool_ids: list[str]) -> None:
        self.get_config(service_id)
        runtime = self._runtime_for(service_id)
        runtime.protocol_connected = True
        runtime.tool_ids = sorted(set(str(tool_id) for tool_id in tool_ids if str(tool_id).strip()))
        runtime.state = "connected"
        runtime.message = f"MCP protocol connected; {len(runtime.tool_ids)} tools discovered"
        self._append_log(runtime, "info", runtime.message)

    def mark_disconnected(self, service_id: str, message: str = "") -> None:
        self.get_config(service_id)
        runtime = self._runtime_for(service_id)
        runtime.protocol_connected = False
        runtime.tool_ids = []
        runtime.capability_bindings = []
        if self.registry is not None:
            self.registry.unregister_source(source_type="mcp", source_id=service_id)
        runtime.state = "running" if runtime.process and runtime.process.returncode is None else "stopped"
        runtime.message = message or "MCP protocol disconnected"
        self._append_log(runtime, "error", runtime.message)

    def is_connected(self, service_id: str) -> bool:
        runtime = self._runtime.get(service_id)
        return bool(runtime and runtime.protocol_connected and runtime.state == "connected")

    def close(self) -> None:
        for service_id, runtime in self._runtime.items():
            if self.registry is not None:
                self.registry.unregister_source(source_type="mcp", source_id=service_id)
            if runtime.process and runtime.process.returncode is None:
                runtime.process.terminate()

    async def _watch_process(self, service_id: str, process: asyncio.subprocess.Process) -> None:
        return_code = await process.wait()
        runtime = self._runtime_for(service_id)
        if runtime.process is not process:
            return
        runtime.process = None
        await self._disconnect_session(service_id, f"process exited with code {return_code}")
        runtime.state = "stopped" if return_code == 0 else "failed"
        runtime.message = f"process exited with code {return_code}"
        self._append_log(runtime, "info" if return_code == 0 else "error", runtime.message)

    async def _read_stderr(self, service_id: str, process: asyncio.subprocess.Process) -> None:
        if not process.stderr:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            self._append_log(
                self._runtime_for(service_id),
                "info",
                line.decode("utf-8", errors="replace").strip(),
            )

    def _runtime_for(self, service_id: str) -> McpServiceRuntime:
        runtime = self._runtime.get(service_id)
        if runtime is None:
            state = "stopped" if self._configs.get(service_id, {}).get("enabled") else "disabled"
            runtime = McpServiceRuntime(state=state)
            self._runtime[service_id] = runtime
        return runtime

    async def _connect_stdio(self, service_id: str) -> None:
        runtime = self._runtime_for(service_id)
        if runtime.process is None:
            raise RuntimeError("MCP stdio process is not running")
        session = McpStdioSession(
            runtime.process,
            log=lambda level, message: self._append_log(runtime, level, message),
        )
        runtime.session = session
        try:
            tools = await session.connect()
        except Exception as exc:
            await self._disconnect_session(service_id, f"MCP handshake failed: {exc}")
            process_running = bool(runtime.process and runtime.process.returncode is None)
            runtime.state = "protocol_disconnected" if process_running else "failed"
            runtime.message = f"MCP handshake failed: {exc}"
            self._append_log(runtime, "error", runtime.message)
            raise RuntimeError(runtime.message) from exc
        tool_ids = self._bind_tools(service_id, tools)
        runtime.protocol_connected = True
        runtime.tool_ids = tool_ids
        runtime.state = "connected"
        runtime.message = f"MCP protocol connected; {len(tool_ids)} tools discovered"
        self._append_log(runtime, "info", runtime.message)

    def _bind_tools(self, service_id: str, tools: list[McpToolDefinition]) -> list[str]:
        namespace = f"mcp_{_normalize_tool_name(service_id)}"
        if self.registry is None:
            return [f"{namespace}.{_normalize_tool_name(tool.name)}" for tool in tools]
        self.registry.unregister_source(source_type="mcp", source_id=service_id)
        self.registry.set_provider_metadata(
            namespace,
            source_type="mcp",
            source_id=service_id,
            provider_kind="mcp",
            display_name=str(self.get_config(service_id).get("name") or service_id),
            lifecycle="external_service",
        )
        runtime = self._runtime_for(service_id)
        runtime.capability_bindings = []
        tool_ids: list[str] = []
        used_tool_ids: set[str] = set()
        for remote_tool in tools:
            base_tool_id = f"{namespace}.{_normalize_tool_name(remote_tool.name)}"
            tool_id = base_tool_id
            suffix = 2
            while tool_id in used_tool_ids:
                tool_id = f"{base_tool_id}_{suffix}"
                suffix += 1
            used_tool_ids.add(tool_id)
            requires_confirmation = self._tool_requires_confirmation(service_id, remote_tool)
            effects = self._tool_effects(service_id, remote_tool)
            roles = self._tool_roles(service_id, remote_tool)
            artifacts = self._tool_artifacts(service_id, remote_tool)
            verification_strength = self._tool_verification_strength(service_id, remote_tool)
            call_timeout = self._tool_call_timeout(service_id, remote_tool.name)
            required_input_fields = _required_input_fields(remote_tool.input_schema)
            diagnostic = self._tool_diagnostic(service_id, remote_tool.name)
            health = str(diagnostic.get("health") or "available")
            last_error = str(diagnostic.get("last_error") or "")

            async def handler(
                input_data: dict[str, Any],
                context: Any,
                *,
                _service_id: str = service_id,
                _remote_name: str = remote_tool.name,
                _effects: list[str] = effects,
                _roles: list[str] = roles,
                _artifacts: list[str] = artifacts,
                _verification_strength: str = verification_strength,
            ) -> dict[str, Any]:
                output = await self.call_tool(_service_id, _remote_name, input_data)
                if not output.get("error"):
                    if _effects:
                        output["effects"] = list(_effects)
                    if _roles:
                        output["roles"] = list(_roles)
                    if _artifacts:
                        output["artifacts"] = list(_artifacts)
                    if _verification_strength:
                        output["verification_strength"] = _verification_strength
                return output

            self.registry.register(
                ToolSpec(
                    id=tool_id,
                    name=remote_tool.title or remote_tool.name,
                    description=remote_tool.description,
                    input_schema=remote_tool.input_schema,
                    requires_confirmation=requires_confirmation,
                    local_only=True,
                    capability=f"mcp.{service_id}",
                    artifacts=artifacts,
                    effects=effects,
                    roles=roles,
                    verification_strength=verification_strength or None,
                    long_running=bool(remote_tool.annotations.get("openWorldHint")),
                    idempotent=bool(remote_tool.annotations.get("readOnlyHint")),
                ),
                handler,
            )
            tool_ids.append(tool_id)
            runtime.capability_bindings.append({
                "tool_id": tool_id,
                "remote_name": remote_tool.name,
                "risk": self._tool_risk(service_id, remote_tool),
                "requires_confirmation": requires_confirmation,
                "effects": effects,
                "roles": roles,
                "artifacts": artifacts,
                "verification_strength": verification_strength,
                "call_timeout": call_timeout,
                "required_input_fields": required_input_fields,
                "health": health,
                "last_error": last_error,
            })
        return tool_ids

    def _tool_requires_confirmation(self, service_id: str, tool: McpToolDefinition) -> bool:
        if self._tool_risk(service_id, tool) == "read_only":
            return False
        permissions = self.get_config(service_id).get("permissions") or {}
        return any(value == "confirm_each" for value in permissions.values())

    def _tool_risk(self, service_id: str, tool: McpToolDefinition) -> str:
        policies = self.get_config(service_id).get("tool_policies") or {}
        policy = policies.get(tool.name) if isinstance(policies, dict) else None
        if isinstance(policy, dict) and policy.get("risk") in {"read_only", "state_change", "unknown"}:
            return str(policy["risk"])
        if tool.annotations.get("readOnlyHint") is True:
            return "read_only"
        if tool.annotations.get("destructiveHint") is True:
            return "state_change"
        return "unknown"

    def _tool_effects(self, service_id: str, tool: McpToolDefinition) -> list[str]:
        return self._tool_policy_values(service_id, tool.name, "effects")

    def _tool_roles(self, service_id: str, tool: McpToolDefinition) -> list[str]:
        return self._tool_policy_values(service_id, tool.name, "roles")

    def _tool_artifacts(self, service_id: str, tool: McpToolDefinition) -> list[str]:
        return self._tool_policy_values(service_id, tool.name, "artifacts")

    def _tool_verification_strength(self, service_id: str, tool: McpToolDefinition) -> str:
        policies = self.get_config(service_id).get("tool_policies") or {}
        policy = policies.get(tool.name) if isinstance(policies, dict) else None
        value = str(policy.get("verification_strength") or "").strip().lower() if isinstance(policy, dict) else ""
        return value if value in {"none", "weak", "standard", "strong"} else ""

    def _tool_call_timeout(self, service_id: str, tool_name: str) -> float:
        config = self.get_config(service_id)
        policies = config.get("tool_policies") or {}
        policy = policies.get(tool_name) if isinstance(policies, dict) else None
        service_timeout = _normalize_timeout_seconds(
            (config.get("timeouts") or {}).get("call"),
            30.0,
        )
        if isinstance(policy, dict) and "call_timeout" in policy:
            return _normalize_timeout_seconds(policy.get("call_timeout"), service_timeout)
        return service_timeout

    def _tool_policy_values(self, service_id: str, tool_name: str, key: str) -> list[str]:
        policies = self.get_config(service_id).get("tool_policies") or {}
        policy = policies.get(tool_name) if isinstance(policies, dict) else None
        values = policy.get(key) if isinstance(policy, dict) else []
        if not isinstance(values, list):
            return []
        return [str(item).strip() for item in values if str(item).strip()]

    async def call_tool(
        self,
        service_id: str,
        remote_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        runtime = self._runtime_for(service_id)
        if not runtime.protocol_connected or runtime.session is None:
            return {
                "error": True,
                "message": f"MCP service is not connected: {service_id}",
                "content": f"MCP service is not connected: {service_id}",
            }
        timeout = self._tool_call_timeout(service_id, remote_name)
        try:
            result = await runtime.session.call_tool(remote_name, arguments, timeout=timeout)
        except Exception as exc:
            self._update_binding_health(
                runtime,
                remote_name,
                error=str(exc),
                service_id=service_id,
            )
            return {
                "error": True,
                "message": f"MCP tool call failed: {exc}",
                "content": f"MCP tool call failed: {exc}",
                "call_timeout": timeout,
            }
        output = normalize_mcp_tool_result(result)
        output.setdefault("call_timeout", timeout)
        self._update_binding_health(
            runtime,
            remote_name,
            error=str(output.get("message") or "") if output.get("error") else "",
            service_id=service_id,
        )
        return output

    def _update_binding_health(
        self,
        runtime: McpServiceRuntime,
        remote_name: str,
        *,
        error: str,
        service_id: str = "",
    ) -> None:
        for binding in runtime.capability_bindings:
            if binding.get("remote_name") != remote_name:
                continue
            binding["health"] = "degraded" if error else "available"
            binding["last_error"] = error[:MAX_TOOL_DIAGNOSTIC_ERROR_CHARS]
            if service_id:
                self._record_tool_diagnostic(service_id, remote_name, error=error)
            return
        if service_id:
            self._record_tool_diagnostic(service_id, remote_name, error=error)

    def _tool_diagnostic(self, service_id: str, remote_name: str) -> dict[str, Any]:
        config = self._configs.get(service_id) or {}
        diagnostics = config.get("tool_diagnostics") if isinstance(config.get("tool_diagnostics"), dict) else {}
        item = diagnostics.get(remote_name) if isinstance(diagnostics, dict) else None
        return item if isinstance(item, dict) else {}

    def _record_tool_diagnostic(self, service_id: str, remote_name: str, *, error: str) -> None:
        config = self._configs.get(service_id)
        name = str(remote_name or "").strip()
        if not config or not name:
            return
        diagnostics = _normalize_tool_diagnostics(config.get("tool_diagnostics"))
        before = json.dumps(diagnostics, sort_keys=True, ensure_ascii=False)
        if error:
            current = diagnostics.get(name, {})
            try:
                failure_count = int(current.get("failure_count") or 0) + 1
            except (TypeError, ValueError):
                failure_count = 1
            diagnostics[name] = {
                "health": "degraded",
                "last_error": str(error)[:MAX_TOOL_DIAGNOSTIC_ERROR_CHARS],
                "updated_at": _now_iso(),
                "failure_count": max(1, min(failure_count, 9999)),
            }
        else:
            diagnostics.pop(name, None)
        after = json.dumps(diagnostics, sort_keys=True, ensure_ascii=False)
        if before == after:
            return
        config["tool_diagnostics"] = diagnostics
        self._save()

    async def _disconnect_session(self, service_id: str, message: str) -> None:
        runtime = self._runtime_for(service_id)
        if runtime.session:
            await runtime.session.close()
        runtime.session = None
        runtime.protocol_connected = False
        runtime.tool_ids = []
        runtime.capability_bindings = []
        if self.registry is not None:
            self.registry.unregister_source(source_type="mcp", source_id=service_id)
        runtime.message = message

    @staticmethod
    def _append_log(runtime: McpServiceRuntime, level: str, message: str) -> None:
        if not message:
            return
        if len(message) > MAX_LOG_MESSAGE_CHARS:
            omitted = len(message) - MAX_LOG_MESSAGE_CHARS
            message = f"{message[:MAX_LOG_MESSAGE_CHARS]} ... [{omitted} chars omitted]"
        runtime.logs.append({"time": _now_iso(), "level": level, "message": message})
        del runtime.logs[:-MAX_LOG_LINES]

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        values = payload.get("services") if isinstance(payload, dict) else []
        configs: dict[str, dict[str, Any]] = {}
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                continue
            candidate = dict(value)
            transport = dict(candidate.get("transport") or {})
            secrets = self._secrets.get(str(candidate.get("id") or ""), {})
            if transport.get("type") == "stdio":
                transport["env"] = secrets.get("env", transport.get("env", {}))
            else:
                transport["headers"] = secrets.get("headers", transport.get("headers", {}))
            candidate["transport"] = transport
            try:
                config = normalize_mcp_service(candidate)
            except ValueError:
                continue
            configs[config["id"]] = config
        return configs

    def _stored_schema_version(self) -> str:
        if not self.path.exists():
            return ""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(payload.get("schema_version") or "") if isinstance(payload, dict) else ""

    def _load_secrets(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self.secrets_path.exists():
            return {}
        try:
            payload = json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        values = payload.get("services") if isinstance(payload, dict) else {}
        return values if isinstance(values, dict) else {}

    def _save(self) -> None:
        services: list[dict[str, Any]] = []
        secrets: dict[str, dict[str, dict[str, str]]] = {}
        for config in self._configs.values():
            public_config = dict(config)
            transport = dict(config.get("transport") or {})
            service_secrets: dict[str, dict[str, str]] = {}
            if transport.get("type") == "stdio":
                service_secrets["env"] = dict(transport.pop("env", {}))
            else:
                service_secrets["headers"] = dict(transport.pop("headers", {}))
            public_config["transport"] = transport
            services.append(public_config)
            if any(service_secrets.values()):
                secrets[config["id"]] = service_secrets
        payload = {
            "schema_version": MCP_SERVICE_SCHEMA_VERSION,
            "services": services,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._secrets = secrets
        self.secrets_path.write_text(
            json.dumps({"schema_version": MCP_SERVICE_SCHEMA_VERSION, "services": secrets}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
