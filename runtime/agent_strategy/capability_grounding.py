"""Ground model task contracts against runtime capability facts.

The model owns the first semantic judgment.  The runtime owns the current
capability snapshot.  This module reconciles the two without adding
scenario-specific branches to the runner.
"""

from __future__ import annotations

import re
from typing import Any


GENERIC_CAPABILITY_TOKENS = {
    "asset",
    "assets",
    "call",
    "capability",
    "change",
    "code",
    "download",
    "execute",
    "external",
    "generate",
    "get",
    "images",
    "import",
    "info",
    "local",
    "mcp",
    "model",
    "object",
    "poll",
    "scene",
    "search",
    "service",
    "set",
    "state",
    "status",
    "text",
    "tool",
    "tools",
    "via",
    "viewport",
}


def ground_task_contract_with_capabilities(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    user_content: str = "",
) -> bool:
    """Align a task contract with available external-state capabilities.

    The function is deliberately conservative: it does not turn answer-only
    questions into actions.  It only grounds contracts that already require a
    state change and whose text matches a runtime-known external-state
    capability.  A capability may be available, degraded, or currently
    unavailable through an issue record; preflight will decide how to present
    that readiness fact to the model.
    """
    if not isinstance(contract, dict) or not isinstance(snapshot, dict):
        return False
    if not bool(contract.get("requires_state_change")):
        return False

    text = _contract_match_text(contract, user_content=user_content)
    if not text:
        return False
    capability = _best_external_state_capability(snapshot, text)
    if not capability:
        return False

    capability_id = str(capability.get("id") or "").strip()
    if not capability_id:
        return False

    changed = _add_capability_id(contract, capability_id)
    explicit_file_artifact = _user_requested_file_artifact(user_content)
    if not explicit_file_artifact:
        changed = _ground_external_state_deliverable(contract, capability_id) or changed
        if bool(contract.get("requires_write")):
            contract["requires_write"] = False
            changed = True
    else:
        changed = _attach_capability_to_deliverables(contract, capability_id) or changed

    if _remove_contradicted_blockers(contract, capability):
        changed = True
    if changed:
        _add_system_override(contract, "capability_grounded")
    return changed


def _best_external_state_capability(snapshot: dict[str, Any], text: str) -> dict[str, Any] | None:
    available = _best_available_external_state_capability(snapshot, text)
    if available:
        return available
    return _best_issue_external_state_capability(snapshot, text)


def _best_available_external_state_capability(snapshot: dict[str, Any], text: str) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for capability in snapshot.get("capabilities") or []:
        if not isinstance(capability, dict) or not bool(capability.get("available")):
            continue
        if "external_state_change" not in _string_set(capability.get("available_effects")):
            continue
        tokens = _capability_tokens(capability)
        score = _capability_match_score(tokens, text)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, capability)
    return best[1] if best else None


def _best_issue_external_state_capability(snapshot: dict[str, Any], text: str) -> dict[str, Any] | None:
    """Return a matching unavailable external capability from readiness issues.

    MCP services can be known to the runtime even when their dynamic tools are
    not registered because the service is stopped or protocol-disconnected.
    Those facts should still help the model understand the target boundary.
    """
    best: tuple[int, dict[str, Any]] | None = None
    issues = snapshot.get("capability_issues") if isinstance(snapshot.get("capability_issues"), list) else []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        capability_id = str(issue.get("capability_id") or "").strip()
        if not capability_id:
            continue
        if not _issue_represents_external_capability(issue):
            continue
        tokens = _capability_issue_tokens(issue)
        score = _capability_match_score(tokens, text)
        if score <= 0:
            continue
        capability = {
            "id": capability_id,
            "name": str(issue.get("name") or capability_id),
            "description": str(issue.get("message") or ""),
            "tool_ids": [],
            "available": False,
            "source": str(issue.get("source_type") or ""),
        }
        if best is None or score > best[0]:
            best = (score, capability)
    return best[1] if best else None


def _issue_represents_external_capability(issue: dict[str, Any]) -> bool:
    source_type = str(issue.get("source_type") or "").strip().lower()
    capability_id = str(issue.get("capability_id") or "").strip().lower()
    return source_type == "mcp" or capability_id.startswith("mcp.")


def _capability_tokens(capability: dict[str, Any]) -> set[str]:
    parts: list[str] = [
        str(capability.get("id") or ""),
        str(capability.get("name") or ""),
        str(capability.get("description") or ""),
    ]
    parts.extend(str(item) for item in capability.get("tool_ids") or [])
    tokens: set[str] = set()
    for part in parts:
        for token in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", part.lower()):
            if not token:
                continue
            if token in GENERIC_CAPABILITY_TOKENS:
                continue
            if len(token) < 3 and not _contains_cjk(token):
                continue
            tokens.add(token)
    return tokens


def _capability_issue_tokens(issue: dict[str, Any]) -> set[str]:
    parts = [
        str(issue.get("capability_id") or ""),
        str(issue.get("name") or ""),
        str(issue.get("source_id") or ""),
        str(issue.get("message") or ""),
        str(issue.get("tool_id") or ""),
        str(issue.get("remote_name") or ""),
    ]
    tokens: set[str] = set()
    for part in parts:
        for token in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", part.lower()):
            if not token:
                continue
            if token in GENERIC_CAPABILITY_TOKENS:
                continue
            if len(token) < 3 and not _contains_cjk(token):
                continue
            tokens.add(token)
    return tokens


