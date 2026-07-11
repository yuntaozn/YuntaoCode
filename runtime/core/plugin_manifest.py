"""Portable plugin package contracts.

A plugin is a distributable container, not an execution engine. It may package
model-facing skills, Capability Packs, provider descriptors, hooks, or static
assets. Installation and review state are runtime-owned records and therefore
stay outside the package manifest.

This module is intentionally pure. It does not discover, install, trust, load,
or execute plugin content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from .capability import PermissionSet


PLUGIN_MANIFEST_SCHEMA_VERSION = "plugin_manifest.v1"
PLUGIN_COMPONENT_SCHEMA_VERSION = "plugin_component.v1"
PLUGIN_INSTALLATION_SCHEMA_VERSION = "plugin_installation.v1"

PluginComponentKind = Literal[
    "skill",
    "capability_pack",
    "mcp_provider",
    "cli_provider",
    "external_provider",
    "hook",
    "asset",
]
PluginSourceKind = Literal["local", "git", "catalog", "imported", "ai_draft"]
PluginInstallState = Literal[
    "discovered",
    "installed",
    "quarantined",
    "removed",
]
PluginReviewState = Literal["unreviewed", "reviewed", "rejected"]

PLUGIN_COMPONENT_KINDS: frozenset[str] = frozenset(PluginComponentKind.__args__)  # type: ignore[attr-defined]
PLUGIN_SOURCE_KINDS: frozenset[str] = frozenset(PluginSourceKind.__args__)  # type: ignore[attr-defined]
PLUGIN_INSTALL_STATES: frozenset[str] = frozenset(PluginInstallState.__args__)  # type: ignore[attr-defined]
PLUGIN_REVIEW_STATES: frozenset[str] = frozenset(PluginReviewState.__args__)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class PluginComponent:
    """One package member referenced by a portable relative path."""

    kind: PluginComponentKind
    path: str
    id: str = ""
    optional: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLUGIN_COMPONENT_SCHEMA_VERSION,
            "kind": self.kind,
            "id": self.id,
            "path": self.path,
            "optional": self.optional,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PluginCompatibility:
    """Declared package compatibility; declaration is not a health check."""

    min_runtime_version: str = ""
    max_runtime_version: str = ""
    platforms: tuple[str, ...] = field(default_factory=tuple)
    python: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_runtime_version": self.min_runtime_version,
            "max_runtime_version": self.max_runtime_version,
            "platforms": list(self.platforms),
            "python": self.python,
        }


@dataclass(frozen=True)
class PluginManifest:
    """Package-owned description of distributable plugin contents.

    Requested permissions are shown before enablement but never grant access by
    themselves. Every executable provider still enters Capability Runtime and
    its normal permission, confirmation, trace, and verification path.
    """

    id: str
    name: str
    version: str
    description: str = ""
    components: tuple[PluginComponent, ...] = field(default_factory=tuple)
    requested_permissions: PermissionSet = field(default_factory=PermissionSet)
    external_apps: tuple[str, ...] = field(default_factory=tuple)
    compatibility: PluginCompatibility = field(default_factory=PluginCompatibility)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLUGIN_MANIFEST_SCHEMA_VERSION,
            "record_kind": "plugin_manifest",
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "components": [item.to_dict() for item in self.components],
            "requested_permissions": self.requested_permissions.to_dict(),
            "external_apps": list(self.external_apps),
            "compatibility": self.compatibility.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PluginInstallation:
    """Runtime-owned local state for one installed plugin package.

    Keeping this outside ``PluginManifest`` prevents a package from declaring
    itself reviewed, trusted, or enabled. ``reviewed`` also does not bypass
    Capability Runtime checks for any component.
    """

    plugin_id: str
    plugin_version: str
    source_kind: PluginSourceKind = "local"
    source_uri: str = ""
    install_state: PluginInstallState = "discovered"
    review_state: PluginReviewState = "unreviewed"
    installed_path: str = ""
    content_digest: str = ""
    enabled_components: tuple[str, ...] = field(default_factory=tuple)
    installed_at: str = ""
    reviewed_at: str = ""
    enabled_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLUGIN_INSTALLATION_SCHEMA_VERSION,
            "record_kind": "plugin_installation",
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "source_kind": self.source_kind,
            "source_uri": self.source_uri,
            "install_state": self.install_state,
            "review_state": self.review_state,
            "installed_path": self.installed_path,
            "content_digest": self.content_digest,
            "enabled_components": list(self.enabled_components),
            "installed_at": self.installed_at,
            "reviewed_at": self.reviewed_at,
            "enabled_at": self.enabled_at,
            "metadata": dict(self.metadata),
        }


def plugin_manifest_issues(manifest: PluginManifest) -> tuple[str, ...]:
    """Return portable package-shape issues without loading package content."""

    issues: list[str] = []
    if not manifest.id.strip():
        issues.append("plugin_id_required")
    if not manifest.name.strip():
        issues.append("plugin_name_required")
    if not manifest.version.strip():
        issues.append("plugin_version_required")

    component_ids: set[str] = set()
    for component in manifest.components:
        if component.kind not in PLUGIN_COMPONENT_KINDS:
            issues.append(f"unsupported_component_kind:{component.kind}")
        if not _is_portable_relative_path(component.path):
            issues.append(f"invalid_component_path:{component.path}")
        component_id = component.id.strip()
        if component_id:
            if component_id in component_ids:
                issues.append(f"duplicate_component_id:{component_id}")
            component_ids.add(component_id)
    return tuple(issues)


def _is_portable_relative_path(value: str) -> bool:
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("/"):
        return False
    if len(text) >= 2 and text[1] == ":":
        return False
    path = PurePosixPath(text)
    return not path.is_absolute() and ".." not in path.parts
