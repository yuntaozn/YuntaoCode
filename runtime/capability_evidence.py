"""Capability evidence summaries derived from tool events.

Capability metadata is declared by ToolSpec and observed from tool outputs.
This module keeps those facts available for RunResult, Runbook, diagnostics,
replay fixtures, and future evaluation without turning them into execution
policy.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from runtime.agent_strategy.tool_event_roles import event_path_hints


CAPABILITY_EVIDENCE_SCHEMA_VERSION = "capability_evidence_summary.v1"


def build_capability_evidence_summary(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact capability evidence view from tool events."""
    events = [event for event in tool_events if isinstance(event, dict)]
    requested = _requested_capability_ids(task_contract)
    observed = _unique(
        capability_id
        for event in events
        for capability_id in _event_capability_ids(event)
    )
    event_summaries = [
        _capability_event(index, event)
        for index, event in enumerate(events)
    ]
    status_counts = Counter(str(event.get("status") or "") for event in events)
    return {
        "schema_version": CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        "kind": "capability_evidence_summary",
        "requested_capability_ids": requested,
        "observed_capability_ids": observed,
        "unobserved_requested_capability_ids": [
            capability_id for capability_id in requested if capability_id not in set(observed)
        ],
        "tool_event_count": len(events),
        "status_counts": dict(sorted(status_counts.items())),
        "declared_effects": _unique(
            value
            for event in events
            for value in _string_list(event.get("declared_effects"))
        ),
        "observed_effects": _unique(
            value
            for event in events
            for value in _output_string_list(event, "effects")
        ),
        "declared_roles": _unique(
            value
            for event in events
            for value in _string_list(event.get("declared_roles"))
        ),
        "observed_roles": _unique(
            value
            for event in events
            for value in _output_string_list(event, "roles")
        ),
        "artifacts": _unique(
            value
            for event in events
            for value in _event_artifacts(event)
        ),
        "verification_strengths": _unique(
            value
            for event in events
            for value in _event_verification_strengths(event)
        ),
        "events": event_summaries[-50:],
    }


def _capability_event(index: int, event: dict[str, Any]) -> dict[str, Any]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    artifacts = _event_artifacts(event)
    result = {
        "index": index,
        "tool": str(event.get("tool") or event.get("name") or ""),
        "status": str(event.get("status") or ""),
        "capability_ids": _event_capability_ids(event),
        "declared_effects": _string_list(event.get("declared_effects")),
        "observed_effects": _string_list(output.get("effects")),
        "declared_roles": _string_list(event.get("declared_roles")),
        "observed_roles": _string_list(output.get("roles")),
        "artifacts": artifacts,
        "verification_strength": _first_text(_event_verification_strengths(event)),
        "paths": sorted(event_path_hints(event)),
    }
    if str(event.get("error") or ""):
        result["error"] = _truncate(event.get("error"), 500)
    return result


def _requested_capability_ids(task_contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(task_contract, dict):
        return []
    values: list[str] = []
    for key in ("capability_id", "capability_ids", "target_capability_ids"):
        value = task_contract.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    for item in task_contract.get("deliverables") or []:
        if isinstance(item, dict):
            for key in ("capability_id", "target_capability_id"):
                if item.get(key):
                    values.append(str(item[key]))
    return _unique(values)


def _event_capability_ids(event: dict[str, Any]) -> list[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values: list[str] = []
    for source in (event, output):
        for key in ("declared_capability", "capability", "capability_id"):
            if source.get(key):
                values.append(str(source[key]))
    return _unique(values)


def _event_artifacts(event: dict[str, Any]) -> list[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values: list[str] = []
    values.extend(_string_list(event.get("artifacts")))
    values.extend(_string_list(output.get("artifacts")))
    for key in ("artifact", "artifact_kind", "format", "type"):
        if output.get(key):
            values.append(str(output[key]))
    if event.get("artifact_kind"):
        values.append(str(event["artifact_kind"]))
    return _unique(values)


def _event_verification_strengths(event: dict[str, Any]) -> list[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values = [
        event.get("declared_verification_strength"),
        event.get("verification_strength"),
        output.get("verification_strength"),
    ]
    return _unique(str(item) for item in values if str(item or "").strip())


def _output_string_list(event: dict[str, Any], key: str) -> list[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    return _string_list(output.get(key))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique(str(item) for item in value if str(item or "").strip())


def _first_text(values: list[str]) -> str:
    return values[0] if values else ""


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."
