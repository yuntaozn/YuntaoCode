"""从选定 Experience 证据生成的 Replay Fixture Schema。

Replay Fixture 是根据已审核 Runbook 证据派生的被动记录。它不生成能力、
不注册插件、不提升可信 Runtime 行为，也不执行工具。它让选定 Run 可以被比较、
导出和评测，而不会把每个成功任务自动变成新 Runtime 行为。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


REPLAY_FIXTURE_SCHEMA_VERSION = "replay_fixture.v1"


@dataclass(frozen=True)
class ReplayFixture:
    """从经审核任务证据中提取的稳定任务样本。"""

    id: str
    source_run_id: str
    runbook_id: str = ""
    task_id: str = ""
    workspace_id: str = ""
    conversation_id: str = ""
    goal: str = ""
    task_contract: dict[str, Any] = field(default_factory=dict)
    expected_artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    verification_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REPLAY_FIXTURE_SCHEMA_VERSION,
            "record_kind": "replay_fixture",
            "id": self.id,
            "source_run_id": self.source_run_id,
            "runbook_id": self.runbook_id,
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "goal": self.goal,
            "task_contract": dict(self.task_contract),
            "expected_artifacts": [dict(item) for item in self.expected_artifacts],
            "verification_evidence": [dict(item) for item in self.verification_evidence],
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


def replay_fixture_from_runbook(fixture_id: str, runbook: dict[str, Any]) -> ReplayFixture:
    run = runbook.get("run") if isinstance(runbook.get("run"), dict) else {}
    result = runbook.get("result") if isinstance(runbook.get("result"), dict) else {}
    return ReplayFixture(
        id=fixture_id,
        source_run_id=str(run.get("id") or runbook.get("source_run_id") or ""),
        runbook_id=str(runbook.get("id") or ""),
        task_id=str(run.get("task_id") or ""),
        workspace_id=str(run.get("workspace_id") or ""),
        conversation_id=str(run.get("conversation_id") or ""),
        goal=str(run.get("goal") or ""),
        task_contract=dict(runbook.get("task_contract") or {}),
        expected_artifacts=tuple(_dict_items(result.get("artifacts"))),
        verification_evidence=tuple(_dict_items(runbook.get("verification_evidence"))),
    )


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
