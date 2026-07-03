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
    run_result = metadata.get("run_result") if isinstance(metadata.get("run_result"), dict) else {}
    target_written_paths = _string_list(run_result.get("target_written_paths"), limit=8)
    observed_written_paths = _string_list(run_result.get("observed_written_paths"), limit=8)
    changed_paths = _string_list(run_result.get("changed_paths"), limit=8)
    written_paths = _string_list(run_result.get("written_paths"), limit=8)
    verified_paths = _verification_paths(run_result)
    artifact_paths = _artifact_paths(run_result)
    actual_paths = _unique_strings(
        [
            *target_written_paths,
            *changed_paths,
            *observed_written_paths,
            *written_paths,
            *artifact_paths,
            *verified_paths,
        ],
        limit=12,
    )
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
        "changed_paths": changed_paths,
        "target_written_paths": target_written_paths,
        "observed_written_paths": observed_written_paths,
        "verified_paths": verified_paths,
        "artifact_paths": artifact_paths,
        "actual_paths": actual_paths,
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
    scan_limit = max(limit, limit * 3)
    source_recency_rank = 0
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
        source_recency_rank += 1
        candidate["recency_rank"] = source_recency_rank
        result.append(candidate)
        if len(result) >= scan_limit:
            break
    ranked = sorted(result, key=_candidate_sort_key)[:limit]
    for rank, candidate in enumerate(ranked, start=1):
        candidate["lineage_rank"] = rank
    return ranked


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
            "lineage_rank": candidate.get("lineage_rank"),
            "recency_rank": candidate.get("recency_rank"),
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
            "They are ordered by lineage_rank: recent candidates with "
            "runtime-observed target paths first. "
            "Use one only if the current user request continues, revises, "
            "retries, or evaluates that candidate. Prefer runtime-observed "
            "actual_paths over guessed, stale, or intermediate paths when "
            "inspecting a continued task. Read-only failed verification "
            "attempts may explain what went wrong, but should not replace the "
            "target paths from a prior write/change run."
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


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int]:
    recency = _safe_int(candidate.get("recency_rank"), default=9999)
    has_target_path = bool(
        candidate.get("target_written_paths")
        or candidate.get("changed_paths")
        or candidate.get("observed_written_paths")
    )
    has_any_path = bool(candidate.get("actual_paths"))
    status = str(candidate.get("status") or "").strip().lower()
    if has_target_path:
        group = 0
    elif has_any_path and status != "failure":
        group = 1
    elif has_any_path:
        group = 2
    else:
        group = 3
    return (group, recency)


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _verification_paths(run_result: dict[str, Any]) -> list[str]:
    values = run_result.get("verified") if isinstance(run_result.get("verified"), list) else []
    paths: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path and path not in paths:
            paths.append(path)
    evidence = (
        run_result.get("verification_evidence")
        if isinstance(run_result.get("verification_evidence"), list)
        else []
    )
    for item in evidence:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path and path not in paths:
            paths.append(path)
    return paths[:8]


def _artifact_paths(run_result: dict[str, Any]) -> list[str]:
    artifacts = run_result.get("artifacts") if isinstance(run_result.get("artifacts"), list) else []
    paths: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path and path not in paths:
            paths.append(path)
    return paths[:8]


def _unique_strings(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _candidate_hash(index: int, goal: str, content: str) -> str:
    seed = f"{index}:{goal}:{content[:120]}".encode("utf-8", errors="ignore")
    return hashlib.sha1(seed).hexdigest()[:12]


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."
