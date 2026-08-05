"""声明式 CLI Provider Schema。

CLI Provider 是由本地子进程执行支持的能力 Provider，不等同于自由形式 Shell 访问。
每个暴露工具在进入 ToolRegistry 前，都必须声明命令、参数、输入、输出、权限、
超时、影响范围和验证证据。"""

from __future__ import annotations

import re
import sys
from copy import deepcopy
from typing import Any


CLI_PROVIDER_SCHEMA_VERSION = "cli_provider.v1"
CLI_PROVIDER_STORE_SCHEMA_VERSION = "cli_provider_store.v1"
CLI_PROVIDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
CLI_TOOL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SUPPORTED_EVIDENCE_TYPES = {
    "exit_code_zero",
    "file_exists",
    "file_min_size",
    "stdout_contains",
    "stderr_not_contains",
}
SUPPORTED_PLATFORMS = {"windows", "macos", "linux"}
PERMISSION_VALUES = {
    "filesystem": {"none", "workspace", "full_local"},
    "shell": {"false", "confirm_each", "allow"},
    "network": {"false", "confirm_each", "allow"},
    "model": {"false", "confirm_each", "allow"},
}


def normalize_cli_provider(value: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = existing or {}
    provider_id = str(value.get("id") or current.get("id") or "").strip()
    if not CLI_PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise ValueError("CLI provider id must use letters, numbers, dot, underscore, or hyphen")

    incoming_tools = value.get("tools")
    if incoming_tools is None:
        incoming_tools = current.get("tools")
    if incoming_tools is None:
        incoming_tools = [_legacy_single_tool_payload(value, current)]
    if not isinstance(incoming_tools, list) or not incoming_tools:
        raise ValueError("CLI provider requires at least one tool")

    tools = [
        _normalize_cli_tool(item, provider_id=provider_id)
        for item in incoming_tools
        if isinstance(item, dict)
    ]
    if not tools:
        raise ValueError("CLI provider requires at least one valid tool")

    return {
        "schema_version": CLI_PROVIDER_SCHEMA_VERSION,
        "id": provider_id,
        "name": str(value.get("name") or current.get("name") or provider_id).strip() or provider_id,
        "description": str(value.get("description") or current.get("description") or "").strip(),
        "enabled": bool(value.get("enabled", current.get("enabled", True))),
        "tools": tools,
    }


def current_platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def cli_tool_registry_id(provider_id: str, tool_id: str) -> str:
    return f"cli_{_normalize_namespace(provider_id)}.{_normalize_namespace(tool_id)}"


def _normalize_cli_tool(value: dict[str, Any], *, provider_id: str) -> dict[str, Any]:
    tool_id = str(value.get("id") or value.get("tool_id") or "run").strip()
    if not CLI_TOOL_ID_PATTERN.fullmatch(tool_id):
        raise ValueError(f"CLI tool id must use letters, numbers, dot, underscore, or hyphen: {tool_id}")
    command = str(value.get("command") or "").strip()
    if not command:
        raise ValueError(f"CLI tool {tool_id} requires command")
    args = value.get("args") or []
    if not isinstance(args, list):
        raise ValueError(f"CLI tool {tool_id} args must be an array")
    env = value.get("env") or {}
    if not isinstance(env, dict):
        raise ValueError(f"CLI tool {tool_id} env must be an object")

    input_schema = value.get("input_schema")
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}, "required": []}
    inputs = _normalize_inputs(value.get("inputs"), input_schema)
    outputs = _normalize_outputs(value.get("outputs"))
    effects = _string_list(value.get("effects"))
    if outputs and not effects:
        effects = ["file_write"]
    artifacts = _string_list(value.get("artifacts"))
    if outputs and not artifacts:
        artifacts = sorted({
            str(item.get("artifact") or "file")
            for item in outputs
            if str(item.get("artifact") or "").strip() or item
        })
    roles = _string_list(value.get("roles"))
    if outputs and not roles:
        roles = ["deliverable"]
    evidence = _normalize_evidence(value.get("evidence"), outputs)
    permissions = _normalize_permissions(value.get("permissions"))
    verification_strength = str(value.get("verification_strength") or "").strip().lower()
    if verification_strength not in {"none", "weak", "standard", "strong"}:
        verification_strength = "standard" if evidence else ""

    return {
        "id": tool_id,
        "registry_id": cli_tool_registry_id(provider_id, tool_id),
        "name": str(value.get("name") or tool_id).strip() or tool_id,
        "description": str(value.get("description") or "").strip(),
        "capability": str(value.get("capability") or value.get("capability_id") or f"cli.{provider_id}").strip(),
        "command": command,
        "args": [str(item) for item in args],
        "cwd": str(value.get("cwd") or "workspace").strip() or "workspace",
        "env": {str(key): str(item) for key, item in env.items() if str(key).strip()},
        "input_schema": deepcopy(input_schema),
        "inputs": inputs,
        "outputs": outputs,
        "permissions": permissions,
        "timeout": _normalize_timeout(value.get("timeout"), default=60),
        "evidence": evidence,
        "effects": effects,
        "artifacts": artifacts,
        "roles": roles,
        "verification_strength": verification_strength,
        "requires_confirmation": _requires_confirmation(value, permissions, effects),
        "local_only": bool(value.get("local_only", True)),
        "platforms": _normalize_platforms(value.get("platforms")),
        "retry_safe": bool(value.get("retry_safe", False)),
        "idempotent": bool(value.get("idempotent", False)),
    }


