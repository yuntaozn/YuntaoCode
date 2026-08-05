"""可移植插件包契约。

插件是可分发容器，不是执行引擎。它可以打包面向模型的 Skill、Capability Pack、
Provider 描述符、Hook 或静态资源。安装与审核状态由 Runtime 管理，
因而保存在包清单之外。

本模块有意保持纯净，不发现、安装、信任、加载或执行插件内容。"""

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
    """由可移植相对路径引用的一个包成员。"""

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
    """声明的包兼容性；该声明不等同于健康检查。"""

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
    """由包自身提供的可分发插件内容说明。

    请求权限会在启用前展示，但本身绝不授予访问权。每个可执行 Provider 仍进入
    Capability Runtime，并遵循正常权限、确认、Trace 和验证路径。"""

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
    """Runtime 管理的一个已安装插件包本地状态。

    将它放在 ``PluginManifest`` 外，可防止插件包自行声明已审核、可信或已启用。
    ``reviewed`` 也不会绕过任何组件的 Capability Runtime 检查。"""

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
    """不加载包内容，仅返回可移植的包结构问题。"""

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
