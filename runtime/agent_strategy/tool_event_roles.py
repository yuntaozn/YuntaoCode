"""Task-contract-aware roles for tool events.

Tool IDs tell the runtime whether an action can change local state.  They do
not, by themselves, tell whether the action satisfied the user's goal.  This
module maps tool events to task roles using the model-declared task contract
plus runtime facts such as paths and outputs.
"""

from __future__ import annotations

from typing import Any

from .classifiers import (
    canonical_tool_id,
    is_meaningful_verification_event,
    is_write_tool,
)


DELIVERABLE = "deliverable"
EVIDENCE = "evidence"
DRAFT = "draft"
TEMPORARY = "temporary"
VERIFICATION = "verification"
STATE_CHANGE = "state_change"
UNKNOWN = "unknown"
EXTERNAL_STATE_CHANGE = "external_state_change"


DRAFT_TOOL_IDS: frozenset[str] = frozenset({
    "filesystem.create_text_draft",
    "filesystem.append_text_chunk",
    "filesystem.inspect_text_draft",
    "document.create_draft",
    "document.append_draft_section",
    "document.add_draft_citation",
    "document.inspect_draft",
})

TEMPORARY_TOOL_IDS: frozenset[str] = frozenset({
    "filesystem.write_temp_file",
})

EVIDENCE_TOOL_IDS: frozenset[str] = frozenset({
    "filesystem.scan_folder",
    "filesystem.read_file",
    "filesystem.read_text_preview",
    "document.extract_docx_outline",
    "document.extract_pdf_text_preview",
    "web.extract_text",
    "web.render_page",
    "web.collect_site_assets",
})


def classify_tool_event_role(
    event: dict[str, Any],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
    deliverable_paths: set[str] | None = None,
) -> str:
    """Return the role this event played in the current task."""
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    paths = event_path_hints(event)
    contract_paths = deliverable_paths or contract_deliverable_paths(task_contract)
    effects = event_effects(event)
    declared_roles = event_declared_roles(event)
    deliverable_kinds = contract_deliverable_kinds(task_contract)

    if paths and contract_paths and any(_path_matches_any(path, contract_paths) for path in paths):
        if (
            _status_is_success_or_partial(event)
            and _can_be_deliverable_for_contract(event, task_contract)
        ):
            return DELIVERABLE
        if _is_verification_event(event, mode, written_paths=contract_paths):
            return VERIFICATION

    if (
        _status_is_success_or_partial(event)
        and EXTERNAL_STATE_CHANGE in effects
        and (
            "external_state" in deliverable_kinds
            or (
                isinstance(task_contract, dict)
                and task_contract.get("requires_state_change")
                and not task_contract.get("requires_write")
            )
        )
    ):
        return DELIVERABLE

    if tool_id in DRAFT_TOOL_IDS:
        return DRAFT
    if tool_id in TEMPORARY_TOOL_IDS:
        return TEMPORARY
    if tool_id in EVIDENCE_TOOL_IDS:
        return EVIDENCE
    if VERIFICATION in declared_roles and _status_is_success_or_partial(event):
        return VERIFICATION

    if _status_is_success_or_partial(event) and _can_be_deliverable_for_contract(event, task_contract):
        if not contract_paths or _contract_allows_alternative_path(event, task_contract):
            return DELIVERABLE
        return STATE_CHANGE
    if _is_verification_event(event, mode, written_paths=contract_paths):
        return VERIFICATION
    return UNKNOWN


def successful_deliverable_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    contract_paths = contract_deliverable_paths(task_contract)
    return [
        event
        for event in tool_events
        if str(event.get("status") or "") in {"success", "partial"}
        and classify_tool_event_role(
            event,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
            deliverable_paths=contract_paths,
        ) == DELIVERABLE
    ]


def failed_deliverable_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    contract_paths = contract_deliverable_paths(task_contract)
    result: list[dict[str, Any]] = []
    for event in tool_events:
        if str(event.get("status") or "") != "failure":
            continue
        tool_id = canonical_tool_id(str(event.get("tool") or ""))
        if not _can_be_deliverable_for_contract(event, task_contract):
            continue
        paths = event_path_hints(event)
        if (
            not contract_paths
            or _contract_allows_alternative_path(event, task_contract)
            or (paths and any(_path_matches_any(path, contract_paths) for path in paths))
        ):
            result.append(event)
    return result


def deliverable_verification_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    deliverables = successful_deliverable_events(
        tool_events,
        task_contract=task_contract,
        workspace_path=workspace_path,
        mode=mode,
    )
    if not deliverables:
        return []

    deliverable_ids = {id(event) for event in deliverables}
    latest_index = max(index for index, event in enumerate(tool_events) if id(event) in deliverable_ids)
    deliverable_paths = contract_deliverable_paths(task_contract)
    for event in deliverables:
        deliverable_paths.update(event_path_hints(event))

    scoped = tool_events[latest_index:]
    return [
        event
        for event in scoped
        if _is_verification_event(event, mode, written_paths=deliverable_paths)
    ]


