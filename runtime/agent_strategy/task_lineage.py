"""有界模型上下文中的 Task Lineage 辅助函数。

Task Lineage 不是路由器。它把先前任务契约转换为明确的历史候选，
让模型无需重读噪声较多的旧回复，就能判断当前请求是新任务、续接还是修订。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from runtime.agent_strategy.project_context import compact_focus_for_candidate


TASK_LINEAGE_CANDIDATE_SCHEMA_VERSION = "task_lineage_candidate.v2"
TASK_LINEAGE_PROVENANCE_SCHEMA_VERSION = "task_lineage_provenance.v1"


def task_candidate_from_message(
    *,
    role: str,
    content: str,
    metadata: dict[str, Any] | None,
    index: int = 0,
    message_id: str = "",
    user_request: str = "",
    user_message_id: str = "",
) -> dict[str, Any] | None:
    """返回从一条助手消息中提取的历史任务候选。"""
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
    observed_status = _observed_status_from_metadata(metadata)
    status = observed_status or "historical"
    declared_goal = _truncate(goal, 240)
    model_response_excerpt = _truncate(content, 280)
    provenance = _candidate_provenance(
        contract=contract,
        run_id=run_id,
        task_id=task_id,
        message_id=message_id,
        user_message_id=user_message_id,
        has_user_request=bool(str(user_request or "").strip()),
        has_model_response_excerpt=bool(model_response_excerpt),
        has_observed_paths=bool(actual_paths),
        status=observed_status,
        metadata=metadata,
    )
    candidate = {
        "schema_version": TASK_LINEAGE_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "task_id": task_id,
        "run_id": run_id,
        "source": "assistant_task_contract",
        "index": int(index),
        "user_request": _truncate(user_request, 320),
        "declared_goal": declared_goal,
        "model_response_excerpt": model_response_excerpt,
        "observed_status": observed_status,
        "observed_actual_paths": actual_paths,
        "field_provenance": provenance,
        # 兼容字段仍供内部使用方使用；面向模型的
        # 血缘格式化使用上方明确标注来源的字段。
        "goal": declared_goal,
        "intent": intent,
        "requires_write": bool(contract.get("requires_write")),
        "requires_state_change": bool(contract.get("requires_state_change")),
        "requires_verification": bool(contract.get("requires_verification")),
        "deliverable_kinds": deliverable_kinds[:6],
        "capability_ids": capability_ids[:6],
        "status": status,
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
    """从对话中收集近期历史任务候选。"""
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
        user_anchor = _preceding_user_request(
            messages,
            index,
            current_content=current,
        )
        candidate = task_candidate_from_message(
            role=role,
            content=content,
            metadata=metadata,
            index=index,
            message_id=_message_id(message, fallback=f"assistant:{index}"),
            user_request=str(user_anchor.get("content") or ""),
            user_message_id=str(user_anchor.get("message_id") or ""),
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
    ranked = sorted(
        result,
        key=lambda candidate: _safe_int(candidate.get("recency_rank"), default=9999),
    )[:limit]
    for rank, candidate in enumerate(ranked, start=1):
        candidate["lineage_rank"] = rank
    return ranked


def referenced_candidate_contract(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    candidate_id: Any,
) -> dict[str, Any] | None:
    """返回模型引用候选所对应的内部契约锚点。"""
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
    """将候选格式化为面向模型的紧凑事实。"""
    compact: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        item = {
            "candidate_id": candidate.get("candidate_id"),
            "lineage_rank": candidate.get("lineage_rank"),
            "recency_rank": candidate.get("recency_rank"),
        }
        optional_fields = {
            "user_request": _truncate(candidate.get("user_request"), 220),
            "declared_goal": _truncate(
                candidate.get("declared_goal") or candidate.get("goal"),
                180,
            ),
            "model_response_excerpt": _truncate(
                candidate.get("model_response_excerpt"),
                220,
            ),
            "observed_status": _candidate_observed_status(candidate),
            "observed_actual_paths": list(
                candidate.get("observed_actual_paths")
                or candidate.get("actual_paths")
                or []
            )[:4],
            "declared_focus": candidate.get("focus") or {},
        }
        item.update({key: value for key, value in optional_fields.items() if value})
        provenance = _model_facing_provenance(candidate)
        visible_provenance = {
            key: value
            for key, value in provenance.items()
            if key in item
        }
        if visible_provenance:
            item["field_provenance"] = visible_provenance
        compact.append(item)
        if len(compact) >= limit:
            break
    if not compact:
        return ""
    payload = {
        "schema_version": "task_lineage_context.v2",
        "kind": "task_lineage",
        "rule": (
            "Historical task candidates contain mixed-source fields, not current goals. "
            "user_request is user-provided history; declared_goal, model_response_excerpt, and "
            "declared_focus are historical model interpretations; observed_status and "
            "observed_actual_paths are runtime-observed facts. The current user request "
            "has priority. A new task may inherit a working focus without inheriting an "
            "old declared_goal. Failed verification attempts should not replace the target "
            "paths from a prior write run."
        ),
        "candidates": compact,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _candidate_provenance(
    *,
    contract: dict[str, Any],
    run_id: str,
    task_id: str,
    message_id: str,
    user_message_id: str,
    has_user_request: bool,
    has_model_response_excerpt: bool,
    has_observed_paths: bool,
    status: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    assistant_source_id = run_id or task_id or message_id
    fields: dict[str, dict[str, str]] = {
        "declared_goal": _provenance_field(
            source_type="assistant_task_contract",
            trust=_contract_trust(contract),
            source_id=assistant_source_id,
        ),
    }
    if isinstance(contract.get("focus"), dict) or contract.get("focus_relation"):
        fields["declared_focus"] = _provenance_field(
            source_type="assistant_task_contract",
            trust=_contract_trust(contract),
            source_id=assistant_source_id,
        )
    if has_user_request:
        fields["user_request"] = _provenance_field(
            source_type="user_message",
            trust="user_provided",
            source_id=user_message_id,
        )
    if has_model_response_excerpt:
        fields["model_response_excerpt"] = _provenance_field(
            source_type="assistant_message",
            trust="model_inferred",
            source_id=message_id or assistant_source_id,
        )
    if status:
        fields["observed_status"] = _provenance_field(
            source_type=_status_source_type(metadata),
            trust="runtime_fact",
            source_id=run_id or task_id or assistant_source_id,
        )
    if has_observed_paths:
        fields["observed_actual_paths"] = _provenance_field(
            source_type="run_result",
            trust="runtime_fact",
            source_id=run_id or task_id or assistant_source_id,
        )
    return {
        "schema_version": TASK_LINEAGE_PROVENANCE_SCHEMA_VERSION,
        "fields": fields,
    }


def _provenance_field(*, source_type: str, trust: str, source_id: str) -> dict[str, str]:
    return {
        "source_type": str(source_type or "unknown"),
        "trust": str(trust or "unverified"),
        "source_id": str(source_id or ""),
    }


def _contract_trust(contract: dict[str, Any]) -> str:
    source = str(contract.get("source") or "model").strip().lower()
    return "model_inferred" if source.startswith("model") else "unverified"


def _status_source_type(metadata: dict[str, Any]) -> str:
    if isinstance(metadata.get("run_result"), dict):
        return "run_result"
    if isinstance(metadata.get("execution_notice"), dict):
        return "runtime_event"
    if isinstance(metadata.get("change_summary"), dict):
        return "runtime_event"
    return "assistant_metadata"


def _candidate_observed_status(candidate: dict[str, Any]) -> str:
    value = str(candidate.get("observed_status") or "").strip()
    if value:
        return value
    if str(candidate.get("schema_version") or "") == TASK_LINEAGE_CANDIDATE_SCHEMA_VERSION:
        return ""
    return str(candidate.get("status") or "").strip()


def _model_facing_provenance(candidate: dict[str, Any]) -> dict[str, str]:
    provenance = candidate.get("field_provenance")
    fields = provenance.get("fields") if isinstance(provenance, dict) else None
    if not isinstance(fields, dict):
        fields = {
            "declared_goal": {
                "source_type": "assistant_task_contract",
                "trust": "model_inferred",
            },
            "observed_status": {
                "source_type": "run_result",
                "trust": "runtime_fact",
            },
            "observed_actual_paths": {
                "source_type": "run_result",
                "trust": "runtime_fact",
            },
        }
    result: dict[str, str] = {}
    for name, item in fields.items():
        if not isinstance(item, dict):
            continue
        result[str(name)] = (
            f"{str(item.get('trust') or 'unverified')}:"
            f"{str(item.get('source_type') or 'unknown')}"
        )
    return result


def _preceding_user_request(
    messages: list[Any],
    assistant_index: int,
    *,
    current_content: str,
) -> dict[str, str]:
    for index in range(assistant_index - 1, -1, -1):
        message = messages[index]
        if str(getattr(message, "role", "") or "") != "user":
            continue
        metadata = getattr(message, "metadata", {}) or {}
        if isinstance(metadata, dict) and metadata.get("guidance") and metadata.get("during_run"):
            continue
        content = str(getattr(message, "content", "") or "").strip()
        if not content or (current_content and content == current_content):
            continue
        return {
            "content": content,
            "message_id": _message_id(message, fallback=f"user:{index}"),
        }
    return {}


def _message_id(message: Any, *, fallback: str) -> str:
    return str(getattr(message, "id", "") or fallback).strip()


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
    _ = run_result
    return anchor


def _observed_status_from_metadata(metadata: dict[str, Any]) -> str:
    run_result = metadata.get("run_result")
    if isinstance(run_result, dict) and run_result.get("status"):
        return str(run_result.get("status"))
    execution_notice = metadata.get("execution_notice")
    if isinstance(execution_notice, dict) and execution_notice.get("reason"):
        return str(execution_notice.get("reason"))
    change_summary = metadata.get("change_summary")
    if isinstance(change_summary, dict) and int(change_summary.get("file_count") or 0) > 0:
        return "changed_files"
    return str(metadata.get("status") or "").strip()


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
