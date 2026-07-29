"""Context Pack builders for model-facing runtime facts.

Context Pack is the small, explicit set of facts a model sees for one phase of
a Run. Context Ledger is the audit view of those facts: where they came from,
how fresh they are, and how trustworthy they are.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from runtime.core.context import ContextRecord, select_records_for_phase
from runtime.agent_strategy.task_lineage import format_task_candidates_for_model
from runtime.verification_closure import format_verification_closure_for_model
from runtime.workspace_snapshot import workspace_snapshot_summary


CONTEXT_PACK_SCHEMA_VERSION = "context_pack.v1"
CONTEXT_LEDGER_SCHEMA_VERSION = "context_ledger.v1"


def build_context_pack(
    *,
    phase: str,
    user_content: str,
    workspace_snapshot: dict[str, Any] | None = None,
    task_contract: dict[str, Any] | None = None,
    active_focus: dict[str, Any] | None = None,
    previous_contract: dict[str, Any] | None = None,
    task_lineage_availability: dict[str, Any] | None = None,
    task_candidates: list[dict[str, Any]] | None = None,
    memory_context: dict[str, Any] | None = None,
    capability_snapshot: dict[str, Any] | None = None,
    capability_preflight: dict[str, Any] | None = None,
    tool_events: list[dict[str, Any]] | None = None,
    execution_plan: dict[str, Any] | None = None,
    round_index: int | None = None,
    run_result: dict[str, Any] | None = None,
    assistant_content: str = "",
    context_hygiene_report: dict[str, Any] | None = None,
    task_id: str = "",
    limit: int = 12,
) -> dict[str, Any]:
    """Build a bounded context pack for one runtime phase."""
    records = _candidate_records(
        phase=phase,
        user_content=user_content,
        workspace_snapshot=workspace_snapshot,
        task_contract=task_contract,
        active_focus=active_focus,
        previous_contract=previous_contract,
        task_lineage_availability=task_lineage_availability,
        task_candidates=task_candidates,
        memory_context=memory_context,
        capability_snapshot=capability_snapshot,
        capability_preflight=capability_preflight,
        tool_events=tool_events,
        execution_plan=execution_plan,
        round_index=round_index,
        run_result=run_result,
        assistant_content=assistant_content,
        context_hygiene_report=context_hygiene_report,
        task_id=task_id,
    )
    selected = select_records_for_phase(records, phase, limit=limit)
    record_dicts = [record.to_dict() for record in selected]
    ledger = build_context_ledger(record_dicts, phase=phase)
    return {
        "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
        "kind": "context_pack",
        "phase": str(phase or ""),
        "record_count": len(record_dicts),
        "records": record_dicts,
        "ledger": ledger,
    }


def build_context_ledger(records: list[dict[str, Any]], *, phase: str) -> dict[str, Any]:
    """Build an audit ledger for selected context records."""
    ledger_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        content = str(record.get("content") or "")
        ledger_records.append({
            "index": index,
            "kind": str(record.get("kind") or ""),
            "source_id": str(record.get("source_id") or ""),
            "source_type": str(record.get("source_type") or ""),
            "trust": str(record.get("trust") or ""),
            "freshness": str(record.get("freshness") or ""),
            "task_id": str(record.get("task_id") or ""),
            "token_estimate": _safe_int(record.get("token_estimate")),
            "content_hash": _content_hash(content),
            "content_preview": _truncate(content, 180),
            "metadata_keys": sorted(
                str(key) for key in (record.get("metadata") or {}).keys()
            )
            if isinstance(record.get("metadata"), dict)
            else [],
        })
    return {
        "schema_version": CONTEXT_LEDGER_SCHEMA_VERSION,
        "kind": "context_ledger",
        "phase": str(phase or ""),
        "record_count": len(ledger_records),
        "records": ledger_records,
    }


def format_context_pack_for_prompt(pack: dict[str, Any] | None) -> str:
    """Format context facts for a model prompt."""
    if not isinstance(pack, dict) or not pack.get("records"):
        return ""
    compact_records: list[dict[str, Any]] = []
    for record in pack.get("records") or []:
        if not isinstance(record, dict):
            continue
        kind = str(record.get("kind") or "")
        compact_records.append({
            "kind": kind,
            "content": _truncate(record.get("content"), _model_record_char_limit(kind)),
            "source_type": record.get("source_type"),
            "trust": record.get("trust"),
            "freshness": record.get("freshness"),
        })
    prompt_payload = {
        "schema_version": pack.get("schema_version"),
        "phase": pack.get("phase"),
        "records": compact_records[:12],
        "ledger": _model_facing_ledger(pack.get("ledger")),
    }
    text = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))
    return (
        "Context Pack for this model call:\n"
        f"{text}\n"
        "Context Pack rule: these are selected runtime facts and source labels, "
        "not hard instructions or a forced route. The current user request still "
        "has priority; use older context only when it is relevant."
    )


def _model_facing_ledger(ledger: Any) -> dict[str, Any]:
    """Return ledger metadata without repeating record content in the prompt.

    The full Context Ledger remains in run events, diagnostics, and workbench
    views.  The model prompt only needs source/trust/freshness indexes; putting
    ``content_preview`` next to ``records`` duplicates historical facts and can
    accidentally overweight old context.
    """

    if not isinstance(ledger, dict):
        return {}
    records: list[dict[str, Any]] = []
    for item in ledger.get("records") or []:
        if not isinstance(item, dict):
            continue
        records.append({
            "index": item.get("index"),
            "kind": item.get("kind"),
            "source_id": item.get("source_id"),
            "source_type": item.get("source_type"),
            "trust": item.get("trust"),
            "freshness": item.get("freshness"),
            "token_estimate": item.get("token_estimate"),
            "content_hash": item.get("content_hash"),
            "metadata_keys": item.get("metadata_keys") or [],
        })
    return {
        "schema_version": ledger.get("schema_version"),
        "kind": ledger.get("kind"),
        "phase": ledger.get("phase"),
        "record_count": ledger.get("record_count"),
        "records": records[:12],
    }


def is_context_pack_prompt_for_phase(value: Any, phase: str) -> bool:
    """Return whether a model message is a Context Pack prompt for *phase*."""
    text = str(value or "")
    if not text.startswith("Context Pack for this model call:\n"):
        return False
    return f'"phase":"{str(phase or "")}"' in text[:4000]


def context_pack_summary(pack: dict[str, Any] | None) -> dict[str, Any]:
    """Return a stable summary for RunEvidence, Runbook, and diagnostics."""
    if not isinstance(pack, dict):
        return {}
    records = [item for item in pack.get("records") or [] if isinstance(item, dict)]
    ledger = pack.get("ledger") if isinstance(pack.get("ledger"), dict) else {}
    return {
        "schema_version": str(pack.get("schema_version") or ""),
        "kind": str(pack.get("kind") or ""),
        "phase": str(pack.get("phase") or ""),
        "record_count": len(records),
        "record_kinds": [
            str(item.get("kind") or "")
            for item in records
            if str(item.get("kind") or "")
        ],
        "ledger": ledger,
    }


def _candidate_records(
    *,
    phase: str,
    user_content: str,
    workspace_snapshot: dict[str, Any] | None,
    task_contract: dict[str, Any] | None,
    active_focus: dict[str, Any] | None,
    previous_contract: dict[str, Any] | None,
    task_lineage_availability: dict[str, Any] | None,
    task_candidates: list[dict[str, Any]] | None,
    memory_context: dict[str, Any] | None,
    capability_snapshot: dict[str, Any] | None,
    capability_preflight: dict[str, Any] | None,
    tool_events: list[dict[str, Any]] | None,
    execution_plan: dict[str, Any] | None,
    round_index: int | None,
    run_result: dict[str, Any] | None,
    assistant_content: str,
    context_hygiene_report: dict[str, Any] | None,
    task_id: str,
) -> list[ContextRecord]:
    records = [
        ContextRecord(
            kind="user_intent",
            content=_truncate(user_content, 1200),
            source_id="current_user_message",
            source_type="user_message",
            trust="user_provided",
            task_id=task_id,
            freshness="current",
            token_estimate=_estimate_tokens_fast(user_content),
        )
    ]
    memory_record = _memory_record(memory_context, task_id=task_id)
    if memory_record:
        records.append(memory_record)
    lineage_availability_record = _task_lineage_availability_record(
        task_lineage_availability,
        task_id=task_id,
    )
    if lineage_availability_record:
        records.append(lineage_availability_record)
    lineage_record = _task_lineage_record(task_candidates, task_id=task_id)
    if lineage_record:
        records.append(lineage_record)
    previous_record = _previous_contract_record(previous_contract, task_id=task_id)
    if previous_record:
        records.append(previous_record)
    focus_record = _active_focus_record(active_focus, task_id=task_id)
    if focus_record:
        records.append(focus_record)
    current_contract_record = _task_contract_record(task_contract, task_id=task_id)
    if current_contract_record:
        records.append(current_contract_record)
    workspace_record = _workspace_record(workspace_snapshot, task_id=task_id)
    if workspace_record:
        records.append(workspace_record)
    capability_record = _capability_record(
        capability_snapshot,
        capability_preflight,
        task_id=task_id,
    )
    if capability_record:
        records.append(capability_record)
    tool_result_record = _tool_events_record(tool_events, task_id=task_id)
    if tool_result_record:
        records.append(tool_result_record)
    execution_state_record = _execution_state_record(
        tool_events,
        execution_plan,
        round_index=round_index,
        task_id=task_id,
    )
    if execution_state_record:
        records.append(execution_state_record)
    tool_risk_record = _tool_risk_record(tool_events, task_id=task_id)
    if tool_risk_record:
        records.append(tool_risk_record)
    run_result_record = _run_result_record(run_result, task_id=task_id)
    if run_result_record:
        records.append(run_result_record)
    answer_record = _assistant_answer_record(assistant_content, task_id=task_id)
    if answer_record:
        records.append(answer_record)
    hygiene_record = _context_hygiene_record(context_hygiene_report, task_id=task_id)
    if hygiene_record:
        records.append(hygiene_record)
    return records


def _memory_record(
    memory_context: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    if not isinstance(memory_context, dict):
        return None
    used_ids = [
        str(item).strip()
        for item in memory_context.get("used_memory_ids") or []
        if str(item).strip()
    ]
    prompt = str(memory_context.get("prompt") or "").strip()
    if not used_ids or not prompt:
        return None
    content = (
        "Selected user memory for the current request. Treat it as advisory "
        "stored context that may be stale, not as a new user instruction:\n"
        f"{_truncate(prompt, 2400)}"
    )
    return ContextRecord(
        kind="memory",
        content=content,
        source_id="memory_selection",
        source_type="memory_store",
        trust="memory",
        task_id=task_id,
        freshness="stored",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "schema_version": str(memory_context.get("schema_version") or ""),
            "used_memory_ids": used_ids,
            "selected_count": len(used_ids),
            "workspace_id": str(memory_context.get("workspace_id") or ""),
        },
    )


def _workspace_record(snapshot: dict[str, Any] | None, *, task_id: str) -> ContextRecord | None:
    summary = workspace_snapshot_summary(snapshot)
    if not summary:
        return None
    extension_counts = summary.get("extension_counts") if isinstance(summary.get("extension_counts"), dict) else {}
    patterns = summary.get("observed_patterns") if isinstance(summary.get("observed_patterns"), list) else []
    notable_paths = summary.get("notable_paths") if isinstance(summary.get("notable_paths"), list) else []
    top_level_entries = summary.get("top_level_entries") if isinstance(summary.get("top_level_entries"), list) else []
    top_level_names = [
        str(item.get("name") or "")
        for item in top_level_entries
        if isinstance(item, dict) and str(item.get("name") or "")
    ][:20]
    pattern_ids = [
        str(item.get("id") or "")
        for item in patterns
        if isinstance(item, dict) and str(item.get("id") or "")
    ]
    extension_text = ", ".join(
        f"{key}:{value}"
        for key, value in list(extension_counts.items())[:12]
    )
    content = (
        f"Workspace {summary.get('name') or ''} at {summary.get('path') or ''}; "
        f"files={summary.get('file_count') or 0}; dirs={summary.get('directory_count') or 0}; "
        f"file_types={extension_text or 'none'}; "
        f"signals={', '.join(pattern_ids[:8]) or 'none'}; "
        f"top_level={', '.join(top_level_names) or 'none'}; "
        f"notable_paths={', '.join(str(item) for item in notable_paths[:12]) or 'none'}"
    )
    return ContextRecord(
        kind="workspace_summary",
        content=content,
        source_id="workspace_snapshot",
        source_type="runtime_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={"snapshot": summary},
    )


def _previous_contract_record(
    previous_contract: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    if not isinstance(previous_contract, dict):
        return None
    goal = str(previous_contract.get("goal") or previous_contract.get("intent") or "").strip()
    if not goal:
        return None
    capability_ids = [
        str(item)
        for item in previous_contract.get("capability_ids") or []
        if str(item or "").strip()
    ]
    deliverables = previous_contract.get("deliverables") if isinstance(previous_contract.get("deliverables"), list) else []
    deliverable_kinds = [
        str(item.get("kind") or "")
        for item in deliverables
        if isinstance(item, dict) and str(item.get("kind") or "")
    ]
    content = (
        "Historical previous task contract reference, not the current goal by default: "
        f"{goal}; "
        f"intent={previous_contract.get('intent') or ''}; "
        f"capabilities={', '.join(capability_ids[:6]) or 'none'}; "
        f"deliverables={', '.join(deliverable_kinds[:6]) or 'none'}"
    )
    return ContextRecord(
        kind="previous_contract",
        content=content,
        source_id="previous_task_contract",
        source_type="run_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="recent",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "contract_goal": goal,
            "intent": previous_contract.get("intent") or "",
            "requires_write": bool(previous_contract.get("requires_write")),
            "requires_state_change": bool(previous_contract.get("requires_state_change")),
            "capability_ids": capability_ids[:6],
            "deliverable_kinds": deliverable_kinds[:6],
            "inheritance_rule": "historical_reference_only_unless_current_request_continues_it",
        },
    )


def _task_lineage_availability_record(
    availability: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    if not isinstance(availability, dict):
        return None
    candidate_count = _safe_int(availability.get("candidate_count"))
    if candidate_count <= 0 and not availability.get("available"):
        return None
    content = (
        "Historical task lineage candidates are available for this conversation, "
        "but their goals, paths, and routes are not included in this initial "
        "context. If the current request depends on earlier task state, the "
        "model task contract can request lineage facts; otherwise judge from "
        "the current user request and current workspace facts."
    )
    return ContextRecord(
        kind="task_lineage_availability",
        content=content,
        source_id="task_lineage_availability",
        source_type="conversation_history",
        trust="runtime_fact",
        task_id=task_id,
        freshness="recent",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "schema_version": str(availability.get("schema_version") or ""),
            "available": bool(availability.get("available")),
            "candidate_count": candidate_count,
            "candidate_content_exposure": str(
                availability.get("candidate_content_exposure") or "model_requested"
            ),
        },
    )


def _task_lineage_record(
    candidates: list[dict[str, Any]] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    content = format_task_candidates_for_model(candidates, limit=4)
    if not content:
        return None
    compact_candidates: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        compact_candidates.append({
            "candidate_id": candidate.get("candidate_id"),
            "lineage_rank": candidate.get("lineage_rank"),
            "recency_rank": candidate.get("recency_rank"),
            "user_request": candidate.get("user_request") or "",
            "declared_goal": candidate.get("declared_goal") or candidate.get("goal"),
            "model_response_excerpt": candidate.get("model_response_excerpt") or "",
            "observed_status": candidate.get("observed_status") or candidate.get("status"),
            "observed_actual_paths": (
                candidate.get("observed_actual_paths")
                or candidate.get("actual_paths")
                or []
            ),
            "field_provenance": candidate.get("field_provenance") or {},
            # Compatibility metadata for existing audit/UI consumers.
            "goal": candidate.get("goal"),
            "intent": candidate.get("intent"),
            "status": candidate.get("status"),
            "requires_write": bool(candidate.get("requires_write")),
            "requires_state_change": bool(candidate.get("requires_state_change")),
            "deliverable_kinds": candidate.get("deliverable_kinds") or [],
            "capability_ids": candidate.get("capability_ids") or [],
            "target_written_paths": candidate.get("target_written_paths") or [],
            "changed_paths": candidate.get("changed_paths") or [],
            "verified_paths": candidate.get("verified_paths") or [],
            "actual_paths": candidate.get("actual_paths") or [],
            "focus_relation": candidate.get("focus_relation") or "",
            "focus": candidate.get("focus") or {},
        })
    return ContextRecord(
        kind="task_lineage",
        content=content,
        source_id="task_lineage_candidates",
        source_type="conversation_history",
        trust="mixed_sources",
        task_id=task_id,
        freshness="recent",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "candidate_schema_version": "task_lineage_candidate.v2",
            "provenance_schema_version": "task_lineage_provenance.v1",
            "candidates": compact_candidates[:4],
        },
    )


def _task_contract_record(
    task_contract: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    if not isinstance(task_contract, dict):
        return None
    goal = str(task_contract.get("goal") or task_contract.get("intent") or "").strip()
    if not goal:
        return None
    capability_ids = [
        str(item)
        for item in task_contract.get("capability_ids") or []
        if str(item or "").strip()
    ]
    success_conditions = [
        str(item)
        for item in task_contract.get("success_conditions") or []
        if str(item or "").strip()
    ]
    deliverables = task_contract.get("deliverables") if isinstance(task_contract.get("deliverables"), list) else []
    deliverable_bits = [
        _deliverable_summary(item)
        for item in deliverables
        if isinstance(item, dict)
    ]
    content = (
        f"Current task contract: {goal}; "
        f"task_relation={task_contract.get('scope_relation') or 'new'}; "
        f"focus_relation={task_contract.get('focus_relation') or 'unresolved'}; "
        f"intent={task_contract.get('intent') or ''}; "
        f"requires_write={bool(task_contract.get('requires_write'))}; "
        f"requires_state_change={bool(task_contract.get('requires_state_change'))}; "
        f"requires_verification={bool(task_contract.get('requires_verification'))}; "
        f"capabilities={', '.join(capability_ids[:6]) or 'none'}; "
        f"deliverables={'; '.join(deliverable_bits[:6]) or 'none'}; "
        f"success_conditions={', '.join(success_conditions[:8]) or 'none'}"
    )
    return ContextRecord(
        kind="task_contract",
        content=content,
        source_id="current_task_contract",
        source_type="runtime_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "contract_goal": goal,
            "intent": task_contract.get("intent") or "",
            "task_relation": task_contract.get("scope_relation") or "new",
            "focus_relation": task_contract.get("focus_relation") or "unresolved",
            "focus": task_contract.get("focus") if isinstance(task_contract.get("focus"), dict) else {},
            "requires_write": bool(task_contract.get("requires_write")),
            "requires_state_change": bool(task_contract.get("requires_state_change")),
            "requires_verification": bool(task_contract.get("requires_verification")),
            "capability_ids": capability_ids[:6],
            "success_conditions": success_conditions[:8],
        },
    )


def _active_focus_record(
    active_focus: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    if not isinstance(active_focus, dict):
        return None
    relation = str(active_focus.get("relation") or "unresolved")
    focus = active_focus.get("focus") if isinstance(active_focus.get("focus"), dict) else {}
    source_candidate_id = str(active_focus.get("source_candidate_id") or "")
    evidence_paths = [
        str(item)
        for item in active_focus.get("evidence_paths") or []
        if str(item or "").strip()
    ][:12]
    if relation == "unresolved" and not focus and not source_candidate_id:
        return None
    content = (
        "Active working focus declaration, independent from the task action: "
        f"relation={relation}; "
        f"kind={focus.get('kind') or 'unknown'}; "
        f"name={focus.get('name') or 'unknown'}; "
        f"path={focus.get('path_hint') or 'unknown'}; "
        f"source_candidate={source_candidate_id or 'none'}; "
        f"evidence_paths={', '.join(evidence_paths) or 'none'}. "
        "Use this to identify the working object only; do not reuse an earlier task goal or route."
    )
    return ContextRecord(
        kind="project_context",
        content=content,
        source_id="active_focus_snapshot",
        source_type="runtime_event",
        trust="model_inferred",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "schema_version": active_focus.get("schema_version") or "",
            "relation": relation,
            "focus": focus,
            "source_candidate_id": source_candidate_id,
            "source_candidate_found": bool(active_focus.get("source_candidate_found")),
            "evidence_paths": evidence_paths,
            "resolved": bool(active_focus.get("resolved")),
        },
    )


def _capability_record(
    snapshot: dict[str, Any] | None,
    preflight: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    preflight = preflight if isinstance(preflight, dict) else {}
    if not snapshot and not preflight:
        return None
    target_capability_ids = [
        str(item)
        for item in preflight.get("target_capability_ids") or []
        if str(item or "").strip()
    ]
    visual_verification_tool_ids = [
        str(item)
        for item in preflight.get("visual_verification_tool_ids") or []
        if str(item or "").strip()
    ] if isinstance(preflight.get("visual_verification_tool_ids"), list) else []
    advisories = preflight.get("advisories") if isinstance(preflight.get("advisories"), list) else []
    advisory_codes = [
        str(item.get("code") or "")
        for item in advisories
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    evidence_affordances = _capability_evidence_affordances(snapshot, preflight)
    evidence_text = _format_evidence_affordances(evidence_affordances)
    content = (
        "Capability boundary facts: "
        f"available_tools={_safe_int(snapshot.get('available_tool_count'))}/"
        f"{_safe_int(snapshot.get('tool_count'))}; "
        f"target_capabilities={', '.join(target_capability_ids[:8]) or 'none'}; "
        f"visual_verification_tools={', '.join(visual_verification_tool_ids[:8]) or 'none'}; "
        f"evidence_affordances={evidence_text or 'none'}; "
        f"advisories={', '.join(advisory_codes[:8]) or 'none'}; "
        f"preflight_ok={preflight.get('ok') if 'ok' in preflight else 'unknown'}"
    )
    return ContextRecord(
        kind="capability",
        content=content,
        source_id="capability_preflight",
        source_type="runtime_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "target_capability_ids": target_capability_ids[:8],
            "visual_verification_tool_ids": visual_verification_tool_ids[:12],
            "evidence_affordances": evidence_affordances[:8],
            "advisory_codes": advisory_codes[:12],
            "available_tool_count": _safe_int(snapshot.get("available_tool_count")),
            "tool_count": _safe_int(snapshot.get("tool_count")),
            "preflight_ok": preflight.get("ok"),
        },
    )


def _capability_evidence_affordances(
    snapshot: dict[str, Any],
    preflight: dict[str, Any],
) -> list[dict[str, Any]]:
    value = preflight.get("evidence_affordances")
    if not isinstance(value, list):
        value = snapshot.get("evidence_affordances")
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if not kind:
            continue
        tool_ids = [
            str(tool_id)
            for tool_id in item.get("tool_ids") or []
            if str(tool_id or "").strip()
        ]
        result.append({
            "kind": kind,
            "tool_ids": tool_ids[:8],
            "verification_strengths": [
                str(strength)
                for strength in item.get("verification_strengths") or []
                if str(strength or "").strip()
            ][:4],
        })
    return result


def _format_evidence_affordances(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items[:6]:
        kind = str(item.get("kind") or "").strip()
        tool_ids = [
            str(tool_id)
            for tool_id in item.get("tool_ids") or []
            if str(tool_id or "").strip()
        ]
        if not kind or not tool_ids:
            continue
        parts.append(f"{kind}:{','.join(tool_ids[:4])}")
    return "; ".join(parts)


def _context_hygiene_record(
    report: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    if not isinstance(report, dict) or not report.get("changed"):
        return None
    content = (
        "Historical model context was sanitized before this run; UI history and "
        "audit records are unchanged."
    )
    return ContextRecord(
        kind="risk",
        content=content,
        source_id="context_hygiene",
        source_type="runtime_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "sanitized_messages": _safe_int(report.get("sanitized_messages")),
            "tool_markup_messages": _safe_int(report.get("tool_markup_messages")),
            "failed_run_messages": _safe_int(report.get("failed_run_messages")),
            "task_candidate_messages": _safe_int(report.get("task_candidate_messages")),
            "task_user_anchor_messages": _safe_int(report.get("task_user_anchor_messages")),
            "compacted_task_marker_messages": _safe_int(report.get("compacted_task_marker_messages")),
            "current_request_boundary_inserted": bool(report.get("current_request_boundary_inserted")),
        },
    )


def _tool_events_record(
    tool_events: list[dict[str, Any]] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    events = _dict_events(tool_events)
    if not events:
        return None
    recent = events[-6:]
    summaries = [_tool_event_summary(event) for event in recent]
    content = "Recent tool result facts: " + "; ".join(summaries)
    return ContextRecord(
        kind="tool_result",
        content=content,
        source_id="recent_tool_events",
        source_type="run_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "tool_event_count": len(events),
            "recent_tools": [
                {
                    "tool": str(event.get("tool") or event.get("name") or ""),
                    "status": str(event.get("status") or ""),
                    "path": _tool_event_path(event),
                    "error": _truncate(event.get("error"), 180),
                }
                for event in recent
            ],
        },
    )


def _execution_state_record(
    tool_events: list[dict[str, Any]] | None,
    execution_plan: dict[str, Any] | None,
    *,
    round_index: int | None,
    task_id: str,
) -> ContextRecord | None:
    events = _dict_events(tool_events)
    plan = execution_plan if isinstance(execution_plan, dict) else {}
    if not events and not plan and round_index is None:
        return None
    active_step = _active_plan_step(plan)
    latest = events[-1] if events else {}
    content = (
        "Execution state facts: "
        f"round={round_index if round_index is not None else 'unknown'}; "
        f"tool_event_count={len(events)}; "
        f"latest_tool={latest.get('tool') or latest.get('name') or 'none'}; "
        f"latest_status={latest.get('status') or 'none'}; "
        f"plan_state={plan.get('state') or 'none'}; "
        f"active_step={active_step or 'none'}"
    )
    return ContextRecord(
        kind="recovery",
        content=content,
        source_id="execution_state",
        source_type="runtime_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "round_index": round_index,
            "tool_event_count": len(events),
            "latest_tool": str(latest.get("tool") or latest.get("name") or ""),
            "latest_status": str(latest.get("status") or ""),
            "plan_state": str(plan.get("state") or ""),
            "active_step": active_step,
        },
    )


def _tool_risk_record(
    tool_events: list[dict[str, Any]] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    events = _dict_events(tool_events)
    if not events:
        return None
    risk_bits: list[str] = []
    for event in events[-8:]:
        status = str(event.get("status") or "")
        if status in {"failure", "cancelled"}:
            tool = str(event.get("tool") or event.get("name") or "tool")
            error = _truncate(event.get("error"), 220)
            risk_bits.append(f"{tool} {status}: {error or 'no error message'}")
        for risk in event.get("runtime_risks") or []:
            if isinstance(risk, dict):
                code = str(risk.get("code") or risk.get("reason") or "runtime_risk")
                message = _truncate(risk.get("message") or risk.get("detail") or "", 180)
                risk_bits.append(f"{code}: {message}".strip(": "))
    if not risk_bits:
        return None
    content = "Execution risk facts: " + "; ".join(risk_bits[:8])
    return ContextRecord(
        kind="risk",
        content=content,
        source_id="execution_risks",
        source_type="run_event",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={"risk_count": len(risk_bits), "risks": risk_bits[:8]},
    )


def _run_result_record(
    run_result: dict[str, Any] | None,
    *,
    task_id: str,
) -> ContextRecord | None:
    if not isinstance(run_result, dict):
        return None
    status = str(run_result.get("status") or "").strip()
    artifacts = (
        run_result.get("run_artifacts")
        if isinstance(run_result.get("run_artifacts"), list)
        else run_result.get("artifacts") if isinstance(run_result.get("artifacts"), list) else []
    )
    verification = (
        run_result.get("verification_evidence")
        if isinstance(run_result.get("verification_evidence"), list)
        else []
    )
    risks = [
        str(item)
        for item in run_result.get("risks") or []
        if str(item or "").strip()
    ]
    failures = (
        run_result.get("failure_details")
        if isinstance(run_result.get("failure_details"), list)
        else run_result.get("failures") if isinstance(run_result.get("failures"), list) else []
    )
    artifact_paths = [
        str(item.get("path") or "")
        for item in artifacts
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    artifact_roles = [
        str(item.get("role") or item.get("artifact_kind") or item.get("kind") or "")
        for item in artifacts
        if isinstance(item, dict)
    ]
    verification_bits = [
        _verification_summary(item)
        for item in verification
        if isinstance(item, dict)
    ]
    closure_text = format_verification_closure_for_model(
        run_result.get("verification_closure")
        if isinstance(run_result.get("verification_closure"), dict)
        else None
    ).strip()
    content = (
        f"Run result facts: status={status or 'unknown'}; "
        f"artifacts={', '.join(artifact_paths[:8]) or 'none'}; "
        f"artifact_roles={', '.join(artifact_roles[:8]) or 'none'}; "
        f"verification={'; '.join(verification_bits[:8]) or 'none'}; "
        f"risks={', '.join(risks[:12]) or 'none'}; "
        f"failure_count={len(failures)}"
    )
    if closure_text:
        content += "\n" + closure_text
    return ContextRecord(
        kind="tool_result",
        content=content,
        source_id="run_result",
        source_type="run_result",
        trust="runtime_fact",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={
            "status": status,
            "risk_count": len(risks),
            "risks": risks[:12],
            "artifact_count": len(artifacts),
            "artifact_paths": artifact_paths[:12],
            "artifact_roles": artifact_roles[:12],
            "verification_count": len(verification),
            "failure_count": len(failures),
            "verification_closure": (
                run_result.get("verification_closure")
                if isinstance(run_result.get("verification_closure"), dict)
                else {}
            ),
        },
    )


def _assistant_answer_record(
    assistant_content: str,
    *,
    task_id: str,
) -> ContextRecord | None:
    text = str(assistant_content or "").strip()
    if not text:
        return None
    content = f"Final answer candidate preview: {_truncate(text, 500)}"
    return ContextRecord(
        kind="tool_result",
        content=content,
        source_id="assistant_final_answer",
        source_type="assistant_message",
        trust="model_inferred",
        task_id=task_id,
        freshness="current",
        token_estimate=_estimate_tokens_fast(content),
        metadata={"content_chars": len(text)},
    )


def _deliverable_summary(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "artifact")
    path_hint = str(item.get("path_hint") or item.get("path") or "").strip()
    capability_id = str(item.get("capability_id") or "").strip()
    description = str(item.get("description") or "").strip()
    bits = [kind]
    if path_hint:
        bits.append(path_hint)
    if capability_id:
        bits.append(capability_id)
    if description:
        bits.append(_truncate(description, 80))
    return " / ".join(bits)


def _verification_summary(item: dict[str, Any]) -> str:
    tool = str(item.get("tool") or "")
    path = str(item.get("path") or "")
    strength = str(item.get("strength") or item.get("verification_strength") or "")
    modality = str(item.get("modality") or "")
    modalities = item.get("modalities") if isinstance(item.get("modalities"), list) else []
    bits = [value for value in (tool, path, strength, modality) if value]
    if modalities:
        bits.append(",".join(str(value) for value in modalities[:4]))
    return " / ".join(bits) or "verification"


def _tool_event_summary(event: dict[str, Any]) -> str:
    tool = str(event.get("tool") or event.get("name") or "tool")
    status = str(event.get("status") or "unknown")
    path = _tool_event_path(event)
    error = _truncate(event.get("error"), 160)
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    observation = event.get("tool_attempt_observation")
    if not isinstance(observation, dict):
        observation = output.get("observation") if isinstance(output.get("observation"), dict) else {}
    reason = str(output.get("reason") or observation.get("reason") or "").strip()
    missing_fields = [
        str(item)
        for item in observation.get("missing_fields") or []
        if str(item or "").strip()
    ] if isinstance(observation, dict) else []
    roles = event.get("declared_roles") if isinstance(event.get("declared_roles"), list) else []
    bits = [tool, status]
    if path:
        bits.append(path)
    if roles:
        bits.append("roles=" + ",".join(str(item) for item in roles[:4]))
    if reason:
        bits.append("reason=" + _truncate(reason, 120))
    if missing_fields:
        bits.append("missing=" + ",".join(missing_fields[:4]))
    if error:
        bits.append("error=" + error)
    return " / ".join(bits)


def _tool_event_path(event: dict[str, Any]) -> str:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    inputs = event.get("input") if isinstance(event.get("input"), dict) else {}
    for source in (output, inputs):
        for key in ("path", "output_path", "root", "file", "target_path"):
            value = source.get(key)
            if str(value or "").strip():
                return str(value)
        paths = source.get("paths") or source.get("changed_paths") or source.get("created_paths")
        if isinstance(paths, list) and paths:
            return str(paths[0])
    return ""


def _active_plan_step(plan: dict[str, Any]) -> str:
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        status = str(step.get("status") or step.get("state") or "").lower()
        if status in {"running", "in_progress", "active"}:
            return _truncate(step.get("title") or step.get("step") or f"step {index + 1}", 160)
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        status = str(step.get("status") or step.get("state") or "").lower()
        if status in {"pending", "todo", ""}:
            return _truncate(step.get("title") or step.get("step") or f"step {index + 1}", 160)
    return ""


def _dict_events(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _model_record_char_limit(kind: str) -> int:
    return {
        "user_intent": 1200,
        "workspace_summary": 1600,
        "task_lineage_availability": 900,
        "task_lineage": 2800,
        "project_context": 1400,
        "task_contract": 1800,
        "memory": 2400,
        "tool_result": 1800,
    }.get(str(kind or ""), 1000)


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _estimate_tokens_fast(value: Any) -> int:
    text = str(value or "")
    if not text:
        return 0
    ascii_chars = 0
    cjk_chars = 0
    other_chars = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            cjk_chars += 1
        elif ord(char) < 128:
            ascii_chars += 1
        else:
            other_chars += 1
    return max(1, (ascii_chars + 3) // 4 + cjk_chars + (other_chars + 1) // 2)
