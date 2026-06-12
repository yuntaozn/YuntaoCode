"""Capability contract schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CAPABILITY_CONTRACT_SCHEMA_VERSION = "capability_contract.v1"

FilesystemPermission = Literal["none", "workspace", "full_local"]
ActionPermission = Literal["false", "confirm_each", "allow"]


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
