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

from runtime.agent_strategy.project_context import compact_focus_for_candidate


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
    candidate = {
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
        "contract_anchor": _contract_anchor(contract, run_result=run_result),
    }
    candidate.update(compact_focus_for_candidate(contract))
    return candidate


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
    for candidate in result:
        affinity = _candidate_target_affinity(candidate, current)
        candidate["current_target_affinity"] = affinity
        candidate["current_target_match"] = affinity > 0
    has_target_match = any(
        _safe_int(candidate.get("current_target_affinity"), default=0) > 0
        for candidate in result
    )
    ranked = sorted(
        result,
        key=lambda candidate: _candidate_sort_key(
            candidate,
            target_match_active=has_target_match,
        ),
    )[:limit]
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
        item = {
            "candidate_id": candidate.get("candidate_id"),
            "lineage_rank": candidate.get("lineage_rank"),
            "recency_rank": candidate.get("recency_rank"),
            "goal": _truncate(candidate.get("goal"), 180),
            "status": candidate.get("status"),
            "actual_paths": list(candidate.get("actual_paths") or [])[:4],
            "focus": candidate.get("focus") or {},
        }
        if "current_target_match" in candidate:
            item["current_target_match"] = bool(candidate.get("current_target_match"))
        if _safe_int(candidate.get("current_target_affinity"), default=0) > 0:
            item["current_target_affinity"] = _safe_int(
                candidate.get("current_target_affinity"),
                default=0,
            )
        compact.append(item)
        if len(compact) >= limit:
            break
    if not compact:
        return ""
    payload = {
        "schema_version": "task_lineage_context.v1",
        "kind": "task_lineage",
        "rule": (
            "Historical task candidates, not current goals. A new task may "
            "inherit a candidate's working focus without inheriting its old "
            "goal. Prefer runtime-observed actual_paths. Failed verification "
            "attempts should not replace the target paths from a prior write run."
        ),
        "candidates": compact,
    }
    active_target = _active_target_fact(candidates)
    if active_target:
        payload["active_target"] = active_target
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _contract_anchor(
    contract: dict[str, Any],
    *,
    run_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "focus_relation",
        "focus",
        "referenced_focus_candidate_id",
    )
    anchor = {
        key: deepcopy(contract[key])
        for key in keys
        if key in contract
    }
    if isinstance(run_result, dict):
        _ground_anchor_deliverables_with_run_result(anchor, run_result)
    return anchor


def _ground_anchor_deliverables_with_run_result(
    anchor: dict[str, Any],
    run_result: dict[str, Any],
) -> None:
    """Promote runtime-observed write targets into a continuation anchor.

    The model still decides whether a current request references this
    candidate. Once it does, paths observed in the previous run are stronger
    evidence than a broad original path hint such as the workspace root.
    """
    paths = _unique_strings(
        [
            *_string_list(run_result.get("target_written_paths"), limit=8),
            *_string_list(run_result.get("observed_written_paths"), limit=8),
            *_string_list(run_result.get("changed_paths"), limit=8),
            *_string_list(run_result.get("written_paths"), limit=8),
        ],
        limit=8,
    )
    if not paths:
        return

    existing = [
        deepcopy(item)
        for item in anchor.get("deliverables") or []
        if isinstance(item, dict)
    ]
    observed_keys = {_normalize_path_hint(path) for path in paths}
    promoted: list[dict[str, Any]] = []
    for path in paths:
        key = _normalize_path_hint(path)
        match = next(
            (
                item
                for item in existing
                if _normalize_path_hint(item.get("path_hint") or item.get("path")) == key
            ),
            None,
        )
        if match:
            item = deepcopy(match)
        else:
            item = {
                "kind": _deliverable_kind_for_path(path, existing),
                "path_hint": path,
                "path_policy": "hint",
                "capability_id": "",
                "description": "Runtime-observed target path from the referenced run",
            }
        item["path_hint"] = str(item.get("path_hint") or item.get("path") or path)
        item.setdefault("path_policy", "hint")
        item.setdefault("capability_id", "")
        if not str(item.get("description") or "").strip():
            item["description"] = "Runtime-observed target path from the referenced run"
        promoted.append(item)

    remaining = [
        item
        for item in existing
        if _normalize_path_hint(item.get("path_hint") or item.get("path")) not in observed_keys
    ]
    anchor["deliverables"] = _dedupe_deliverables([*promoted, *remaining])[:8]


