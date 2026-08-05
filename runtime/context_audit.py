"""面向用户的 Context Runtime 审计摘要。

本模块将 Context Pack 账本转换为供 UI 和诊断使用的紧凑审计模型。
它只负责展示，不选择任务、不选择工具、不阻止执行，
也不判断模型的决策是否正确。"""

from __future__ import annotations

from typing import Any


CONTEXT_AUDIT_SCHEMA_VERSION = "context_audit.v1"

HISTORICAL_CONTEXT_KINDS = frozenset({
    "previous_contract",
    "task_lineage",
    "memory",
    "recovery",
})
HISTORICAL_SOURCE_TYPES = frozenset({
    "conversation_history",
    "memory_store",
})
HISTORICAL_FRESHNESS = frozenset({"recent", "stored", "historical", "stale"})


def build_context_audit(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """根据 RunEvidence 的 Context Pack 摘要构建只读审计视图。"""

    if not isinstance(evidence, dict):
        return _empty_audit()
    packs = _context_packs_from_evidence(evidence)
    records = _ledger_records(packs)
    phase_summary = _phase_summary(packs, records)
    source_summary = _counter_summary(records, "source_type")
    trust_summary = _counter_summary(records, "trust")
    freshness_summary = _counter_summary(records, "freshness")
    kind_summary = _counter_summary(records, "kind")
    historical_records = [
        item for item in records
        if _is_historical_record(item)
    ]
    hygiene_records = [
        item for item in records
        if item.get("source_id") == "context_hygiene"
        or item.get("kind") == "risk" and "context_hygiene" in _metadata_keys(item)
    ]
    token_estimate = sum(_safe_int(item.get("token_estimate"), 0) for item in records)
    current_records = [
        item for item in records
        if str(item.get("freshness") or "") == "current"
    ]
    run_info = evidence.get("run") if isinstance(evidence.get("run"), dict) else {}
    run_task_id = str(run_info.get("task_id") or "")

    return {
        "schema_version": CONTEXT_AUDIT_SCHEMA_VERSION,
        "kind": "context_audit",
        "boundary": "audit_only",
        "run_task_id": run_task_id,
        "counts": {
            "context_packs": len(packs),
            "records": len(records),
            "token_estimate": token_estimate,
            "current_records": len(current_records),
            "historical_records": len(historical_records),
            "memory_records": sum(1 for item in records if item.get("kind") == "memory"),
            "task_lineage_records": sum(1 for item in records if item.get("kind") == "task_lineage"),
            "previous_contract_records": sum(1 for item in records if item.get("kind") == "previous_contract"),
            "hygiene_records": len(hygiene_records),
            "records_without_task_id": sum(1 for item in records if not str(item.get("task_id") or "")),
            "different_task_records": sum(
                1
                for item in records
                if run_task_id and str(item.get("task_id") or "") and str(item.get("task_id")) != run_task_id
            ),
        },
        "flags": {
            "has_context": bool(records),
            "has_historical_context": bool(historical_records),
            "has_memory_context": any(item.get("kind") == "memory" for item in records),
            "has_task_lineage": any(item.get("kind") == "task_lineage" for item in records),
            "has_previous_contract": any(item.get("kind") == "previous_contract" for item in records),
            "has_context_hygiene": bool(hygiene_records),
            "has_task_id_gaps": any(not str(item.get("task_id") or "") for item in records),
        },
        "phase_summary": phase_summary,
        "source_summary": source_summary,
        "trust_summary": trust_summary,
        "freshness_summary": freshness_summary,
        "record_kind_summary": kind_summary,
        "historical_records": historical_records[-12:],
        "hygiene_records": hygiene_records[-8:],
        "recent_records": records[-16:],
    }


def _empty_audit() -> dict[str, Any]:
    return {
        "schema_version": CONTEXT_AUDIT_SCHEMA_VERSION,
        "kind": "context_audit",
        "boundary": "audit_only",
        "run_task_id": "",
        "counts": {
            "context_packs": 0,
            "records": 0,
            "token_estimate": 0,
            "current_records": 0,
            "historical_records": 0,
            "memory_records": 0,
            "task_lineage_records": 0,
            "previous_contract_records": 0,
            "hygiene_records": 0,
            "records_without_task_id": 0,
            "different_task_records": 0,
        },
        "flags": {
            "has_context": False,
            "has_historical_context": False,
            "has_memory_context": False,
            "has_task_lineage": False,
            "has_previous_contract": False,
            "has_context_hygiene": False,
            "has_task_id_gaps": False,
        },
        "phase_summary": [],
        "source_summary": [],
        "trust_summary": [],
        "freshness_summary": [],
        "record_kind_summary": [],
        "historical_records": [],
        "hygiene_records": [],
        "recent_records": [],
    }


def _context_packs_from_evidence(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    for item in evidence.get("context_packs") or []:
        if isinstance(item, dict):
            packs.append(item)
    latest = evidence.get("context_pack")
    if isinstance(latest, dict) and latest:
        latest_phase = str(latest.get("phase") or "")
        latest_hash = _pack_identity(latest)
        if not any(_pack_identity(item) == latest_hash for item in packs):
            packs.append(latest)
        elif latest_phase and not any(str(item.get("phase") or "") == latest_phase for item in packs):
            packs.append(latest)
    return packs


def _ledger_records(packs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for pack_index, pack in enumerate(packs):
        phase = str(pack.get("phase") or "")
        ledger = pack.get("ledger") if isinstance(pack.get("ledger"), dict) else {}
        for item_index, item in enumerate(ledger.get("records") or []):
            if not isinstance(item, dict):
                continue
            metadata_keys = [
                str(key)
                for key in item.get("metadata_keys") or []
                if str(key or "").strip()
            ]
            records.append({
                "phase": phase or str(ledger.get("phase") or ""),
                "pack_index": pack_index,
                "record_index": _safe_int(item.get("index"), item_index),
                "kind": str(item.get("kind") or ""),
                "source_id": str(item.get("source_id") or ""),
                "source_type": str(item.get("source_type") or ""),
                "trust": str(item.get("trust") or ""),
                "freshness": str(item.get("freshness") or ""),
                "task_id": str(item.get("task_id") or ""),
                "token_estimate": _safe_int(item.get("token_estimate"), 0),
                "content_hash": str(item.get("content_hash") or ""),
                "content_preview": _truncate(item.get("content_preview"), 220),
                "metadata_keys": metadata_keys[:24],
                "historical": _is_historical_record(item),
            })
    return records


def _phase_summary(packs: list[dict[str, Any]], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases: list[str] = []
    for pack in packs:
        phase = str(pack.get("phase") or "")
        if phase and phase not in phases:
            phases.append(phase)
    result: list[dict[str, Any]] = []
    for phase in phases:
        phase_records = [item for item in records if item.get("phase") == phase]
        result.append({
            "phase": phase,
            "pack_count": sum(1 for item in packs if str(item.get("phase") or "") == phase),
            "record_count": len(phase_records),
            "token_estimate": sum(_safe_int(item.get("token_estimate"), 0) for item in phase_records),
            "historical_records": sum(1 for item in phase_records if item.get("historical")),
            "record_kinds": _unique(item.get("kind") for item in phase_records)[:12],
            "source_types": _unique(item.get("source_type") for item in phase_records)[:12],
        })
    return result


def _counter_summary(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, int]] = {}
    for item in records:
        label = str(item.get(key) or "unknown").strip() or "unknown"
        bucket = counts.setdefault(label, {"count": 0, "token_estimate": 0})
        bucket["count"] += 1
        bucket["token_estimate"] += _safe_int(item.get("token_estimate"), 0)
    return [
        {
            key: label,
            "count": values["count"],
            "token_estimate": values["token_estimate"],
        }
        for label, values in sorted(counts.items(), key=lambda pair: (-pair[1]["count"], pair[0]))[:16]
    ]


def _is_historical_record(record: dict[str, Any]) -> bool:
    kind = str(record.get("kind") or "")
    source_type = str(record.get("source_type") or "")
    freshness = str(record.get("freshness") or "")
    return (
        kind in HISTORICAL_CONTEXT_KINDS
        or source_type in HISTORICAL_SOURCE_TYPES
        or freshness in HISTORICAL_FRESHNESS
    )


def _metadata_keys(record: dict[str, Any]) -> list[str]:
    return [
        str(key)
        for key in record.get("metadata_keys") or []
        if str(key or "").strip()
    ]


def _pack_identity(pack: dict[str, Any]) -> tuple[str, int, str]:
    ledger = pack.get("ledger") if isinstance(pack.get("ledger"), dict) else {}
    records = ledger.get("records") if isinstance(ledger.get("records"), list) else []
    content_hash = ""
    if records and isinstance(records[-1], dict):
        content_hash = str(records[-1].get("content_hash") or "")
    return (str(pack.get("phase") or ""), len(records), content_hash)


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."
