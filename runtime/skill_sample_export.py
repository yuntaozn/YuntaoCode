"""可移植的 Experience Sample 与 Replay Fixture 导出。

样本导出根据现有 Runbook 视图按需生成，产出 Experience Sample 与
Replay Fixture；不持久化完整 Runbook，也不向远程服务提交任何内容。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from runtime.core.experience import experience_sample_from_runbook
from runtime.core.replay_fixture import replay_fixture_from_runbook
from runtime.run_evidence import build_run_evidence
from runtime.runbook import build_runbook_from_evidence


EXPERIENCE_SAMPLE_EXPORT_SCHEMA_VERSION = "experience_sample_export.v1"
SKILL_SAMPLE_EXPORT_SCHEMA_VERSION = "skill_sample_export.v1"


def build_experience_sample_export(run: Any) -> dict[str, Any]:
    evidence = build_run_evidence(run)
    runbook = build_runbook_from_evidence(evidence)
    run_info = runbook.get("run") if isinstance(runbook.get("run"), dict) else {}
    run_id = str(run_info.get("id") or getattr(run, "id", "") or "")
    sample_id = f"experience-{run_id}" if run_id else "experience-export"
    fixture_id = f"fixture-{run_id}" if run_id else "fixture-export"
    experience_sample = experience_sample_from_runbook(sample_id, runbook).to_dict()
    fixture = replay_fixture_from_runbook(fixture_id, runbook).to_dict()
    filename = _sample_filename(run_info.get("goal") or run_id or "run")
    return {
        "schema_version": EXPERIENCE_SAMPLE_EXPORT_SCHEMA_VERSION,
        "kind": "experience_replay_fixture_export",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filename": filename,
        "experience_sample": experience_sample,
        "fixture": fixture,
        "run_evidence": _sample_evidence_summary(evidence),
        "source": {
            "run_id": run_id,
            "task_id": str(run_info.get("task_id") or ""),
            "workspace_id": str(run_info.get("workspace_id") or ""),
            "status": str(run_info.get("status") or ""),
            "attempt": int(run_info.get("attempt") or 1),
        },
        "sample_policy": {
            "manual_export": True,
            "stored_by_runtime": False,
            "remote_submission": False,
            "contains_full_runbook": False,
            "contains_file_contents": False,
            "promotes_capability": False,
            "promotes_skill": False,
        },
        "privacy_note": (
            "Review this sample before sharing. It excludes full Runbook and file "
            "contents, but goals, paths, artifact names, and task contracts may "
            "still contain private information."
        ),
    }


def build_skill_sample_export(run: Any) -> dict[str, Any]:
    exported = build_experience_sample_export(run)
    exported["schema_version"] = SKILL_SAMPLE_EXPORT_SCHEMA_VERSION
    exported["kind"] = "skill_replay_fixture_export"
    exported["compatibility"] = {
        "preferred_schema_version": EXPERIENCE_SAMPLE_EXPORT_SCHEMA_VERSION,
        "preferred_kind": "experience_replay_fixture_export",
        "note": "Skill sample export is a compatibility name. The stable concept is an Experience Sample plus Replay Fixture.",
    }
    return exported


def _sample_evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    trace = evidence.get("trace") if isinstance(evidence.get("trace"), dict) else {}
    capability_evidence = evidence.get("capability_evidence") if isinstance(evidence.get("capability_evidence"), dict) else {}
    result = evidence.get("result") if isinstance(evidence.get("result"), dict) else {}
    return {
        "schema_version": str(evidence.get("schema_version") or ""),
        "trace_schema_version": str(trace.get("schema_version") or ""),
        "capability_evidence_schema_version": str(capability_evidence.get("schema_version") or ""),
        "result_status": str(result.get("status") or ""),
        "risk_count": len(evidence.get("risks") or []),
        "failure_count": len(evidence.get("failures") or []),
        "verification_count": len(evidence.get("verification_evidence") or []),
        "observed_capability_ids": list(capability_evidence.get("observed_capability_ids") or []),
    }


def _sample_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    text = text[:64] or "experience-sample"
    return f"yuntaocode-experience-sample-{text}.json"
