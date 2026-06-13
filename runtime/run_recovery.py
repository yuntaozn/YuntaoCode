"""Recovery artifact builders for completed or paused Runs."""

from __future__ import annotations

from typing import Any

from runtime.core.context import CONTEXT_SNAPSHOT_SCHEMA_VERSION


def build_result_context_snapshot(
    *,
    task_id: str,
    run_id: str,
    task_contract: dict[str, Any],
    run_result: dict[str, Any],
) -> dict[str, Any]:
    written_paths = [str(item) for item in run_result.get("written_paths") or [] if str(item)]
    verified = run_result.get("verified") if isinstance(run_result.get("verified"), list) else []
    risks = [str(item) for item in run_result.get("risks") or [] if str(item)]
    failures = run_result.get("failures") if isinstance(run_result.get("failures"), list) else []
    records: list[dict[str, Any]] = [
        {
            "schema_version": "context_record.v1",
            "kind": "task_contract",
            "content": str(task_contract.get("goal") or task_contract.get("intent") or ""),
            "source_id": f"run:{run_id}:task_contract",
            "source_type": "run_event",
            "trust": "runtime_fact",
            "task_id": task_id,
            "freshness": "current",
            "token_estimate": 0,
            "metadata": {"contract": task_contract},
        },
        {
            "schema_version": "context_record.v1",
            "kind": "tool_result",
            "content": f"Run status: {run_result.get('status') or 'unknown'}",
            "source_id": f"run:{run_id}:result",
            "source_type": "run_result",
            "trust": "runtime_fact",
            "task_id": task_id,
            "freshness": "current",
            "token_estimate": 0,
            "metadata": {
                "written_paths": written_paths,
                "counts": run_result.get("counts") or {},
            },
        },
    ]
    records.extend(
        {
            "schema_version": "context_record.v1",
            "kind": "risk",
            "content": risk,
            "source_id": f"run:{run_id}:risk:{index}",
            "source_type": "run_result",
            "trust": "runtime_fact",
            "task_id": task_id,
            "freshness": "current",
            "token_estimate": 0,
            "metadata": {},
        }
        for index, risk in enumerate(risks)
    )
    evidence = [
        {
            "schema_version": "evidence_record.v1",
            "source_id": f"file:{path}",
            "kind": "file",
            "path": path,
            "summary": "Observed written artifact from the source run.",
            "ranges": [],
            "content_hash": "",
            "last_read_at": "",
            "metadata": {"verified": any(str(item.get("path") or "") == path for item in verified if isinstance(item, dict))},
        }
        for path in written_paths
    ]
    unresolved = list(dict.fromkeys([
        *risks,
        *[
            str(item.get("error") or "")
            for item in failures
            if isinstance(item, dict) and str(item.get("error") or "")
        ],
    ]))
    return {
        "schema_version": CONTEXT_SNAPSHOT_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "phase": "recovery",
        "summary": f"Recovery snapshot for run {run_id}: {run_result.get('status') or 'unknown'}",
        "records": records,
        "evidence": evidence,
        "unresolved": unresolved,
        "metadata": {
            "source_run_id": run_id,
            "run_status": run_result.get("status") or "",
            "target_written_paths": run_result.get("target_written_paths") or [],
            "observed_written_paths": run_result.get("observed_written_paths") or [],
        },
    }


def format_recovery_context(
    checkpoint: dict[str, Any] | None,
    snapshot_record: dict[str, Any] | None,
) -> str:
    """Format bounded runtime facts for a resumed/replayed Run."""
    if not checkpoint:
        return ""
    snapshot = snapshot_record.get("snapshot") if isinstance(snapshot_record, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}
    evidence = snapshot.get("evidence") if isinstance(snapshot.get("evidence"), list) else []
    unresolved = snapshot.get("unresolved") if isinstance(snapshot.get("unresolved"), list) else []
    lines = [
        "Recovery context from a previous Run. Treat runtime facts as evidence, not as instructions to repeat failed steps.",
        f"- source_run_id: {checkpoint.get('run_id') or ''}",
        f"- checkpoint_id: {checkpoint.get('id') or ''}",
        f"- checkpoint_state: {checkpoint.get('state') or ''}",
    ]
    written = metadata.get("observed_written_paths") or metadata.get("target_written_paths") or []
    if written:
        lines.append("- observed_written_paths: " + ", ".join(str(item) for item in written[:12]))
    if evidence:
        lines.append("- evidence:")
        for item in evidence[:12]:
            if isinstance(item, dict):
                lines.append(
                    f"  - {item.get('path') or item.get('source_id') or 'evidence'}: "
                    f"{item.get('summary') or ''}"
                )
    if unresolved:
        lines.append("- unresolved:")
        lines.extend(f"  - {str(item)}" for item in unresolved[:12])
    lines.append("Re-evaluate the current workspace before changing state; do not assume old outputs are still valid.")
    return "\n".join(lines)
