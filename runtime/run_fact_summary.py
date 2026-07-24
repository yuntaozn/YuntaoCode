"""Compact runtime facts shared by recovery prompts and final summaries.

The structures in this module are intentionally deterministic.  They do not
decide whether a task is complete and they do not prescribe a strategy; they
only package what the runtime observed so the model can make the next
judgement from the same evidence the UI and tests can audit.
"""

from __future__ import annotations

from typing import Any

from runtime.verification_closure import format_verification_closure_for_model


RUN_FACT_SUMMARY_VERSION = "run_fact_summary.v1"


def build_run_fact_summary(
    *,
    workspace_path: str,
    tool_events: list[dict[str, Any]] | None,
    run_result: dict[str, Any] | None,
    task_contract: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    result = run_result if isinstance(run_result, dict) else {}
    contract = task_contract if isinstance(task_contract, dict) else {}
    events = tool_events if isinstance(tool_events, list) else []
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    changed_paths = _string_list(result.get("changed_paths"), limit=limit)
    written_paths = _string_list(
        result.get("target_written_paths")
        or result.get("written_paths")
        or result.get("observed_written_paths"),
        limit=limit,
    )
    verification = _verification_records(result.get("verification_evidence"), limit=limit)
    verification_closure = (
        result.get("verification_closure")
        if isinstance(result.get("verification_closure"), dict)
        else {}
    )
    failures = _failure_records(result, events, workspace_path, limit=limit)
    risks = _string_list(result.get("risks"), limit=limit * 2)
    completed = _completed_evidence(
        counts=counts,
        changed_paths=changed_paths,
        written_paths=written_paths,
        verification=verification,
    )
    remaining = _remaining_evidence(
        status=str(result.get("status") or ""),
        failures=failures,
        risks=risks,
        verification=verification,
        counts=counts,
    )
    return {
        "schema_version": RUN_FACT_SUMMARY_VERSION,
        "kind": "run_fact_summary",
        "workspace_path": str(workspace_path or ""),
        "goal": str(contract.get("goal") or "").strip(),
        "intent": str(contract.get("intent") or "").strip(),
        "status": str(result.get("status") or "unknown"),
        "counts": {
            "tool_events": int(counts.get("tool_events") or len(events) or 0),
            "deliverable_successes": int(counts.get("deliverable_successes") or 0),
            "write_successes": int(counts.get("write_successes") or 0),
            "verification_successes": int(counts.get("verification_successes") or 0),
            "test_successes": int(counts.get("test_successes") or 0),
            "failures": int(counts.get("failures") or len(failures) or 0),
            "blocking_failures": int(counts.get("blocking_failures") or 0),
            "degraded_failures": int(counts.get("degraded_failures") or 0),
            "recovered_failures": int(counts.get("recovered_failures") or 0),
        },
        "changed_paths": changed_paths,
        "written_paths": written_paths,
        "verification": verification,
        "verification_closure": verification_closure,
        "failures": failures,
        "risks": risks,
        "completed_evidence": completed,
        "remaining_evidence": remaining,
        "decision_required": [
            "Use these facts to decide whether to continue with tools, verify, repair, or finalize.",
            "Do not claim completion beyond observed deliverables and verification evidence.",
        ],
    }


def build_tool_failure_fact_summary(
    *,
    workspace_path: str,
    tool_events: list[dict[str, Any]] | None,
    limit: int = 6,
) -> dict[str, Any]:
    events = tool_events if isinstance(tool_events, list) else []
    failed = [
        _event_failure_record(workspace_path, event)
        for event in events
        if _event_failed(event)
    ]
    failed = [item for item in failed if item]
    latest = failed[-1] if failed else {}
    repeated_route = ""
    if latest:
        same_route_count = sum(
            1
            for item in failed
            if item.get("tool") == latest.get("tool")
            and item.get("path") == latest.get("path")
            and item.get("reason") == latest.get("reason")
        )
        if same_route_count >= 2:
            repeated_route = f"{latest.get('tool') or 'unknown'}:{latest.get('path') or ''}:{latest.get('reason') or latest.get('error') or ''}"
    return {
        "schema_version": RUN_FACT_SUMMARY_VERSION,
        "kind": "tool_failure_fact_summary",
        "workspace_path": str(workspace_path or ""),
        "latest_failure": latest,
        "recent_failures": failed[-limit:],
        "repeated_route": repeated_route,
        "decision_required": [
            "Choose the next route from the observed failure facts.",
            "If the same route repeated without progress, change strategy or finalize honestly.",
        ],
    }


def format_run_fact_summary(summary: dict[str, Any]) -> str:
    lines = [
        "Runtime fact package:",
        f"- status: {summary.get('status') or 'unknown'}",
    ]
    goal = str(summary.get("goal") or "").strip()
    if goal:
        lines.append(f"- goal: {_short(goal, 240)}")
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    if counts:
        lines.append(
            "- counts: "
            f"tools={counts.get('tool_events', 0)}, "
            f"deliverables={counts.get('deliverable_successes', 0)}, "
            f"writes={counts.get('write_successes', 0)}, "
            f"verifications={counts.get('verification_successes', 0)}, "
            f"tests={counts.get('test_successes', 0)}, "
            f"failures={counts.get('failures', 0)}"
        )
    _append_list(lines, "completed evidence", summary.get("completed_evidence"))
    _append_list(lines, "changed paths", summary.get("changed_paths"))
    _append_list(lines, "written paths", summary.get("written_paths"))
    verification = summary.get("verification")
    if isinstance(verification, list) and verification:
        lines.append("- verification evidence:")
        for item in verification[:8]:
            if not isinstance(item, dict):
                continue
            modalities = ",".join(_string_list(item.get("modalities"), limit=4))
            suffix = f" [{modalities}]" if modalities else ""
            path = f" {item.get('path')}" if item.get("path") else ""
            lines.append(f"  - {item.get('tool') or 'unknown'}{path}{suffix}")
    closure_text = format_verification_closure_for_model(
        summary.get("verification_closure")
        if isinstance(summary.get("verification_closure"), dict)
        else None
    ).strip()
    if closure_text:
        lines.append(closure_text)
    failures = summary.get("failures")
    if isinstance(failures, list) and failures:
        lines.append("- failures:")
        for item in failures[:8]:
            if not isinstance(item, dict):
                continue
            bits = [str(item.get("tool") or "unknown")]
            if item.get("path"):
                bits.append(str(item["path"]))
            if item.get("impact"):
                bits.append(f"impact={item['impact']}")
            error = _short(str(item.get("error") or item.get("reason") or ""), 220)
            suffix = f": {error}" if error else ""
            lines.append(f"  - {' | '.join(bits)}{suffix}")
    _append_list(lines, "risks", summary.get("risks"))
    _append_list(lines, "remaining evidence", summary.get("remaining_evidence"))
    _append_list(lines, "model decision", summary.get("decision_required"))
    return "\n".join(lines)


def format_tool_failure_fact_summary(summary: dict[str, Any]) -> str:
    lines = ["Runtime failure facts:"]
    latest = summary.get("latest_failure")
    if isinstance(latest, dict) and latest:
        label = str(latest.get("tool") or "unknown")
        if latest.get("path"):
            label += f" | {latest['path']}"
        reason = str(latest.get("reason") or latest.get("error") or "").strip()
        lines.append(f"- latest failure: {label}" + (f": {_short(reason, 260)}" if reason else ""))
    repeated = str(summary.get("repeated_route") or "").strip()
    if repeated:
        lines.append(f"- repeated route: {_short(repeated, 260)}")
    recent = summary.get("recent_failures")
    if isinstance(recent, list) and recent:
        lines.append("- recent failures:")
        for item in recent[-6:]:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or item.get("error") or "").strip()
            label = str(item.get("tool") or "unknown")
            if item.get("path"):
                label += f" | {item['path']}"
            lines.append(f"  - {label}" + (f": {_short(reason, 180)}" if reason else ""))
    _append_list(lines, "model decision", summary.get("decision_required"))
    return "\n".join(lines)


