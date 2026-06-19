"""Core runtime schemas for YuntaoCode.

The modules in this package define product-level runtime concepts. They should
stay pure and dependency-light so API handlers, agent strategy, tools, and UI
adapters can depend on them without pulling in model providers or local I/O.
"""

from .capability import CapabilityContract, PermissionSet
from .context import ContextRecord, ContextSnapshot, EvidenceRecord
from .events import TraceEvent, build_trace_event
from .experience import ExperienceDigest, ExperienceSample
from .result import RUN_RESULT_SCHEMA_VERSION, RuntimeResult
from .skill_evolution import ReplayFixture, SkillCandidate, SkillPromotion, SkillReplayResult
from .task import ProductTask, TaskPlan, TaskStep

__all__ = [
    "CapabilityContract",
    "ContextRecord",
    "ContextSnapshot",
    "EvidenceRecord",
    "ExperienceDigest",
    "ExperienceSample",
    "PermissionSet",
    "ProductTask",
    "RUN_RESULT_SCHEMA_VERSION",
    "ReplayFixture",
    "RuntimeResult",
    "SkillCandidate",
    "SkillPromotion",
    "SkillReplayResult",
    "TaskPlan",
    "TaskStep",
    "TraceEvent",
    "build_trace_event",
]