def contract_deliverable_paths(task_contract: dict[str, Any] | None) -> set[str]:
    if not isinstance(task_contract, dict):
        return set()
    result: set[str] = set()
    for item in task_contract.get("deliverables") or []:
        if not isinstance(item, dict):
            continue
        for key in ("path_hint", "path", "output_path"):
            path = _normalize_path_hint(item.get(key))
            if path:
                result.add(path)
    return result


def contract_deliverable_kinds(task_contract: dict[str, Any] | None) -> set[str]:
    if not isinstance(task_contract, dict):
        return set()
    return {
        str(item.get("kind") or "").strip().lower()
        for item in task_contract.get("deliverables") or []
        if isinstance(item, dict) and str(item.get("kind") or "").strip()
    }


def deliverable_path_deviations(
    events: list[dict[str, Any]],
    task_contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return successful deliverables that used a different hinted path."""
    hinted_paths = contract_deliverable_paths(task_contract)
    if not hinted_paths:
        return []
    deviations: list[dict[str, Any]] = []
    for event in events:
        paths = event_path_hints(event)
        if not paths or any(_path_matches_any(path, hinted_paths) for path in paths):
            continue
        deviations.append({
            "tool": canonical_tool_id(str(event.get("tool") or "")),
            "expected_path_hints": sorted(hinted_paths),
            "actual_paths": sorted(paths),
        })
    return deviations


def event_effects(event: dict[str, Any]) -> set[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values = event.get("effects") or output.get("effects") or []
    if not isinstance(values, list):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}


def event_declared_roles(event: dict[str, Any]) -> set[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values = event.get("roles") or output.get("roles") or []
    if not isinstance(values, list):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}


def event_path_hints(event: dict[str, Any]) -> set[str]:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values = output.get("paths") if isinstance(output.get("paths"), list) else []
    paths = {
        _normalize_path_hint(value)
        for value in values
        if _normalize_path_hint(value)
    }
    for key in ("path", "output_path", "index_path", "manifest_path"):
        path = _normalize_path_hint(output.get(key) or event_input.get(key))
        if path:
            paths.add(path)
    return paths


def _can_be_deliverable_event(event: dict[str, Any]) -> bool:
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if tool_id in DRAFT_TOOL_IDS or tool_id in TEMPORARY_TOOL_IDS:
        return False
    return (
        is_write_tool(tool_id)
        or EXTERNAL_STATE_CHANGE in event_effects(event)
        or DELIVERABLE in event_declared_roles(event)
    )


def _can_be_deliverable_for_contract(
    event: dict[str, Any],
    task_contract: dict[str, Any] | None,
) -> bool:
    if not _can_be_deliverable_event(event):
        return False
    deliverable_kinds = contract_deliverable_kinds(task_contract)
    if not deliverable_kinds:
        return True

    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if is_write_tool(tool_id):
        return bool(deliverable_kinds & {"file", "code", "document"})
    if EXTERNAL_STATE_CHANGE in event_effects(event):
        return "external_state" in deliverable_kinds
    if DELIVERABLE in event_declared_roles(event):
        return bool(
            event_path_hints(event)
            and deliverable_kinds & {"file", "code", "document"}
        )
    return False


def _contract_allows_alternative_path(
    event: dict[str, Any],
    task_contract: dict[str, Any] | None,
) -> bool:
    if not isinstance(task_contract, dict):
        return True
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if not is_write_tool(tool_id) and not (
        DELIVERABLE in event_declared_roles(event)
        and event_path_hints(event)
    ):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("kind") or "").strip().lower() in {"file", "code", "document"}
        and str(item.get("path_policy") or "hint").strip().lower() != "exact"
        for item in task_contract.get("deliverables") or []
    )


def _is_verification_event(
    event: dict[str, Any],
    mode: str | None,
    *,
    written_paths: set[str],
) -> bool:
    if (
        VERIFICATION in event_declared_roles(event)
        and _status_is_success_or_partial(event)
    ):
        return True
    return is_meaningful_verification_event(event, mode, written_paths=written_paths)


def _status_is_success_or_partial(event: dict[str, Any]) -> bool:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if output.get("error") is True:
        return False
    return str(event.get("status") or "") in {"success", "partial"}


def _normalize_path_hint(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


def _path_matches_any(path: str, candidates: set[str]) -> bool:
    normalized = _normalize_path_hint(path)
    if not normalized:
        return False
    for candidate in candidates:
        other = _normalize_path_hint(candidate)
        if not other:
            continue
        if normalized == other:
            return True
        if normalized.endswith("/" + other) or other.endswith("/" + normalized):
            return True
    return False
