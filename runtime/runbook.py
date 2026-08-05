"""根据 RunEvidence 构建 Runbook 与 Replay 辅助数据。

Runbook 是 Runtime 管理的审计产物，用于汇总一次 Run 中实际发生的事项，
不重新执行工具，也不把模型文字当作完成证据。"""

from __future__ import annotations

from typing import Any

from runtime.run_evidence import build_run_evidence


RUNBOOK_SCHEMA_VERSION = "runbook.v1"
REPLAY_REQUEST_SCHEMA_VERSION = "replay_request.v1"


def build_runbook(run: Any) -> dict[str, Any]:
    """根据类似 RunRecord 的对象构建紧凑 Runbook。"""
    return build_runbook_from_evidence(build_run_evidence(run))


def build_runbook_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """根据 RunEvidence 视图构建公开 Runbook 结构。"""
    return {
        "schema_version": RUNBOOK_SCHEMA_VERSION,
        "kind": "runbook",
        "run": evidence.get("run") if isinstance(evidence.get("run"), dict) else {},
        "task_contract": evidence.get("task_contract") if isinstance(evidence.get("task_contract"), dict) else {},
        "trace": evidence.get("trace") if isinstance(evidence.get("trace"), dict) else {},
        "context_pack": evidence.get("context_pack") if isinstance(evidence.get("context_pack"), dict) else {},
        "context_packs": list(evidence.get("context_packs") or []),
        "workspace_snapshot": evidence.get("workspace_snapshot") if isinstance(evidence.get("workspace_snapshot"), dict) else {},
        "capability_evidence": evidence.get("capability_evidence") if isinstance(evidence.get("capability_evidence"), dict) else {},
        "capability_snapshot": evidence.get("capability_snapshot") if isinstance(evidence.get("capability_snapshot"), dict) else {},
        "plan": evidence.get("plan") if isinstance(evidence.get("plan"), dict) else {},
        "tool_steps": list(evidence.get("tool_steps") or []),
        "status_timeline": list(evidence.get("status_timeline") or []),
        "completion_decisions": list(evidence.get("completion_decisions") or []),
        "result": evidence.get("result") if isinstance(evidence.get("result"), dict) else {},
        "risks": list(evidence.get("risks") or []),
        "failures": list(evidence.get("failures") or []),
        "failure_details": list(evidence.get("failure_details") or []),
        "verification_evidence": list(evidence.get("verification_evidence") or []),
        "checkpoints": list(evidence.get("checkpoints") or []),
        "recovery": evidence.get("recovery") if isinstance(evidence.get("recovery"), dict) else {},
        "replay": build_replay_request_from_evidence(evidence, include_runbook=False),
    }


def build_replay_request(run: Any, *, include_runbook: bool = True) -> dict[str, Any]:
    """构建回放请求产物，但不启动新的 Run。"""
    evidence = build_run_evidence(run)
    return build_replay_request_from_evidence(evidence, include_runbook=include_runbook)


def build_replay_request_from_evidence(
    evidence: dict[str, Any],
    *,
    include_runbook: bool = True,
) -> dict[str, Any]:
    """根据现有 RunEvidence 视图构建回放请求。"""
    seed = evidence.get("replay_seed") if isinstance(evidence.get("replay_seed"), dict) else {}
    replay = {
        "schema_version": REPLAY_REQUEST_SCHEMA_VERSION,
        "kind": "replay_request",
        "source_run_id": str(seed.get("source_run_id") or ""),
        "conversation_id": str(seed.get("conversation_id") or ""),
        "workspace_id": str(seed.get("workspace_id") or ""),
        "task_id": str(seed.get("task_id") or ""),
        "mode": str(seed.get("mode") or ""),
        "goal": str(seed.get("goal") or ""),
        "task_contract": seed.get("task_contract") if isinstance(seed.get("task_contract"), dict) else {},
        "replayable": bool(seed.get("replayable", False)),
        "boundary": str(seed.get("boundary") or "manual_start_required"),
        "notes": [
            "Replay request is an audit artifact in 0.1; it does not execute tools by itself.",
            "Start a new run with the goal and task_contract after reviewing the run evidence.",
        ],
    }
    if include_runbook:
        replay["runbook"] = build_runbook_from_evidence(evidence)
    return replay
