"""单次对话 Run 的可变生命周期状态。

本模块记录模型轮次之间共享的执行事实，不负责分类任务、选择工具、判断能力
适配性，也不决定模型下一步应采用什么策略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TransientModelContext:
    """仅供下一次响应使用、不得进入任务历史的 Runtime 提示。"""

    pending_messages: list[dict[str, Any]] = field(default_factory=list)

    def add(self, message: dict[str, Any]) -> None:
        if isinstance(message, dict) and all(
            message is not existing for existing in self.pending_messages
        ):
            self.pending_messages.append(message)

    def add_from(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "system":
                self.add(message)

    def consume_from(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.pending_messages:
            return messages
        pending_ids = {id(message) for message in self.pending_messages}
        self.pending_messages.clear()
        return [message for message in messages if id(message) not in pending_ids]


@dataclass
class RunExecutionState:
    """单个 Run 在模型与工具生命周期中的显式可变状态。"""

    round_limit: int
    round_index: int = -1
    max_rounds_exceeded: bool = False
    transient_model_context: TransientModelContext = field(
        default_factory=TransientModelContext
    )
    consecutive_idle_timeouts: int = 0
    argument_observation_threshold: int = 24_000
    large_argument_observations: int = 0
    guidance_count: int = 0
    model_provider_error: str = ""

    @classmethod
    def create(cls, max_rounds: int) -> "RunExecutionState":
        return cls(round_limit=max(1, int(max_rounds or 1)))

    @property
    def round_number(self) -> int:
        return self.round_index + 1

    def can_start_round(self) -> bool:
        return self.round_number < self.round_limit

    def start_round(self) -> int:
        if not self.can_start_round():
            raise RuntimeError("run round budget is exhausted")
        self.round_index += 1
        return self.round_index

    def record_guidance(self) -> None:
        self.guidance_count += 1

    @property
    def runtime_intervention_count(self) -> int:
        """供旧版诊断读取器使用的兼容别名。"""

        return self.guidance_count

    @runtime_intervention_count.setter
    def runtime_intervention_count(self, value: int) -> None:
        self.guidance_count = max(0, int(value or 0))
