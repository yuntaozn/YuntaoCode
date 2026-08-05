"""根据选定 RunEvidence 构建评测 Fixture。

Fixture 是为未来回归和评测工作准备的本地手动产物，不是 Benchmark 提交，
也不会自行执行 Replay。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from runtime.run_evidence import build_run_evidence


EVALUATION_FIXTURE_SCHEMA_VERSION = "evaluation_fixture.v1"
EVALUATION_FIXTURE_EXPORT_SCHEMA_VERSION = "evaluation_fixture_export.v1"


def build_evaluation_fixture_export(run: Any) -> dict[str, Any]:
    """根据一个选中的 Run 构建可移植评测夹具导出。"""
    evidence = build_run_evidence(run)
    run_info = evidence.get("run") if isinstance(evidence.get("run"), dict) else {}
    run_id = str(run_info.get("id") or getattr(run, "id", "") or "")
    fixture_id = f"eval-fixture-{run_id}" if run_id else "eval-fixture"
    fixture = build_evaluation_fixture_from_evidence(fixture_id, evidence)
    return {
        "schema_version": EVALUATION_FIXTURE_EXPORT_SCHEMA_VERSION,
        "kind": "evaluation_fixture_export",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filename": _fixture_filename(run_info.get("goal") or run_id or "run"),
        "fixture": fixture,
        "source": {
            "run_id": run_id,
            "task_id": str(run_info.get("task_id") or ""),
            "workspace_id": str(run_info.get("workspace_id") or ""),
            "status": str(run_info.get("status") or ""),
            "attempt": int(run_info.get("attempt") or 1),
        },
        "export_policy": {
            "manual_export": True,
            "stored_by_runtime": False,
            "remote_submission": False,
            "contains_full_runbook": False,
            "contains_full_event_log": False,
            "contains_file_contents": False,
            "contains_api_keys": False,
            "executes_replay": False,
        },
        "privacy_note": (
            "Review this fixture before sharing. It excludes full event logs and "
            "file contents, but goals, paths, model IDs, task contracts, and "
            "capability names may still contain private information."
        ),
    }


def build_evaluation_fixture_from_evidence(
    fixture_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """根据 RunEvidence 视图构建稳定评测夹具结构。"""
    run = evidence.get("run") if isinstance(evidence.get("run"), dict) else {}
    contract = evidence.get("task_contract") if isinstance(evidence.get("task_contract"), dict) else {}
    result = evidence.get("result") if isinstance(evidence.get("result"), dict) else {}
    trace = evidence.get("trace") if isinstance(evidence.get("trace"), dict) else {}
    capability_evidence = (
        evidence.get("capability_evidence")
        if isinstance(evidence.get("capability_evidence"), dict)
        else {}
    )
    replay_seed = evidence.get("replay_seed") if isinstance(evidence.get("replay_seed"), dict) else {}
    expected_artifacts = _dict_items(result.get("artifacts")) or _contract_expected_artifacts(contract)
    return {
        "schema_version": EVALUATION_FIXTURE_SCHEMA_VERSION,
        "record_kind": "evaluation_fixture",
        "id": str(fixture_id or "eval-fixture"),
        "source_run_id": str(run.get("id") or ""),
        "task_id": str(run.get("task_id") or ""),
        "workspace_id": str(run.get("workspace_id") or ""),
        "conversation_id": str(run.get("conversation_id") or ""),
        "goal": str(run.get("goal") or ""),
        "task_contract": dict(contract),
        "expected": {
            "result_status": str(result.get("status") or ""),
            "artifacts": expected_artifacts,
            "risks": list(evidence.get("risks") or []),
            "required_verification_strength": str(
                result.get("required_verification_strength")
                or contract.get("required_verification_strength")
                or ""
            ),
            "required_verification_modalities": _string_list(
                result.get("required_verification_modalities")
                or contract.get("required_verification_modalities")
            ),
        },
        "baseline": {
            "run_evidence_schema_version": str(evidence.get("schema_version") or ""),
            "trace_schema_version": str(trace.get("schema_version") or ""),
            "capability_evidence_schema_version": str(capability_evidence.get("schema_version") or ""),
            "event_count": int(trace.get("event_count") or 0),
            "tool_event_count": int(trace.get("tool_event_count") or 0),
            "failed_tool_count": int(trace.get("failed_tool_count") or 0),
            "failure_count": len(evidence.get("failures") or []),
            "verification_count": len(evidence.get("verification_evidence") or []),
            "checkpoint_count": int((evidence.get("recovery") or {}).get("checkpoint_count") or 0)
            if isinstance(evidence.get("recovery"), dict) else 0,
        },
        "capabilities": {
            "requested": list(capability_evidence.get("requested_capability_ids") or []),
            "observed": list(capability_evidence.get("observed_capability_ids") or []),
            "unobserved_requested": list(capability_evidence.get("unobserved_requested_capability_ids") or []),
            "observed_effects": list(capability_evidence.get("observed_effects") or []),
            "observed_roles": list(capability_evidence.get("observed_roles") or []),
            "artifacts": list(capability_evidence.get("artifacts") or []),
            "verification_strengths": list(capability_evidence.get("verification_strengths") or []),
        },
        "verification_evidence": _dict_items(evidence.get("verification_evidence")),
        "replay_seed": {
            "source_run_id": str(replay_seed.get("source_run_id") or run.get("id") or ""),
            "workspace_id": str(replay_seed.get("workspace_id") or run.get("workspace_id") or ""),
            "task_id": str(replay_seed.get("task_id") or run.get("task_id") or ""),
            "mode": str(replay_seed.get("mode") or run.get("mode") or ""),
            "goal": str(replay_seed.get("goal") or run.get("goal") or ""),
            "task_contract": dict(replay_seed.get("task_contract") or contract),
            "boundary": str(replay_seed.get("boundary") or "manual_start_required"),
        },
        "boundaries": {
            "manual_export": True,
            "manual_replay_required": True,
            "local_only": True,
            "remote_submission": False,
            "executes_replay": False,
            "promotes_capability": False,
            "promotes_skill": False,
        },
    }


def _contract_expected_artifacts(contract: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in contract.get("deliverables") or []:
        if not isinstance(item, dict):
            continue
        artifact = {
            "kind": str(item.get("kind") or ""),
            "path": str(item.get("path") or item.get("path_hint") or item.get("output_path") or ""),
            "description": str(item.get("description") or ""),
            "capability_id": str(item.get("capability_id") or ""),
        }
        result.append({key: value for key, value in artifact.items() if value})
    return result


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _fixture_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    text = text[:64] or "run"
    return f"yuntaocode-evaluation-fixture-{text}.json"