def _legacy_single_tool_payload(value: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    result.update(value)
    result.setdefault("id", "run")
    return result


def _normalize_inputs(value: Any, input_schema: dict[str, Any]) -> list[dict[str, str]]:
    explicit: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            kind = str(item.get("kind") or "value").strip().lower()
            access = str(item.get("access") or "").strip().lower()
            explicit.append({
                "name": name,
                "kind": kind if kind in {"value", "path", "file", "directory"} else "value",
                "access": access if access in {"read", "write", "read_write"} else "",
            })
    names = {item["name"] for item in explicit}
    properties = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
    for name, schema in properties.items():
        text = str(name or "").strip()
        if not text or text in names:
            continue
        kind = "path" if _looks_like_path_input_name(text) else "value"
        access = ""
        if isinstance(schema, dict):
            access = str(schema.get("x-yuntaocode-access") or schema.get("access") or "").strip().lower()
            schema_kind = str(schema.get("x-yuntaocode-kind") or schema.get("kind") or "").strip().lower()
            if schema_kind in {"path", "file", "directory"}:
                kind = schema_kind
        explicit.append({
            "name": text,
            "kind": kind,
            "access": access if access in {"read", "write", "read_write"} else "",
        })
    return explicit


def _normalize_outputs(value: Any) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return outputs
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        outputs.append({
            "name": str(item.get("name") or "output").strip() or "output",
            "path": path,
            "artifact": str(item.get("artifact") or "file").strip() or "file",
            "required": bool(item.get("required", True)),
        })
    return outputs[:20]


def _normalize_evidence(value: Any, outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "").strip()
            if kind not in SUPPORTED_EVIDENCE_TYPES:
                continue
            normalized = {
                "type": kind,
                "required": bool(item.get("required", True)),
            }
            for key in ("path", "text"):
                text = str(item.get(key) or "").strip()
                if text:
                    normalized[key] = text
            if kind == "file_min_size":
                try:
                    normalized["min_bytes"] = max(0, int(item.get("min_bytes") or 1))
                except (TypeError, ValueError):
                    normalized["min_bytes"] = 1
            evidence.append(normalized)
    if not evidence:
        evidence.append({"type": "exit_code_zero", "required": True})
    for output in outputs:
        if output.get("required", True):
            evidence.append({
                "type": "file_exists",
                "path": output["path"],
                "required": True,
            })
    return evidence[:40]


def _normalize_permissions(value: Any) -> dict[str, str]:
    permissions = value if isinstance(value, dict) else {}
    result = {
        "filesystem": str(permissions.get("filesystem") or "workspace"),
        "shell": str(permissions.get("shell") or "confirm_each"),
        "network": str(permissions.get("network") or "false"),
        "model": str(permissions.get("model") or "false"),
    }
    for key, allowed in PERMISSION_VALUES.items():
        if result[key] not in allowed:
            raise ValueError(f"unsupported CLI provider {key} permission: {result[key]}")
    return result


def _normalize_platforms(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        return sorted(SUPPORTED_PLATFORMS)
    aliases = {"win32": "windows", "darwin": "macos", "osx": "macos"}
    result: list[str] = []
    for item in value:
        platform = aliases.get(str(item or "").strip().lower(), str(item or "").strip().lower())
        if platform in SUPPORTED_PLATFORMS and platform not in result:
            result.append(platform)
    return result or sorted(SUPPORTED_PLATFORMS)


def _normalize_timeout(value: Any, *, default: int) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(timeout, 3600))


def _requires_confirmation(value: dict[str, Any], permissions: dict[str, str], effects: list[str]) -> bool:
    if "requires_confirmation" in value:
        return bool(value.get("requires_confirmation"))
    if any(item == "confirm_each" for item in permissions.values()):
        return True
    return bool(set(effects) & {"file_write", "file_delete", "local_state_change", "external_state_change"})


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _looks_like_path_input_name(value: str) -> bool:
    text = value.lower()
    return (
        text in {"path", "file", "dir", "folder", "input_path", "output_path", "input_file", "output_file"}
        or text.endswith("_path")
        or text.endswith("_file")
        or text.endswith("_dir")
        or text.endswith("_folder")
    )


def _normalize_namespace(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
    return normalized or "provider"
