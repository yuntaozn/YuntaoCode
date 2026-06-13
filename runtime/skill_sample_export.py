"""Portable Skill Evolution sample exports.

Sample exports are generated on demand from an existing Runbook view. They do
not persist complete Runbooks and they do not submit anything to a remote
service.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from runtime.core.skill_evolution import replay_fixture_from_runbook
from runtime.runbook import build_runbook


SKILL_SAMPLE_EXPORT_SCHEMA_VERSION = "skill_sample_export.v1"


def build_skill_sample_export(run: Any) -> dict[str, Any]:
    runbook = build_runbook(run)
    run_info = runbook.get("run") if isinstance(runbook.get("run"), dict) else {}
    run_id = str(run_info.get("id") or getattr(run, "id", "") or "")
    fixture_id = f"fixture-{run_id}" if run_id else "fixture-export"
    fixture = replay_fixture_from_runbook(fixture_id, runbook).to_dict()
    filename = _sample_filename(run_info.get("goal") or run_id or "run")
    return {
        "schema_version": SKILL_SAMPLE_EXPORT_SCHEMA_VERSION,
        "kind": "skill_replay_fixture_export",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filename": filename,
        "fixture": fixture,
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
        },
        "privacy_note": (
            "Review this sample before sharing. It excludes full Runbook and file "
            "contents, but goals, paths, artifact names, and task contracts may "
            "still contain private information."
        ),
    }


def _sample_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    text = text[:64] or "skill-sample"
    return f"yuntaocode-skill-sample-{text}.json"
