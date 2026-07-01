"""Task lineage helpers for bounded model context.

Task lineage is not a router.  It converts prior task contracts into explicit
historical candidates so the model can decide whether the current request is a
new task, a continuation, or a revision without rereading noisy old replies.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


TASK_LINEAGE_CANDIDATE_SCHEMA_VERSION = "task_lineage_candidate.v1"


def task_candidate_from_message(
    *,
    role: str,
    content: str,
    metadata: dict[str, Any] | None,
    index: int = 0,
) -> dict[str, Any] | None:
    """Return a historical task candidate extracted from one assistant message."""
    if str(role or "") != "assistant" or not isinstance(metadata, dict):
        return None
    contract = metadata.get("task_contract")
    if not isinstance(contract, dict):
        return None
    intent = str(contract.get("intent") or "").strip()
    goal = str(contract.get("goal") or intent or "").strip()
    if not goal or intent == "answer_only":
        return None
    run_id = str(metadata.get("run_id") or "").strip()
    task_id = str(metadata.get("task_id") or "").strip()
    candidate_id = run_id or task_id or _candidate_hash(index, goal, content)
    deliverables = contract.get("deliverables") if isinstance(contract.get("deliverables"), list) else []
    deliverable_kinds = [
        str(item.get("kind") or "")
        for item in deliverables
        if isinstance(item, dict) and str(item.get("kind") or "").strip()
    ]
    capability_ids = [
        str(item)
        for item in contract.get("capability_ids") or []
        if str(item or "").strip()
    ]
    return {
        "schema_version": TASK_LINEAGE_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "task_id": task_id,
        "run_id": run_id,
        "source": "assistant_task_contract",
        "index": int(index),
        "goal": _truncate(goal, 240),
        "intent": intent,
        "requires_write": bool(contract.get("requires_write")),
        "requires_state_change": bool(contract.get("requires_state_change")),
        "requires_verification": bool(contract.get("requires_verification")),
        "deliverable_kinds": deliverable_kinds[:6],
        "capability_ids": capability_ids[:6],
        "status": _status_from_metadata(metadata),
        "contract_anchor": _contract_anchor(contract),
    }


def collect_task_lineage_candidates(
    conversation: Any | None,
    current_content: str,
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Collect recent historical task candidates from a conversation."""
    if conversation is None:
        return []
    current = str(current_content or "").strip()
    result: list[dict[str, Any]] = []
    messages = list(getattr(conversation, "messages", []) or [])
    seen: set[str] = set()
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        role = str(getattr(message, "role", "") or "")
        content = str(getattr(message, "content", "") or "").strip()
        if role == "user" and current and content == current:
            continue
        metadata = getattr(message, "metadata", {}) or {}
        candidate = task_candidate_from_message(
            role=role,
            content=content,
            metadata=metadata,
            index=index,
        )
        if not candidate:
            continue
        key = str(candidate.get("candidate_id") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    result.reverse()
    return result


def referenced_candidate_contract(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    candidate_id: Any,
) -> dict[str, Any] | None:
    """Return the internal contract anchor for a model-referenced candidate."""
    target = str(candidate_id or "").strip()
    if not target:
        return None
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("candidate_id") or "") != target:
            continue
        anchor = candidate.get("contract_anchor")
        return deepcopy(anchor) if isinstance(anchor, dict) else None
    return None


def format_task_candidates_for_model(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    *,
    limit: int = 4,
) -> str:
    """Format candidates as compact model-facing facts."""
    compact: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        compact.append({
            "candidate_id": candidate.get("candidate_id"),
            "goal": candidate.get("goal"),
            "intent": candidate.get("intent"),
            "status": candidate.get("status"),
            "requires_write": bool(candidate.get("requires_write")),
            "requires_state_change": bool(candidate.get("requires_state_change")),
            "deliverable_kinds": candidate.get("deliverable_kinds") or [],
            "capability_ids": candidate.get("capability_ids") or [],
        })
        if len(compact) >= limit:
            break
    if not compact:
        return ""
    payload = {
        "schema_version": "task_lineage_context.v1",
        "kind": "task_lineage",
        "rule": (
            "These are historical task candidates, not the current goal. "
            "Use one only if the current user request continues, revises, "
            "retries, or evaluates that candidate."
        ),
        "candidates": compact,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _contract_anchor(contract: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "intent",
        "goal",
        "requires_write",
        "requires_state_change",
        "requires_verification",
        "required_verification_modalities",
        "expected_document_coverage",
        "expected_min_output_chars",
        "capability_ids",
        "deliverables",
        "success_conditions",
    )
    return {
        key: deepcopy(contract[key])
        for key in keys
        if key in contract
    }


def _status_from_metadata(metadata: dict[str, Any]) -> str:
    run_result = metadata.get("run_result")
    if isinstance(run_result, dict) and run_result.get("status"):
        return str(run_result.get("status"))
    execution_notice = metadata.get("execution_notice")
    if isinstance(execution_notice, dict) and execution_notice.get("reason"):
        return str(execution_notice.get("reason"))
    change_summary = metadata.get("change_summary")
    if isinstance(change_summary, dict) and int(change_summary.get("file_count") or 0) > 0:
        return "changed_files"
    return str(metadata.get("status") or "historical")


def _candidate_hash(index: int, goal: str, content: str) -> str:
    seed = f"{index}:{goal}:{content[:120]}".encode("utf-8", errors="ignore")
    return hashlib.sha1(seed).hexdigest()[:12]


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."
