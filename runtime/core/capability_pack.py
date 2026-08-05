"""可移植的本地 Capability Pack Schema。

Capability Pack 是用户数据级资产，可以包含可复用的模型侧方法、任务模板、
上下文摘要或未来工具适配器草稿，但不是可信 Runtime 模块，
默认不得导入 ``runtime.skills``。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CAPABILITY_PACK_SCHEMA_VERSION = "capability_pack.v1"
CAPABILITY_PACK_ENTRY_SCHEMA_VERSION = "capability_pack_entry.v1"
CAPABILITY_PACK_EXPORT_SCHEMA_VERSION = "capability_pack_export.v1"

CapabilityPackKind = Literal["method_skill", "task_template", "context_pack", "tool_adapter"]
CapabilityPackState = Literal["draft", "testing", "enabled", "disabled", "failed", "archived"]
CapabilityPackSource = Literal["ai_generated", "user_imported", "developer", "runtime_suggested"]
CapabilityPackEntryKind = Literal["instructions", "runbook", "context", "command", "mcp", "http"]

CAPABILITY_PACK_KINDS: frozenset[str] = frozenset(CapabilityPackKind.__args__)  # type: ignore[attr-defined]
CAPABILITY_PACK_STATES: frozenset[str] = frozenset(CapabilityPackState.__args__)  # type: ignore[attr-defined]
CAPABILITY_PACK_SOURCES: frozenset[str] = frozenset(CapabilityPackSource.__args__)  # type: ignore[attr-defined]
CAPABILITY_PACK_ENTRY_KINDS: frozenset[str] = frozenset(CapabilityPackEntryKind.__args__)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class CapabilityPackPermissions:
    """Capability Pack 声明的权限。

    方法型 Skill 通常应保持全部权限默认值。工具适配器可以声明更广需求，
    但单纯声明永远不会授予执行权限。"""

    filesystem: str = "none"
    shell: str = "false"
    network: str = "false"
    model: str = "false"
    external_apps: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filesystem": self.filesystem,
            "shell": self.shell,
            "network": self.network,
            "model": self.model,
            "external_apps": list(self.external_apps),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CapabilityPackEntry:
    """Capability Pack 的使用方式。

    ``instructions`` 是面向模型的 Skill 类方法首选默认入口；可执行入口在此层
    仅作为草稿描述符。"""

    kind: CapabilityPackEntryKind = "instructions"
    main: str = "SKILL.md"
    command: str = ""
    args: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_PACK_ENTRY_SCHEMA_VERSION,
            "kind": self.kind,
            "main": self.main,
            "command": self.command,
            "args": list(self.args),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CapabilityPackProvenance:
    source_run_id: str = ""
    source_task_id: str = ""
    source_conversation_id: str = ""
    model: str = ""
    created_by: str = "ai"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_run_id": self.source_run_id,
            "source_task_id": self.source_task_id,
            "source_conversation_id": self.source_conversation_id,
            "model": self.model,
            "created_by": self.created_by,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CapabilityPack:
    id: str
    name: str
    kind: CapabilityPackKind = "method_skill"
    state: CapabilityPackState = "draft"
    source: CapabilityPackSource = "ai_generated"
    version: str = "0.1.0"
    description: str = ""
    summary: str = ""
    instructions: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    entry: CapabilityPackEntry = field(default_factory=CapabilityPackEntry)
    permissions: CapabilityPackPermissions = field(default_factory=CapabilityPackPermissions)
    provenance: CapabilityPackProvenance = field(default_factory=CapabilityPackProvenance)
    tests: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    exportable: bool = True
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_PACK_SCHEMA_VERSION,
            "record_kind": "capability_pack",
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "state": self.state,
            "source": self.source,
            "version": self.version,
            "description": self.description,
            "summary": self.summary,
            "instructions": self.instructions,
            "tags": list(self.tags),
            "entry": self.entry.to_dict(),
            "permissions": self.permissions.to_dict(),
            "provenance": self.provenance.to_dict(),
            "tests": [dict(item) for item in self.tests],
            "exportable": self.exportable,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


def capability_pack_export_bundle(
    pack: CapabilityPack,
    *,
    exported_at: str,
    files: tuple[dict[str, Any], ...] = (),
    skipped_files: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "schema_version": CAPABILITY_PACK_EXPORT_SCHEMA_VERSION,
        "record_kind": "capability_pack_export",
        "exported_at": exported_at,
        "pack": pack.to_dict(),
        "files": [dict(item) for item in files],
        "skipped_files": [dict(item) for item in skipped_files],
    }
