"""面向模型的项目上下文与活动焦点事实。

Task Lineage 回答之前发生了什么，Active Focus 回答当前任务涉及哪个项目、子项目、
文件、产物或外部对象。两种关系有意保持独立：新任务可以继承相同焦点，
而不继承上一目标或执行路线。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


ACTIVE_FOCUS_SCHEMA_VERSION = "active_focus.v1"
VALID_FOCUS_RELATIONS: frozenset[str] = frozenset({
    "explicit",
    "inherit",
    "switch",
    "unresolved",
})
VALID_FOCUS_KINDS: frozenset[str] = frozenset({
    "workspace",
    "project",
    "subproject",
    "directory",
    "file",
    "artifact",
    "external_state",
    "other",
})


def normalize_focus_relation(value: Any) -> str:
    relation = str(value or "").strip().lower()
    return relation if relation in VALID_FOCUS_RELATIONS else "unresolved"


def normalize_focus_reference(value: Any) -> dict[str, Any]:
    """返回有界的模型声明焦点引用。"""
    if not isinstance(value, dict):
        return {}
    kind = str(value.get("kind") or "").strip().lower()
    if kind not in VALID_FOCUS_KINDS:
        kind = "other" if any(value.get(key) for key in ("name", "path_hint")) else ""
    result = {
        "kind": kind,
        "name": _clean_text(value.get("name"), 160),
        "path_hint": _clean_text(value.get("path_hint") or value.get("path"), 500),
        "description": _clean_text(value.get("description"), 240),
    }
    return {key: item for key, item in result.items() if item}


def build_active_focus_snapshot(
    task_contract: dict[str, Any] | None,
    task_candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    *,
    workspace_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建可审计的焦点快照，但不替模型决定焦点。"""
    contract = task_contract if isinstance(task_contract, dict) else {}
    relation = normalize_focus_relation(contract.get("focus_relation"))
    focus = normalize_focus_reference(contract.get("focus"))
    source_candidate_id = _clean_text(
        contract.get("referenced_focus_candidate_id"),
        160,
    )
    candidate = _candidate_by_id(task_candidates, source_candidate_id)
    candidate_focus = normalize_focus_reference(candidate.get("focus")) if candidate else {}
    evidence_paths = _candidate_paths(candidate)

    # 继承的候选事实只补充模型声明，绝不
    # 替换已声明的当前焦点，也不复制候选的旧任务目标。
    effective_focus = dict(focus)
    if relation == "inherit" and candidate_focus:
        for key, value in candidate_focus.items():
            effective_focus.setdefault(key, value)

    workspace = workspace_snapshot if isinstance(workspace_snapshot, dict) else {}
    return {
        "schema_version": ACTIVE_FOCUS_SCHEMA_VERSION,
        "kind": "active_focus",
        "relation": relation,
        "focus": effective_focus,
        "source": "model_contract" if contract.get("source") == "model" else "runtime_contract",
        "source_candidate_id": source_candidate_id,
        "source_candidate_found": bool(candidate),
        "source_candidate_goal": _clean_text(candidate.get("goal"), 240) if candidate else "",
        "evidence_paths": evidence_paths,
        "workspace_path": _clean_text(workspace.get("path"), 500),
        "resolved": bool(effective_focus) and relation != "unresolved",
    }


def compact_focus_for_candidate(contract: dict[str, Any] | None) -> dict[str, Any]:
    """在任务血缘候选中保留稳定焦点事实。"""
    if not isinstance(contract, dict):
        return {}
    focus = normalize_focus_reference(contract.get("focus"))
    if not focus:
        return {}
    return {
        "relation": normalize_focus_relation(contract.get("focus_relation")),
        "focus": deepcopy(focus),
    }


def _candidate_by_id(
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    candidate_id: str,
) -> dict[str, Any] | None:
    if not candidate_id:
        return None
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("candidate_id") or "").strip() == candidate_id:
            return candidate
    return None


def _candidate_paths(candidate: dict[str, Any] | None) -> list[str]:
    if not isinstance(candidate, dict):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for key in ("actual_paths", "target_written_paths", "changed_paths", "verified_paths"):
        for value in candidate.get(key) or []:
            path = _clean_text(value, 500)
            normalized = path.replace("\\", "/").lower()
            if not path or normalized in seen:
                continue
            seen.add(normalized)
            result.append(path)
            if len(result) >= 12:
                return result
    return result


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]