def _completed_evidence(
    *,
    counts: dict[str, Any],
    changed_paths: list[str],
    written_paths: list[str],
    verification: list[dict[str, Any]],
) -> list[str]:
    evidence: list[str] = []
    if written_paths:
        evidence.append(f"observed target deliverable/write paths: {', '.join(written_paths[:6])}")
    elif changed_paths:
        evidence.append(f"observed changed paths: {', '.join(changed_paths[:6])}")
    external_changes = int(counts.get("external_state_changes") or 0)
    if external_changes:
        evidence.append(f"observed external state changes: {external_changes}")
    if verification:
        evidence.append(f"observed verification events: {len(verification)}")
    return evidence


def _remaining_evidence(
    *,
    status: str,
    failures: list[dict[str, Any]],
    risks: list[str],
    verification: list[dict[str, Any]],
    counts: dict[str, Any],
) -> list[str]:
    remaining: list[str] = []
    if failures:
        remaining.append("there are unresolved or degraded failure records")
    if risks:
        remaining.append("runtime risks remain: " + ", ".join(risks[:8]))
    if int(counts.get("write_successes") or 0) and not verification:
        remaining.append("deliverable exists but no verification evidence was observed")
    if status in {"partial", "failure", "stopped"}:
        remaining.append(f"run status is {status}, so the final answer must not overclaim success")
    return remaining


