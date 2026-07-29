"""Run-level recovery evidence for tool attempts that did not execute.

ToolAttemptRecovery gathers failed tool-call protocol, availability,
confirmation, and safety-boundary facts into one evidence-only record. It does
not choose a new tool, retry anything, mark the task impossible, or decide
whether the run is complete.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


TOOL_ATTEMPT_RECOVERY_SCHEMA_VERSION = "tool_attempt_recovery.v1"


def build_tool_attempt_recovery(
    tool_events: list[dict[str, Any]] | None,
    *,
    limit: int = 12,
) -> dict[str, Any]:
    """Build a bounded run-level summary from tool attempt observations."""

    observations = _observation_records(tool_events or [], limit=max(1, int(limit or 1)))
    reason_counts = Counter(str(item.get("reason") or "unknown") for item in observations)
    boundary_counts = Counter(str(item.get("boundary") or "runtime_boundary") for item in observations)
    recoverable = [item for item in observations if item.get("recoverable_by_model") is True]
    hard_boundaries = [item for item in observations if item.get("hard_runtime_boundary") is True]
    large_write_attempts = [
        item for item in observations
        if bool(item.get("flags", {}).get("large_write_like_payload"))
    ]
    model_facts = _model_facts(
        observations=observations,
        reason_counts=reason_counts,
        boundary_counts=boundary_counts,
        recoverable_count=len(recoverable),
        hard_boundary_count=len(hard_boundaries),
        large_write_count=len(large_write_attempts),
    )
    return {
        "schema_version": TOOL_ATTEMPT_RECOVERY_SCHEMA_VERSION,
        "kind": "tool_attempt_recovery",
        "boundary": "evidence_only",
        "source": "tool_attempt_observation",
        "counts": {
            "attempts": len(observations),
            "recoverable_by_model": len(recoverable),
            "hard_runtime_boundary": len(hard_boundaries),
            "large_write_like_payload": len(large_write_attempts),
        },
        "reason_counts": dict(reason_counts),
        "boundary_counts": dict(boundary_counts),
        "flags": {
            "has_attempts": bool(observations),
            "has_recoverable_attempts": bool(recoverable),
            "has_hard_runtime_boundary": bool(hard_boundaries),
            "has_large_write_like_payload": bool(large_write_attempts),
            "all_attempts_recoverable_by_model": bool(observations)
            and len(recoverable) == len(observations),
        },
        "attempts": observations,
        "model_facts": model_facts,
    }


def format_tool_attempt_recovery_for_model(recovery: dict[str, Any] | None) -> str:
    """Render recovery facts for model-facing evidence packs."""

    item = recovery if isinstance(recovery, dict) else {}
    if item.get("kind") != "tool_attempt_recovery":
        return ""
    counts = item.get("counts") if isinstance(item.get("counts"), dict) else {}
    if not counts.get("attempts"):
        return ""
    lines = [
        "Tool attempt recovery evidence:",
        f"- boundary: {item.get('boundary') or 'evidence_only'}",
        f"- attempts: {counts.get('attempts') or 0}",
        f"- recoverable_by_model: {counts.get('recoverable_by_model') or 0}",
        f"- hard_runtime_boundary: {counts.get('hard_runtime_boundary') or 0}",
    ]
    _append_counts(lines, "reasons", item.get("reason_counts"))
    _append_counts(lines, "boundaries", item.get("boundary_counts"))
    _append_list(lines, "model facts", item.get("model_facts"))
    attempts = item.get("attempts") if isinstance(item.get("attempts"), list) else []
    if attempts:
        lines.append("- recent attempts:")
        for attempt in attempts[-6:]:
            if not isinstance(attempt, dict):
                continue
            pieces = [
                str(attempt.get("tool") or "unknown"),
                str(attempt.get("reason") or "unknown"),
                f"boundary={attempt.get('boundary') or 'runtime_boundary'}",
            ]
            missing = _string_list(attempt.get("missing_fields"), limit=4)
            if missing:
                pieces.append("missing=" + ",".join(missing))
            if attempt.get("recoverable_by_model") is True:
                pieces.append("recoverable=true")
            if attempt.get("hard_runtime_boundary") is True:
                pieces.append("hard_boundary=true")
            lines.append("  - " + " | ".join(pieces))
    return "\n".join(lines)


def summarize_tool_attempt_recovery_for_decision(
    recovery: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a compact summary suitable for completion decisions."""

    item = recovery if isinstance(recovery, dict) else {}
    if item.get("kind") != "tool_attempt_recovery":
        return {}
    counts = item.get("counts") if isinstance(item.get("counts"), dict) else {}
    flags = item.get("flags") if isinstance(item.get("flags"), dict) else {}
    return {
        "schema_version": str(item.get("schema_version") or ""),
        "kind": "tool_attempt_recovery",
        "attempts": _safe_int(counts.get("attempts")),
        "recoverable_by_model": _safe_int(counts.get("recoverable_by_model")),
        "hard_runtime_boundary": _safe_int(counts.get("hard_runtime_boundary")),
        "reason_counts": _compact_counts(item.get("reason_counts"), limit=8),
        "boundary_counts": _compact_counts(item.get("boundary_counts"), limit=8),
        "has_recoverable_attempts": bool(flags.get("has_recoverable_attempts")),
        "has_hard_runtime_boundary": bool(flags.get("has_hard_runtime_boundary")),
        "has_large_write_like_payload": bool(flags.get("has_large_write_like_payload")),
        "model_facts": _string_list(item.get("model_facts"), limit=8),
    }