def _capability_match_score(tokens: set[str], text: str) -> int:
    score = 0
    for token in tokens:
        if _token_in_text(token, text):
            score += 3 if len(token) >= 5 else 2
    return score


def _token_in_text(token: str, text: str) -> bool:
    if _contains_cjk(token):
        return token in text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text))


def _contract_match_text(contract: dict[str, Any], *, user_content: str) -> str:
    parts = [str(user_content or ""), str(contract.get("goal") or "")]
    raw = contract.get("raw_model_contract")
    if isinstance(raw, dict):
        parts.append(str(raw.get("goal") or ""))
    for source in (contract, raw if isinstance(raw, dict) else {}):
        deliverables = source.get("deliverables") if isinstance(source.get("deliverables"), list) else []
        for item in deliverables:
            if not isinstance(item, dict):
                continue
            parts.extend(
                str(item.get(key) or "")
                for key in ("kind", "description", "capability_id", "path_hint", "path")
            )
    return _normalize_match_text(" ".join(parts))


def _normalize_match_text(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9._\-\u4e00-\u9fff]+", " ", str(value or "").lower()),
    ).strip()


def _user_requested_file_artifact(user_content: str) -> bool:
    text = _normalize_match_text(user_content)
    if not text:
        return False
    terms = (
        "export",
        "save as",
        "save file",
        "write file",
        "generate file",
        "\u4fdd\u5b58\u4e3a",
        "\u53e6\u5b58\u4e3a",
        "\u5bfc\u51fa",
        "\u8f93\u51fa\u4e3a",
        "\u751f\u6210\u6587\u4ef6",
        "\u4fdd\u5b58\u6587\u4ef6",
    )
    if any(term in text for term in terms):
        return True
    return bool(re.search(r"\.(blend|fbx|obj|glb|gltf|dae|stl|usd|usdz)(?![a-z0-9])", text))


def _add_capability_id(contract: dict[str, Any], capability_id: str) -> bool:
    values = [
        str(item).strip()
        for item in contract.get("capability_ids") or []
        if str(item).strip()
    ]
    if capability_id in values:
        return False
    values.insert(0, capability_id)
    contract["capability_ids"] = list(dict.fromkeys(values))[:6]
    return True


def _ground_external_state_deliverable(contract: dict[str, Any], capability_id: str) -> bool:
    deliverables = contract.get("deliverables") if isinstance(contract.get("deliverables"), list) else []
    description = str(contract.get("goal") or "External application state").strip()
    changed = False
    grounded: list[dict[str, str]] = []
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind == "external_state":
            copy = dict(item)
            if copy.get("capability_id") != capability_id:
                copy["capability_id"] = capability_id
                changed = True
            grounded.append(copy)
        else:
            changed = True
    if not grounded:
        grounded.append({
            "kind": "external_state",
            "path_hint": "",
            "path_policy": "hint",
            "capability_id": capability_id,
            "description": description,
        })
        changed = True
    if contract.get("deliverables") != grounded:
        contract["deliverables"] = grounded[:6]
        changed = True
    first_action = str(contract.get("first_action") or "")
    if first_action not in {"plan", "use_tool"}:
        contract["first_action"] = "use_tool"
        changed = True
    contract["requires_state_change"] = True
    contract["requires_verification"] = True
    return changed


def _attach_capability_to_deliverables(contract: dict[str, Any], capability_id: str) -> bool:
    deliverables = contract.get("deliverables") if isinstance(contract.get("deliverables"), list) else []
    changed = False
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        if not str(item.get("capability_id") or "").strip():
            item["capability_id"] = capability_id
            changed = True
    return changed


def _remove_contradicted_blockers(contract: dict[str, Any], capability: dict[str, Any]) -> bool:
    blockers = contract.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        return False
    tokens = _capability_tokens(capability)
    kept: list[Any] = []
    changed = False
    for blocker in blockers:
        text = _normalize_match_text(str(blocker or ""))
        if _looks_like_missing_capability_blocker(text) and (
            any(_token_in_text(token, text) for token in tokens)
            or "capability" in text
            or "\u80fd\u529b" in text
        ):
            changed = True
            continue
        kept.append(blocker)
    if changed:
        contract["blockers"] = kept
    return changed


def _looks_like_missing_capability_blocker(text: str) -> bool:
    terms = (
        "missing",
        "lack",
        "unavailable",
        "not available",
        "cannot",
        "no capability",
        "\u7f3a\u5c11",
        "\u6ca1\u6709",
        "\u65e0\u6cd5",
        "\u4e0d\u53ef\u7528",
    )
    return any(term in text for term in terms)


def _add_system_override(contract: dict[str, Any], value: str) -> None:
    overrides = [
        str(item)
        for item in contract.get("system_overrides") or []
        if str(item or "").strip()
    ]
    overrides.append(value)
    contract["system_overrides"] = list(dict.fromkeys(overrides))


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_set(value: Any) -> set[str]:
    return set(_string_list(value))
