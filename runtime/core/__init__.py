"""YuntaoCode 核心 Runtime Schema。

本包模块定义产品级运行时概念，应保持纯净、轻依赖，使 API 处理器、Agent 策略、
工具和 UI 适配器可以依赖它们，而无需引入模型 Provider 或本地 I/O。"""

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
