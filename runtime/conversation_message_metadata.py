"""对话消息元数据的持久化边界。

对话消息用于恢复可见聊天，以及后续任务血缘所需的少量状态；
完整运行时证据属于 RunEvent 历史。保持这一边界，可避免每条助手消息
重复保存已经随 Run 存储的 Context Pack 和能力目录。"""

from __future__ import annotations

from typing import Any

from runtime.context_pack import context_pack_summary


def compact_conversation_message_metadata(
    role: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """返回适合持久化对话的元数据。

    用户编写的元数据原样保留。助手元数据保留 UI 恢复字段和任务血缘事实，
    大型审计记录则替换为有界摘要。完整记录仍保存在 Run 事件存储库和
    Run Workbench 中。"""

    result = dict(metadata) if isinstance(metadata, dict) else {}
    if str(role or "") != "assistant":
        return result

    packs = _context_packs(result)
    if packs:
        summaries = _latest_context_pack_summaries(packs)
        if summaries:
            result["context_pack_summaries"] = summaries
            result["context_pack_summary"] = summaries[-1]
    result.pop("context_pack", None)
    result.pop("context_packs", None)

    snapshot = result.pop("capability_snapshot", None)
    if isinstance(snapshot, dict):
        result["capability_snapshot_summary"] = _capability_snapshot_summary(snapshot)

    preflight = result.pop("capability_preflight", None)
    if isinstance(preflight, dict):
        result["capability_preflight_summary"] = _capability_preflight_summary(preflight)

    result.pop("completion_decisions", None)
    result.pop("task_route_evidence", None)

    return result


def _context_packs(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    packs = [
        item
        for item in metadata.get("context_packs") or []
        if isinstance(item, dict)
    ]
    latest = metadata.get("context_pack")
    if isinstance(latest, dict) and (not packs or packs[-1] is not latest):
        packs.append(latest)
    return packs


def _latest_context_pack_summaries(
    packs: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    latest_by_phase: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, pack in enumerate(packs):
        summary = context_pack_summary(pack)
        if not summary:
            continue
        phase = str(summary.get("phase") or f"unknown:{index}")
        latest_by_phase[phase] = (index, summary)
    selected = sorted(latest_by_phase.values(), key=lambda item: item[0])[-limit:]
    return [summary for _index, summary in selected]


def _capability_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": str(snapshot.get("schema_version") or ""),
        "tool_count": _safe_int(snapshot.get("tool_count")),
        "available_tool_count": _safe_int(snapshot.get("available_tool_count")),
        "unavailable_tool_count": len(_string_list(snapshot.get("unavailable_tool_ids"))),
        "degraded_tool_ids": _string_list(snapshot.get("degraded_tool_ids"), limit=16),
        "provider_kinds": _string_list(snapshot.get("provider_kinds"), limit=16),
        "available_provider_kinds": _string_list(
            snapshot.get("available_provider_kinds"),
            limit=16,
        ),
        "available_evidence_kinds": _string_list(
            snapshot.get("available_evidence_kinds"),
            limit=16,
        ),
        "capability_issue_count": len(
            [item for item in snapshot.get("capability_issues") or [] if isinstance(item, dict)]
        ),
    }


def _capability_preflight_summary(preflight: dict[str, Any]) -> dict[str, Any]:
    advisories = [
        _advisory_summary(item)
        for item in preflight.get("advisories") or []
        if isinstance(item, dict)
    ]
    return {
        "schema_version": str(preflight.get("schema_version") or ""),
        "ok": preflight.get("ok"),
        "target_capability_ids": _string_list(
            preflight.get("target_capability_ids"),
            limit=16,
        ),
        "visual_verification_tool_ids": _string_list(
            preflight.get("visual_verification_tool_ids"),
            limit=16,
        ),
        "advisory_count": len(advisories),
        "advisories": advisories[:12],
        "route_hint": _compact_dict(preflight.get("route_hint")),
    }


def _advisory_summary(value: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: str(value.get(key) or "")
        for key in ("code", "capability_id", "tool_id", "source_id")
        if str(value.get(key) or "").strip()
    }
    message = str(value.get("message") or "").strip()
    if message:
        result["message"] = _truncate(message, 320)
    return result


def _compact_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (str, int, float, bool)) or item is None
    }


def _string_list(value: Any, *, limit: int = 32) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text or text in result:
            continue
        result.append(_truncate(text, 500))
        if len(result) >= limit:
            break
    return result


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."
