"""Core runtime schemas for YuntaoCode.

The modules in this package define product-level runtime concepts. They should
stay pure and dependency-light so API handlers, agent strategy, tools, and UI
adapters can depend on them without pulling in model providers or local I/O.
"""

from .capability import CapabilityContract, PermissionSet
from .capability_pack import (
    CapabilityPack,
    CapabilityPackEntry,
    CapabilityPackPermissions,
    CapabilityPackProvenance,
)
from .automation import Automation, AutomationRun, AutomationTaskTemplate, AutomationTrigger
from .context import ContextRecord, ContextSnapshot, EvidenceRecord
from .events import TraceEvent, build_trace_event
from .experience import ExperienceDigest, ExperienceSample
from .plugin_manifest import (
    PluginCompatibility,
    PluginComponent,
    PluginInstallation,
    PluginManifest,
)
from .replay_fixture import ReplayFixture
from .result import RUN_RESULT_SCHEMA_VERSION, RuntimeResult
from .task import ProductTask, TaskPlan, TaskStep

__all__ = [
    "CapabilityContract",
    "CapabilityPack",
    "CapabilityPackEntry",
    "CapabilityPackPermissions",
    "CapabilityPackProvenance",
    "Automation",
    "AutomationRun",
    "AutomationTaskTemplate",
    "AutomationTrigger",
    "ContextRecord",
    "ContextSnapshot",
    "EvidenceRecord",
    "ExperienceDigest",
    "ExperienceSample",
    "PermissionSet",
    "PluginCompatibility",
    "PluginComponent",
    "PluginInstallation",
    "PluginManifest",
    "ProductTask",
    "RUN_RESULT_SCHEMA_VERSION",
    "ReplayFixture",
    "RuntimeResult",
    "TaskPlan",
    "TaskStep",
    "TraceEvent",
    "build_trace_event",
]