def _observation_records(
    tool_events: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, event in enumerate(tool_events):
        if not isinstance(event, dict):
            continue
        observation = _tool_attempt_observation(event)
        if not observation:
            continue
        input_summary = _dict(observation.get("input_summary"))
        missing_fields = _string_list(observation.get("missing_fields"), limit=12)
        model_decision = _string_list(observation.get("model_decision"), limit=6)
        record = {
            "event_index": index,
            "tool": str(observation.get("tool") or event.get("tool") or "unknown"),
            "status": str(observation.get("status") or event.get("status") or "not_executed"),
            "reason": str(observation.get("reason") or "unknown"),
            "boundary": str(observation.get("boundary") or "runtime_boundary"),
            "recoverable_by_model": bool(observation.get("recoverable_by_model")),
            "hard_runtime_boundary": bool(observation.get("hard_runtime_boundary")),
            "missing_fields": missing_fields,
            "input_summary": _input_summary_digest(input_summary),
            "available_tool_ids": _string_list(observation.get("available_tool_ids"), limit=8),
            "model_decision": model_decision,
            "message": _short(str(observation.get("message") or ""), 320),
            "flags": {
                "large_write_like_payload": _large_write_like_payload(input_summary),
                "has_missing_fields": bool(missing_fields),
                "has_available_tool_ids": bool(observation.get("available_tool_ids")),
            },
        }
        records.append(record)
    if len(records) <= limit:
        return records
    return records[-limit:]


def _tool_attempt_observation(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("tool_attempt_observation")
    if isinstance(value, dict) and value.get("kind") == "tool_attempt_observation":
        return value
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    value = output.get("observation")
    if isinstance(value, dict) and value.get("kind") == "tool_attempt_observation":
        return value
    return {}


def _model_facts(
    *,
    observations: list[dict[str, Any]],
    reason_counts: Counter[str],
    boundary_counts: Counter[str],
    recoverable_count: int,
    hard_boundary_count: int,
    large_write_count: int,
) -> list[str]:
    if not observations:
        return []
    facts = [
        f"tool_attempts={len(observations)}; recoverable={recoverable_count}; hard_boundary={hard_boundary_count}",
    ]
    if reason_counts:
        facts.append("attempt_reasons=" + _count_text(reason_counts))
    if boundary_counts:
        facts.append("attempt_boundaries=" + _count_text(boundary_counts))
    missing = sorted({
        field
        for item in observations
        for field in _string_list(item.get("missing_fields"), limit=12)
    })
    if missing:
        facts.append("missing_fields=" + ",".join(missing[:12]))
    if large_write_count:
        facts.append(f"large_write_like_payload_attempts={large_write_count}")
    hard_tools = [
        str(item.get("tool") or "unknown")
        for item in observations
        if item.get("hard_runtime_boundary")
    ]
    if hard_tools:
        facts.append("hard_boundary_tools=" + ",".join(hard_tools[:8]))
    return facts


def _input_summary_digest(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    result: dict[str, Any] = {
        "keys": _string_list(value.get("keys"), limit=12),
    }
    for key in (
        "path",
        "content_chars",
        "patch_chars",
        "raw_argument_chars",
        "command",
    ):
        if value.get(key) not in (None, "", [], {}):
            result[key] = value.get(key)
    return result


def _large_write_like_payload(input_summary: dict[str, Any]) -> bool:
    for key in ("content_chars", "patch_chars", "raw_argument_chars"):
        try:
            if int(input_summary.get(key) or 0) >= 12_000:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _append_counts(lines: list[str], title: str, value: Any) -> None:
    counts = _compact_counts(value, limit=8)
    if not counts:
        return
    lines.append(
        f"- {title}: "
        + ", ".join(f"{key}:{counts[key]}" for key in sorted(counts))
    )


def _append_list(lines: list[str], title: str, value: Any) -> None:
    items = _string_list(value, limit=8)
    if not items:
        return
    lines.append(f"- {title}:")
    lines.extend(f"  - {_short(item, 240)}" for item in items)


def _compact_counts(value: Any, *, limit: int) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, count in sorted(value.items(), key=lambda item: str(item[0]))[:limit]:
        text = str(key or "").strip()
        if text:
            result[text] = _safe_int(count)
    return result


def _count_text(counts: Counter[str]) -> str:
    return ",".join(
        f"{key}:{counts[key]}"
        for key in sorted(counts)
        if key
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _short(text: Any, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"