def _deliverable_kind_for_path(path: str, existing: list[dict[str, Any]]) -> str:
    for item in existing:
        kind = str(item.get("kind") or "").strip().lower()
        if kind in {"code", "document", "spreadsheet", "file"}:
            return kind
    suffix = str(path or "").strip().lower().rsplit(".", 1)
    ext = suffix[-1] if len(suffix) == 2 else ""
    if ext in {"py", "js", "jsx", "ts", "tsx", "vue", "html", "css", "json", "toml", "yaml", "yml", "rs", "go", "java", "cs", "cpp", "c", "h", "hpp", "php", "rb", "sh", "ps1", "bat", "sql"}:
        return "code"
    if ext in {"doc", "docx", "pdf", "ppt", "pptx", "md"}:
        return "document"
    if ext in {"xls", "xlsx", "csv", "tsv"}:
        return "spreadsheet"
    return "file"


def _dedupe_deliverables(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = _normalize_path_hint(item.get("path_hint") or item.get("path"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(item)
    return result


def _normalize_path_hint(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


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


def _candidate_sort_key(
    candidate: dict[str, Any],
    *,
    target_match_active: bool = False,
) -> tuple[int, int, int, int]:
    affinity = _safe_int(candidate.get("current_target_affinity"), default=0)
    target_group = 0
    if target_match_active:
        target_group = 0 if affinity > 0 else 1
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
    return (target_group, -affinity, group, recency)


def _candidate_target_affinity(candidate: dict[str, Any], current_content: str) -> int:
    """Return path/subproject affinity between current wording and a candidate.

    This does not choose the task. It only ranks historical facts so a prompt
    that explicitly names a target folder is less likely to be dominated by a
    newer but wrong-target run.
    """
    text = _normalize_match_text(current_content)
    if not text:
        return 0
    score = 0
    for path in _candidate_target_paths(candidate):
        score = max(score, _path_affinity(path, text))
    return score


def _candidate_target_paths(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "target_written_paths",
        "changed_paths",
        "observed_written_paths",
        "written_paths",
        "actual_paths",
    ):
        value = candidate.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text)
    return values


def _candidate_write_target_paths(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "target_written_paths",
        "changed_paths",
        "observed_written_paths",
        "written_paths",
    ):
        value = candidate.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text)
    return values


def _active_target_fact(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> dict[str, Any]:
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        paths = _candidate_write_target_paths(candidate)
        if not paths:
            continue
        return {
            "candidate_id": candidate.get("candidate_id"),
            "lineage_rank": candidate.get("lineage_rank"),
            "recency_rank": candidate.get("recency_rank"),
            "target_paths": paths[:6],
            "goal": candidate.get("goal"),
            "rule": (
                "Historical candidate only. Use this as the current target "
                "only when the user explicitly continues/retries/evaluates "
                "the previous result, or when the current wording shares the "
                "same path, artifact, or domain."
            ),
        }
    return {}


def _path_affinity(path: str, normalized_current: str) -> int:
    normalized_path = _normalize_match_text(path)
    if len(normalized_path) >= 6 and normalized_path in normalized_current:
        return min(len(normalized_path), 120)
    score = 0
    for part in str(path or "").replace("\\", "/").split("/"):
        part = part.strip()
        if not part:
            continue
        candidates = {part}
        if "." in part:
            candidates.add(part.rsplit(".", 1)[0])
        for candidate in candidates:
            token = _normalize_match_text(candidate)
            if len(token) < 5:
                continue
            if token in normalized_current:
                score = max(score, min(len(token), 80))
    return score


def _normalize_match_text(value: Any) -> str:
    text = str(value or "").strip().lower().replace("\\", "/")
    for ch in (" ", "\t", "\r", "\n", "，", "。", "、", "：", ":", ";", "；", "\"", "'", "`"):
        text = text.replace(ch, "")
    return text


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
