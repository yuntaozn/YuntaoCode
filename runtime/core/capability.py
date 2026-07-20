"""Capability contract schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CAPABILITY_CONTRACT_SCHEMA_VERSION = "capability_contract.v1"
CAPABILITY_PROVIDER_SCHEMA_VERSION = "capability_provider.v1"

FilesystemPermission = Literal["none", "workspace", "full_local"]
ActionPermission = Literal["false", "confirm_each", "allow"]
ProviderKind = Literal[
    "builtin",
    "cli",
    "mcp",
    "desktop",
    "capability_pack",
    "external_plugin",
    "ai_draft",
    "mixed",
    "unknown",
]

PROVIDER_KINDS: frozenset[str] = frozenset(ProviderKind.__args__)  # type: ignore[attr-defined]
PROVIDER_KIND_ALIASES: dict[str, str] = {
    "": "builtin",
    "builtin": "builtin",
    "runtime": "builtin",
    "local": "builtin",
    "cli": "cli",
    "command": "cli",
    "local_command": "cli",
    "mcp": "mcp",
    "desktop": "desktop",
    "desktop_observation": "desktop",
    "local_desktop": "desktop",
    "capability_pack": "capability_pack",
    "skill_pack": "capability_pack",
    "ai_draft": "ai_draft",
    "plugin": "external_plugin",
    "external_plugin": "external_plugin",
    "external_adapter": "external_plugin",
    "mixed": "mixed",
}


def normalize_provider_kind(value: str | None, *, fallback: str = "builtin") -> ProviderKind:
    """Normalize provider implementation kind without exposing tool internals.

    ``source_type`` remains a backwards-compatible origin label.  Provider kind
    is the runtime-level implementation family used by Capability Runtime:
    builtin, cli, mcp, capability_pack, external_plugin, ai_draft, mixed, or
    unknown.
    """
    fallback_kind = PROVIDER_KIND_ALIASES.get(str(fallback or "").strip().lower(), "builtin")
    text = str(value or "").strip().lower()
    if not text:
        text = str(fallback_kind or "").strip().lower()
    normalized = PROVIDER_KIND_ALIASES.get(text, fallback_kind)
    return normalized if normalized in PROVIDER_KINDS else "unknown"  # type: ignore[return-value]


@dataclass(frozen=True)
class CapabilityProvider:
    provider_id: str
    kind: ProviderKind = "builtin"
    source_type: str = "builtin"
    source_id: str = ""
    display_name: str = ""
    lifecycle: str = "in_process"
    local_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source_id = self.source_id or self.provider_id
        return {
            "schema_version": CAPABILITY_PROVIDER_SCHEMA_VERSION,
            "provider_id": self.provider_id,
            "provider_kind": self.kind,
            "source_type": self.source_type or self.kind,
            "source_id": source_id,
            "display_name": self.display_name or self.provider_id,
            "lifecycle": self.lifecycle,
            "local_only": self.local_only,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PermissionSet:
    filesystem: FilesystemPermission = "none"
    shell: ActionPermission = "false"
    network: ActionPermission = "false"
    model: ActionPermission = "false"

    def to_dict(self) -> dict[str, str]:
        return {
            "filesystem": self.filesystem,
            "shell": self.shell,
            "network": self.network,
            "model": self.model,
        }


@dataclass(frozen=True)
class CapabilityContract:
    capability_id: str
    tool_id: str
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_artifacts: tuple[str, ...] = field(default_factory=tuple)
    effect_types: tuple[str, ...] = field(default_factory=tuple)
    task_roles: tuple[str, ...] = field(default_factory=tuple)
    verification_strength: str = "none"
    permissions: PermissionSet = field(default_factory=PermissionSet)
    long_running: bool = False
    retry_safe: bool = False
    requires_confirmation: bool = False
    local_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_CONTRACT_SCHEMA_VERSION,
            "capability_id": self.capability_id,
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "output_artifacts": list(self.output_artifacts),
            "effect_types": list(self.effect_types),
            "task_roles": list(self.task_roles),
            "verification_strength": self.verification_strength,
            "permissions": self.permissions.to_dict(),
            "long_running": self.long_running,
            "retry_safe": self.retry_safe,
            "requires_confirmation": self.requires_confirmation,
            "local_only": self.local_only,
            "metadata": dict(self.metadata),
        }


def needs_user_confirmation(contract: CapabilityContract) -> bool:
    if contract.requires_confirmation:
        return True
    permissions = contract.permissions
    return (
        permissions.shell == "confirm_each"
        or permissions.network == "confirm_each"
        or permissions.model == "confirm_each"
        or permissions.filesystem == "full_local"
    )
