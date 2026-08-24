from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .core.capability import CapabilityProvider, normalize_provider_kind
from .tool_input_normalizer import normalize_tool_input
from .tool_aliases import TOOL_ID_ALIASES, normalize_tool_id, normalize_tool_syntax


ToolHandler = Callable[[dict[str, Any], Any], Awaitable[dict[str, Any]]]
ToolReadinessProbe = Callable[[], dict[str, Any]]


DEFAULT_TOOL_ID_ALIASES: dict[str, str] = TOOL_ID_ALIASES


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_confirmation: bool = False
    local_only: bool = True
    optional_dependencies: list[str] | None = None
    capability: str | None = None
    artifacts: list[str] | None = None
    effects: list[str] | None = None
    roles: list[str] | None = None
    verification_strength: str | None = None
    affordances: list[dict[str, Any]] | None = None
    long_running: bool = False
    retry_safe: bool = False
    idempotent: bool = False
    readiness_probe: ToolReadinessProbe | None = None

    def check_dependencies(self) -> dict[str, bool]:
        if not self.optional_dependencies:
            return {}
        result = {}
        for dep in self.optional_dependencies:
            try:
                # 静默导入，抑制第三方库自身打印的警告（如 weasyprint 的 GTK 缺失警告）
                with contextlib.redirect_stderr(io.StringIO()):
                    __import__(dep)
                result[dep] = True
            except Exception:
                result[dep] = False
        return result

    def to_public_dict(self) -> dict[str, Any]:
        dependencies = self.check_dependencies()
        readiness = self.check_readiness(dependencies=dependencies)
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "requires_confirmation": self.requires_confirmation,
            "local_only": self.local_only,
            "dependencies": dependencies,
            "available": bool(readiness.get("available", True)),
            "tool_health": str(readiness.get("health") or "available"),
            "readiness": readiness,
            "capability": self.capability,
            "artifacts": list(self.artifacts or []),
            "effects": list(self.effects or []),
            "roles": list(self.roles or []),
            "long_running": self.long_running,
            "retry_safe": self.retry_safe,
            "idempotent": self.idempotent,
        }
        if self.verification_strength:
            data["verification_strength"] = self.verification_strength
        affordances = [
            dict(item)
            for item in (self.affordances or [])
            if isinstance(item, dict)
        ]
        if affordances:
            data["affordances"] = affordances
        message = str(readiness.get("message") or "").strip()
        if message:
            data["tool_last_error"] = message
        return data

    def to_event_contract(self) -> dict[str, Any]:
        """返回写入 ToolEvent 的稳定能力声明快照。"""

        return {
            "declared_capability": self.capability,
            "declared_artifacts": list(self.artifacts or []),
            "declared_effects": list(self.effects or []),
            "declared_roles": list(self.roles or []),
            "declared_verification_strength": self.verification_strength,
        }

    def check_readiness(
        self,
        *,
        dependencies: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """不执行工具，仅返回运行时就绪事实。"""

        dependency_state = dependencies if dependencies is not None else self.check_dependencies()
        missing = sorted(name for name, ready in dependency_state.items() if not ready)
        if missing:
            return {
                "available": False,
                "health": "unavailable",
                "code": "python_dependency_missing",
                "message": f"Missing Python dependencies: {', '.join(missing)}",
                "details": {"missing_dependencies": missing},
            }
        if self.readiness_probe is None:
            return {
                "available": True,
                "health": "available",
                "code": "ready",
                "message": "",
                "details": {},
            }
        try:
            raw = self.readiness_probe()
        except Exception as exc:
            return {
                "available": False,
                "health": "unavailable",
                "code": "readiness_probe_failed",
                "message": f"Capability readiness probe failed: {exc}",
                "details": {},
            }
        if not isinstance(raw, dict):
            return {
                "available": False,
                "health": "unknown",
                "code": "invalid_readiness_result",
                "message": "Capability readiness probe returned an invalid result.",
                "details": {},
            }
        health = str(raw.get("health") or "").strip().lower()
        if health not in {"available", "degraded", "unavailable", "unknown"}:
            health = "available" if bool(raw.get("available", True)) else "unavailable"
        return {
            "available": bool(raw.get("available", health != "unavailable")),
            "health": health,
            "code": str(raw.get("code") or "ready"),
            "message": str(raw.get("message") or ""),
            "details": dict(raw.get("details") or {}) if isinstance(raw.get("details"), dict) else {},
        }


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._aliases: dict[str, str] = dict(DEFAULT_TOOL_ID_ALIASES)
        self._provider_metadata: dict[str, dict[str, str]] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.id in self._tools:
            raise ValueError(f"tool already registered: {spec.id}")
        self._tools[spec.id] = Tool(spec=spec, handler=handler)

    def unregister(self, tool_id: str) -> None:
        resolved_id = self.resolve_id(tool_id)
        self._tools.pop(resolved_id, None)

    def unregister_source(self, *, source_type: str, source_id: str) -> list[str]:
        removed: list[str] = []
        for tool_id in list(self._tools):
            public = self.get_public_spec(tool_id)
            if public.get("source_type") == source_type and public.get("source_id") == source_id:
                self._tools.pop(tool_id, None)
                removed.append(tool_id)
        for provider_id, metadata in list(self._provider_metadata.items()):
            if metadata.get("source_type") == source_type and metadata.get("source_id") == source_id:
                self._provider_metadata.pop(provider_id, None)
        return removed

    def register_alias(self, alias: str, tool_id: str) -> None:
        self._aliases[normalize_tool_syntax(alias)] = normalize_tool_syntax(tool_id)

    def set_provider_metadata(
        self,
        provider_id: str,
        *,
        source_type: str,
        source_id: str | None = None,
        provider_kind: str | None = None,
        display_name: str | None = None,
        lifecycle: str | None = None,
    ) -> None:
        normalized_provider_id = str(provider_id or "").strip()
        normalized_source_type = str(source_type or "").strip()
        if not normalized_provider_id:
            raise ValueError("provider_id is required")
        if not normalized_source_type:
            raise ValueError("source_type is required")
        self._provider_metadata[normalized_provider_id] = {
            "source_type": normalized_source_type,
            "source_id": str(source_id or normalized_provider_id).strip(),
            "provider_kind": normalize_provider_kind(provider_kind or normalized_source_type),
            "display_name": str(display_name or normalized_provider_id).strip(),
            "lifecycle": str(lifecycle or _default_provider_lifecycle(provider_kind or normalized_source_type)).strip(),
        }

    def resolve_id(self, tool_id: str) -> str:
        value = normalize_tool_syntax(tool_id)
        if self._aliases == DEFAULT_TOOL_ID_ALIASES:
            return normalize_tool_id(value)
        return self._aliases.get(value, value)

    def get(self, tool_id: str) -> Tool:
        resolved_id = self.resolve_id(tool_id)
        try:
            return self._tools[resolved_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc

    def normalize_input_data(
        self,
        tool_id: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        return normalize_tool_input(self.resolve_id(tool_id), input_data)

    def get_public_spec(self, tool_id: str) -> dict[str, Any]:
        tool = self.get(tool_id)
        public = tool.spec.to_public_dict()
        provider_id = tool.spec.id.split(".", 1)[0]
        metadata = self._provider_metadata.get(provider_id, {})
        source_type = metadata.get("source_type", "builtin")
        source_id = metadata.get("source_id", provider_id)
        provider_kind = normalize_provider_kind(metadata.get("provider_kind") or source_type)
        provider = CapabilityProvider(
            provider_id=provider_id,
            kind=provider_kind,
            source_type=source_type,
            source_id=source_id,
            display_name=metadata.get("display_name", provider_id),
            lifecycle=metadata.get("lifecycle", _default_provider_lifecycle(provider_kind)),
            local_only=bool(public.get("local_only", True)),
        ).to_dict()
        public["provider_id"] = provider_id
        public["provider_kind"] = provider_kind
        public["provider"] = provider
        public["source_type"] = source_type
        public["source_id"] = source_id
        return public

    def list_specs(self) -> list[dict[str, Any]]:
        return [self.get_public_spec(tool.spec.id) for tool in self._tools.values()]

    def missing_required_input_fields(
        self,
        tool_id: str,
        input_data: dict[str, Any],
    ) -> list[str]:
        tool = self.get(tool_id)
        normalized_input = self.normalize_input_data(tool.spec.id, input_data)
        schema = tool.spec.input_schema if isinstance(tool.spec.input_schema, dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        return [
            str(field)
            for field in required
            if str(field) not in normalized_input or normalized_input.get(str(field)) is None
        ]

    def check_plugin_dependencies(self, plugin_id: str) -> dict[str, bool]:
        result = {}
        for tool in self._tools.values():
            if tool.spec.id.startswith(f"{plugin_id}.") and tool.spec.optional_dependencies:
                deps = tool.spec.check_dependencies()
                for dep, available in deps.items():
                    if dep not in result:
                        result[dep] = available
                    else:
                        result[dep] = result[dep] and available
        return result


def _default_provider_lifecycle(provider_kind: str | None) -> str:
    kind = normalize_provider_kind(provider_kind)
    if kind == "mcp":
        return "external_service"
    if kind == "cli":
        return "subprocess"
    if kind in {"external_plugin", "ai_draft"}:
        return "external_adapter"
    if kind == "capability_pack":
        return "asset"
    return "in_process"