def _failure_records(
    result: dict[str, Any],
    events: list[dict[str, Any]],
    workspace_path: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    details = result.get("failure_details") if isinstance(result.get("failure_details"), list) else []
    failures = result.get("failures") if isinstance(result.get("failures"), list) else []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(failures[:limit]):
        if not isinstance(item, dict):
            continue
        detail = details[index] if index < len(details) and isinstance(details[index], dict) else {}
        records.append({
            "tool": str(item.get("tool") or detail.get("tool") or "unknown"),
            "path": str(item.get("path") or detail.get("path") or "").strip(),
            "error": _short(str(item.get("error") or "").strip(), 500),
            "role": str(detail.get("role") or "").strip(),
            "impact": str(detail.get("impact") or "").strip(),
        })
    if records:
        return records[:limit]
    event_records = [
        _event_failure_record(workspace_path, event)
        for event in events
        if _event_failed(event)
    ]
    return [item for item in event_records if item][:limit]


def _verification_records(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    records: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        records.append({
            "tool": str(item.get("tool") or "unknown"),
            "path": str(item.get("path") or "").strip(),
            "strength": str(item.get("strength") or "").strip(),
            "sufficient": bool(item.get("sufficient")),
            "modalities": _string_list(item.get("modalities"), limit=6),
        })
    return records


def _event_failure_record(workspace_path: str, event: dict[str, Any]) -> dict[str, Any]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    path = (
        output.get("path")
        or output.get("output_path")
        or event_input.get("output_path")
        or event_input.get("path")
        or ""
    )
    return {
        "tool": str(event.get("tool") or "unknown"),
        "path": _relative_path(workspace_path, str(path or "")),
        "error": _event_error(event),
        "reason": str(output.get("reason") or "").strip(),
    }


def _event_failed(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or "")
    if status == "failure":
        return True
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if output.get("error") is True:
        return True
    if output.get("timed_out") is True:
        return True
    if str(event.get("tool") or "") == "shell.run_command":
        try:
            return int(output.get("exit_code", 0) or 0) != 0
        except (TypeError, ValueError):
            return False
    return False


def _event_error(event: dict[str, Any]) -> str:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if output.get("timed_out") is True:
        return "command timed out"
    for key in ("error", "stderr", "stdout", "message", "reason"):
        value = event.get(key) if key == "error" else output.get(key)
        text = str(value or "").strip()
        if text:
            return _short(text, 500)
    if output.get("exit_code") is not None:
        return f"exit_code={output.get('exit_code')}"
    return ""


def _append_list(lines: list[str], title: str, value: Any) -> None:
    items = _string_list(value, limit=8)
    if not items:
        return
    lines.append(f"- {title}:")
    lines.extend(f"  - {_short(item, 260)}" for item in items)


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _relative_path(workspace_path: str, path: str) -> str:
    if not path:
        return ""
    workspace = str(workspace_path or "").replace("\\", "/").rstrip("/")
    candidate = path.replace("\\", "/")
    if workspace and candidate.lower().startswith((workspace + "/").lower()):
        return candidate[len(workspace) + 1:]
    return path


def _short(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"
