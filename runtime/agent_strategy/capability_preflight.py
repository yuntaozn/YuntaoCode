"""Capability snapshot and preflight helpers.

The model may decide which capability a task needs.  The runtime owns the
available capability snapshot and readiness facts.  Preflight stays advisory
unless a separate safety policy explicitly asks for an enforced boundary.
"""

from __future__ import annotations

from typing import Any

from runtime.core.capability import normalize_provider_kind

from .capability_router import build_capability_catalog


CAPABILITY_SNAPSHOT_SCHEMA_VERSION = "capability_snapshot.v1"
CAPABILITY_PREFLIGHT_SCHEMA_VERSION = "capability_preflight.v2"
VISUAL_ARTIFACT_KINDS = {
    "screenshot",
    "image",
    "render",
    "rendered_image",
    "viewport_screenshot",
    "visual_capture",
    "pdf",
}


def build_capability_snapshot(
    tool_specs: list[dict[str, Any]],
    *,
    state_changing_tool_ids: set[str] | None = None,
    capability_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a runtime-owned capability snapshot from tool specs.

    Each spec may include ``available``.  Missing ``available`` means true so
    older callers remain compatible.
    """
    normalized_specs: list[dict[str, Any]] = []
    for spec in tool_specs:
        if not isinstance(spec, dict):
            continue
        tool_id = str(spec.get("id") or "").strip()
        if not tool_id:
            continue
        item = dict(spec)
        item["id"] = tool_id
        provider_id = str(item.get("provider_id") or item.get("source_id") or tool_id.split(".", 1)[0]).strip()
        provider_kind = normalize_provider_kind(
            str(item.get("provider_kind") or ""),
            fallback=str(item.get("source_type") or "builtin"),
        )
        item["provider_id"] = provider_id
        item["provider_kind"] = provider_kind
        if not isinstance(item.get("provider"), dict):
            item["provider"] = {
                "provider_id": provider_id,
                "provider_kind": provider_kind,
                "source_type": str(item.get("source_type") or provider_kind),
                "source_id": str(item.get("source_id") or provider_id),
            }
        item["available"] = bool(spec.get("available", True))
        normalized_specs.append(item)

    spec_by_id = {str(spec["id"]): spec for spec in normalized_specs}
    state_ids = set(state_changing_tool_ids or set())
    capabilities: list[dict[str, Any]] = []
    for contract in build_capability_catalog(normalized_specs):
        data = contract.to_public_dict()
        tool_ids = [tool_id for tool_id in data.get("tool_ids", []) if tool_id in spec_by_id]
        available_tool_ids = [
            tool_id
            for tool_id in tool_ids
            if bool(spec_by_id.get(tool_id, {}).get("available", True))
        ]
        available_specs = [spec_by_id[tool_id] for tool_id in available_tool_ids]
        data["tool_ids"] = tool_ids
        data["available_tool_ids"] = available_tool_ids
        data["unavailable_tool_ids"] = [
            tool_id for tool_id in tool_ids if tool_id not in set(available_tool_ids)
        ]
        data["degraded_tool_ids"] = [
            tool_id
            for tool_id in tool_ids
            if _tool_health(spec_by_id.get(tool_id, {})) == "degraded"
        ]
        data["tool_health"] = {
            tool_id: _tool_health(spec_by_id.get(tool_id, {}))
            for tool_id in tool_ids
            if _tool_health(spec_by_id.get(tool_id, {})) != "available"
        }
        data["available_artifacts"] = sorted({
            item
            for spec in available_specs
            for item in _string_list(spec.get("artifacts"))
        })
        data["available_effects"] = sorted({
            item
            for spec in available_specs
            for item in _string_list(spec.get("effects"))
        })
        data["available_roles"] = sorted({
            item
            for spec in available_specs
            for item in _string_list(spec.get("roles"))
        })
        data["provider_kinds"] = sorted({
            str(spec.get("provider_kind") or "unknown")
            for spec in [spec_by_id[tool_id] for tool_id in tool_ids]
            if str(spec.get("provider_kind") or "").strip()
        })
        data["available_provider_kinds"] = sorted({
            str(spec.get("provider_kind") or "unknown")
            for spec in available_specs
            if str(spec.get("provider_kind") or "").strip()
        })
        data["provider_ids"] = sorted({
            str(spec.get("provider_id") or "")
            for spec in [spec_by_id[tool_id] for tool_id in tool_ids]
            if str(spec.get("provider_id") or "").strip()
        })
        data["available_verification_strengths"] = sorted({
            str(spec.get("verification_strength") or "").strip()
            for spec in available_specs
            if str(spec.get("verification_strength") or "").strip()
        })
        data["available"] = bool(available_tool_ids)
        capabilities.append(data)

    available_tool_ids = sorted(
        tool_id for tool_id, spec in spec_by_id.items() if bool(spec.get("available", True))
    )
    external_state_tool_ids = sorted(
        tool_id
        for tool_id, spec in spec_by_id.items()
        if "external_state_change" in _string_set(spec.get("effects"))
    )
    external_state_capability_ids = sorted({
        str(capability.get("id") or "")
        for capability in capabilities
        if "external_state_change" in _string_set(capability.get("available_effects"))
    } - {""})
    degraded_tool_ids = sorted(
        tool_id
        for tool_id, spec in spec_by_id.items()
        if _tool_health(spec) == "degraded"
    )
    provider_kinds = sorted({
        str(spec.get("provider_kind") or "unknown")
        for spec in spec_by_id.values()
        if str(spec.get("provider_kind") or "").strip()
    })
    available_provider_kinds = sorted({
        str(spec.get("provider_kind") or "unknown")
        for spec in spec_by_id.values()
        if bool(spec.get("available", True)) and str(spec.get("provider_kind") or "").strip()
    })

    return {
        "schema_version": CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
        "tool_count": len(normalized_specs),
        "available_tool_count": len(available_tool_ids),
        "tool_ids": sorted(spec_by_id),
        "available_tool_ids": available_tool_ids,
        "unavailable_tool_ids": sorted(set(spec_by_id) - set(available_tool_ids)),
        "degraded_tool_ids": degraded_tool_ids,
        "tool_health": {
            tool_id: _tool_health(spec)
            for tool_id, spec in sorted(spec_by_id.items())
            if _tool_health(spec) != "available"
        },
        "provider_kinds": provider_kinds,
        "available_provider_kinds": available_provider_kinds,
        "tools_by_provider_kind": _tools_by_provider_kind(spec_by_id),
        "providers": _provider_summaries(spec_by_id),
        "tool_last_errors": {
            tool_id: str(spec.get("tool_last_error") or "").strip()
            for tool_id, spec in sorted(spec_by_id.items())
            if str(spec.get("tool_last_error") or "").strip()
        },
        "state_changing_tool_ids": sorted(state_ids),
        "external_state_tool_ids": external_state_tool_ids,
        "external_state_capability_ids": external_state_capability_ids,
        "capability_issues": _normalize_capability_issues(capability_issues),
        "verification_tool_strengths": {
            tool_id: str(spec.get("verification_strength") or "").strip()
            for tool_id, spec in sorted(spec_by_id.items())
            if bool(spec.get("available", True))
            and str(spec.get("verification_strength") or "").strip()
        },
        "tool_roles": {
            tool_id: _string_list(spec.get("roles"))
            for tool_id, spec in sorted(spec_by_id.items())
            if _string_list(spec.get("roles"))
        },
        "tool_effects": {
            tool_id: _string_list(spec.get("effects"))
            for tool_id, spec in sorted(spec_by_id.items())
            if _string_list(spec.get("effects"))
        },
        "tool_artifacts": {
            tool_id: _string_list(spec.get("artifacts"))
            for tool_id, spec in sorted(spec_by_id.items())
            if _string_list(spec.get("artifacts"))
        },
        "capabilities": capabilities,
    }


def task_contract_capability_ids(contract: dict[str, Any]) -> list[str]:
    """Return model-declared capability IDs from a task contract."""
    result: list[str] = []
    for key in ("capability_ids", "target_capability_ids"):
        value = contract.get(key)
        if isinstance(value, list):
            result.extend(str(item).strip() for item in value if str(item).strip())
    single = str(contract.get("capability_id") or "").strip()
    if single:
        result.append(single)
    deliverables = contract.get("deliverables")
    if isinstance(deliverables, list):
        for item in deliverables:
            if not isinstance(item, dict):
                continue
            capability_id = str(item.get("capability_id") or "").strip()
            if capability_id:
                result.append(capability_id)
    return list(dict.fromkeys(result))


def contract_requires_external_state_capability(contract: dict[str, Any]) -> bool:
    """Return whether a task explicitly targets external state."""
    if not bool(contract.get("requires_state_change")):
        return False
    deliverables = contract.get("deliverables")
    if not isinstance(deliverables, list):
        return False
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip() == "external_state":
            return True
    return False


def preflight_task_capabilities(
    contract: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Describe task capability needs against a runtime snapshot.

    Preflight is an advisory layer.  It should tell the model and UI what is
    available or degraded, but it must not force a task to stop or silently
    constrain the model's strategy.  Concrete safety decisions stay attached to
    tool execution and confirmation.
    """
    capabilities = snapshot.get("capabilities") if isinstance(snapshot.get("capabilities"), list) else []
    capability_issues = (
        snapshot.get("capability_issues")
        if isinstance(snapshot.get("capability_issues"), list)
        else []
    )
    issue_by_capability_id = {
        str(item.get("capability_id") or ""): item
        for item in capability_issues
        if isinstance(item, dict) and str(item.get("capability_id") or "").strip()
    }
    by_id = {
        str(item.get("id") or ""): item
        for item in capabilities
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    available_tool_ids = set(_string_list(snapshot.get("available_tool_ids")))
    state_changing_tool_ids = set(_string_list(snapshot.get("state_changing_tool_ids")))
    target_capability_ids = task_contract_capability_ids(contract)
    requires_external_state = contract_requires_external_state_capability(contract)
    advisories: list[dict[str, Any]] = []
    target_tool_ids: set[str] = set()
    target_has_external_state = False

    for capability_id in target_capability_ids:
        capability = by_id.get(capability_id)
        if not capability:
            issue = issue_by_capability_id.get(capability_id)
            if issue:
                advisories.append(_issue_to_advisory(issue))
                continue
            advisories.append({
                "code": "unknown_capability",
                "capability_id": capability_id,
                "message": f"Capability is not registered in this runtime snapshot: {capability_id}",
            })
            continue
        capability_available_tools = set(_string_list(capability.get("available_tool_ids")))
        if not capability_available_tools:
            advisories.append({
                "code": "capability_unavailable",
                "capability_id": capability_id,
                "message": f"Capability is registered but has no available tools: {capability_id}",
            })
            continue
        target_tool_ids.update(capability_available_tools)
        if "external_state_change" in _string_set(capability.get("available_effects")):
            target_has_external_state = True

    existing_advisories = {
        (
            str(item.get("code") or ""),
            str(item.get("capability_id") or ""),
            str(item.get("tool_id") or ""),
        )
        for item in advisories
    }
    for issue in _normalize_capability_issues([
        item for item in capability_issues if isinstance(item, dict)
    ]):
        capability_id = str(issue.get("capability_id") or "")
        if target_capability_ids and capability_id not in set(target_capability_ids):
            continue
        if not target_capability_ids and not (
            requires_external_state and str(issue.get("source_type") or "") == "mcp"
        ):
            continue
        advisory = _issue_to_advisory(issue)
        key = (
            str(advisory.get("code") or ""),
            str(advisory.get("capability_id") or ""),
            str(advisory.get("tool_id") or ""),
        )
        if key not in existing_advisories:
            advisories.append(advisory)
            existing_advisories.add(key)

    external_state_capabilities = [
        item
        for item in capabilities
        if isinstance(item, dict)
        and bool(item.get("available"))
        and "external_state_change" in _string_set(item.get("available_effects"))
    ]
    if requires_external_state:
        if target_capability_ids and target_tool_ids and not target_has_external_state:
            advisories.append({
                "code": "target_capability_lacks_external_state_effect",
                "capability_id": ",".join(target_capability_ids),
                "message": "The declared target capability does not report external_state_change.",
            })
        if not target_capability_ids:
            for capability in external_state_capabilities:
                target_tool_ids.update(_string_list(capability.get("available_tool_ids")))
        if not target_tool_ids:
            issue_candidates = _external_state_capability_issues(
                capability_issues,
                target_capability_ids=target_capability_ids,
            )
            if issue_candidates:
                existing = {
                    (
                        str(item.get("code") or ""),
                        str(item.get("capability_id") or ""),
                    )
                    for item in advisories
                }
                for issue in issue_candidates[:4]:
                    advisory = _issue_to_advisory(issue)
                    key = (
                        str(advisory.get("code") or ""),
                        str(advisory.get("capability_id") or ""),
                    )
                    if key not in existing:
                        advisories.append(advisory)
                        existing.add(key)
            else:
                advisories.append({
                    "code": "missing_external_state_capability",
                    "message": "This task targets external application state, but no available capability reports external_state_change.",
                })

    if (
        "visual" in _required_verification_modalities(contract)
        and target_tool_ids
        and not _healthy_visual_tool_ids(snapshot, target_tool_ids)
    ):
        advisories.append({
            "code": "visual_verification_path_uncertain",
            "message": (
                "The task asks for visual verification, but no healthy target tool "
                "currently advertises a visual artifact such as screenshot, image, "
                "render, or PDF. This is advisory only: the model may use any safe "
                "available strategy that returns a visual artifact, ask the user, "
                "or report that visual verification is unavailable."
            ),
        })

    visual_verification_tool_ids = (
        _visual_verification_tool_ids(snapshot)
        if "visual" in _required_verification_modalities(contract)
        else []
    )
    if "visual" in _required_verification_modalities(contract) and not visual_verification_tool_ids:
        visual_readiness = _visual_readiness_issues(snapshot)
        if visual_readiness:
            details = "; ".join(
                f"{item['tool_id']} ({item['health']}): {item['message']}"
                for item in visual_readiness[:4]
            )
            advisories.append({
                "code": "visual_verification_provider_unavailable",
                "message": (
                    "Visual verification providers are currently unavailable or degraded. "
                    f"Known readiness facts: {details}"
                ),
                "tools": visual_readiness[:4],
            })
    return {
        "schema_version": CAPABILITY_PREFLIGHT_SCHEMA_VERSION,
        "ok": True,
        "advisories": advisories,
        "readiness_issues": advisories,
        "target_capability_ids": target_capability_ids,
        "requires_external_state_capability": requires_external_state,
        # Compatibility field for older diagnostics. New preflight records do
        # not rank tools or select a route for the model.
        "preferred_tool_ids": None,
        "visual_verification_tool_ids": visual_verification_tool_ids,
        "route_hint": {
            "policy": "advisory",
            "strategy_owner": "model",
            "safety_owner": "tool_execution_guard",
        },
    }


def tool_allowed_by_preflight(preflight: dict[str, Any] | None, tool_id: str) -> bool:
    """Preflight is advisory; it never hides or rejects a visible tool."""
    return True


def preflight_advisory_messages(preflight: dict[str, Any] | None) -> list[str]:
    advisories = preflight.get("advisories") if isinstance(preflight, dict) else []
    if not isinstance(advisories, list):
        return []
    result: list[str] = []
    for advisory in advisories:
        if not isinstance(advisory, dict):
            continue
        message = str(advisory.get("message") or advisory.get("code") or "").strip()
        if message:
            result.append(message)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _tools_by_provider_kind(spec_by_id: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for tool_id, spec in sorted(spec_by_id.items()):
        provider_kind = str(spec.get("provider_kind") or "unknown").strip() or "unknown"
        grouped.setdefault(provider_kind, []).append(tool_id)
    return grouped


def _provider_summaries(spec_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for tool_id, spec in sorted(spec_by_id.items()):
        provider_kind = str(spec.get("provider_kind") or "unknown").strip() or "unknown"
        provider_id = str(spec.get("provider_id") or spec.get("source_id") or tool_id.split(".", 1)[0]).strip()
        key = (provider_kind, provider_id)
        provider = spec.get("provider") if isinstance(spec.get("provider"), dict) else {}
        bucket = grouped.setdefault(
            key,
            {
                "provider_kind": provider_kind,
                "provider_id": provider_id,
                "source_type": str(provider.get("source_type") or spec.get("source_type") or provider_kind),
                "source_id": str(provider.get("source_id") or spec.get("source_id") or provider_id),
                "display_name": str(provider.get("display_name") or provider_id),
                "lifecycle": str(provider.get("lifecycle") or ""),
                "tool_ids": [],
                "available_tool_ids": [],
                "degraded_tool_ids": [],
            },
        )
        bucket["tool_ids"].append(tool_id)
        if bool(spec.get("available", True)):
            bucket["available_tool_ids"].append(tool_id)
        if _tool_health(spec) == "degraded":
            bucket["degraded_tool_ids"].append(tool_id)
    return [
        {
            **bucket,
            "tool_ids": list(dict.fromkeys(bucket["tool_ids"])),
            "available_tool_ids": list(dict.fromkeys(bucket["available_tool_ids"])),
            "degraded_tool_ids": list(dict.fromkeys(bucket["degraded_tool_ids"])),
            "available": bool(bucket["available_tool_ids"]),
        }
        for bucket in grouped.values()
    ]


def _string_set(value: Any) -> set[str]:
    return set(_string_list(value))


def _tool_health(spec: dict[str, Any]) -> str:
    value = str(spec.get("tool_health") or "available").strip().lower()
    return value if value in {"available", "degraded", "unavailable", "unknown"} else "available"


def _required_verification_modalities(contract: dict[str, Any]) -> set[str]:
    values = contract.get("required_verification_modalities")
    if not isinstance(values, list):
        return set()
    return {
        str(item or "").strip().lower()
        for item in values
        if str(item or "").strip()
    }


def _healthy_visual_tool_ids(snapshot: dict[str, Any], tool_ids: set[str]) -> list[str]:
    return [
        tool_id for tool_id in sorted(tool_ids)
        if _tool_snapshot_health(snapshot, tool_id) == "available"
        and _tool_supports_visual_artifact(snapshot, tool_id)
    ]


def _visual_verification_tool_ids(snapshot: dict[str, Any]) -> list[str]:
    tool_ids = set(_string_list(snapshot.get("available_tool_ids")))
    candidates = [
        tool_id for tool_id in _healthy_visual_tool_ids(snapshot, tool_ids)
        if _tool_snapshot_roles(snapshot, tool_id) & {"verification", "evidence"}
    ]
    return sorted(dict.fromkeys(candidates), key=_visual_tool_prompt_order)


def _visual_readiness_issues(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    health = snapshot.get("tool_health") if isinstance(snapshot.get("tool_health"), dict) else {}
    last_errors = (
        snapshot.get("tool_last_errors")
        if isinstance(snapshot.get("tool_last_errors"), dict)
        else {}
    )
    tool_ids = set(_string_list(snapshot.get("tool_ids")))
    result: list[dict[str, str]] = []
    for tool_id in sorted(tool_ids, key=_visual_tool_prompt_order):
        tool_health = str(health.get(tool_id) or "available").strip().lower()
        if tool_health == "available":
            continue
        if not _tool_supports_visual_artifact(snapshot, tool_id):
            continue
        if not (_tool_snapshot_roles(snapshot, tool_id) & {"verification", "evidence"}):
            continue
        result.append({
            "tool_id": tool_id,
            "health": tool_health,
            "message": str(last_errors.get(tool_id) or "runtime dependency is not ready"),
        })
    return result


def _visual_tool_prompt_order(tool_id: str) -> tuple[int, str]:
    order = {
        "preview.capture_local_html": 0,
        "preview.capture_file": 1,
        "preview.interact_page": 2,
        "preview.capture_url": 3,
        "web.capture_page": 4,
    }
    return (order.get(tool_id, 50), tool_id)


def _tool_supports_visual_artifact(snapshot: dict[str, Any], tool_id: str) -> bool:
    artifacts = _tool_snapshot_artifacts(snapshot, tool_id)
    if artifacts & VISUAL_ARTIFACT_KINDS:
        return True
    normalized = str(tool_id or "").strip().lower()
    visual_terms = ("screenshot", "capture", "render", "viewport", "image", "pdf")
    return any(term in normalized for term in visual_terms)


def _tool_snapshot_health(snapshot: dict[str, Any], tool_id: str) -> str:
    health = snapshot.get("tool_health") if isinstance(snapshot.get("tool_health"), dict) else {}
    value = str(health.get(tool_id) or "available").strip().lower()
    return value if value in {"available", "degraded", "unavailable", "unknown"} else "available"


def _tool_snapshot_roles(snapshot: dict[str, Any], tool_id: str) -> set[str]:
    return _tool_snapshot_string_set(snapshot, "tool_roles", tool_id)


def _tool_snapshot_artifacts(snapshot: dict[str, Any], tool_id: str) -> set[str]:
    return _tool_snapshot_string_set(snapshot, "tool_artifacts", tool_id)


def _tool_snapshot_string_set(snapshot: dict[str, Any], key: str, tool_id: str) -> set[str]:
    values = snapshot.get(key) if isinstance(snapshot.get(key), dict) else {}
    return {
        str(item or "").strip().lower()
        for item in values.get(tool_id, [])
        if str(item or "").strip()
    }


def _normalize_capability_issues(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("capability_id") or "").strip()
        message = str(item.get("message") or "").strip()
        if not capability_id or not message:
            continue
        normalized = {
            "code": str(item.get("code") or "capability_unavailable").strip(),
            "capability_id": capability_id,
            "message": message,
        }
        for key in ("source_type", "source_id", "name", "state", "recommended_action"):
            text = str(item.get(key) or "").strip()
            if text:
                normalized[key] = text
        for key in ("tool_id", "remote_name"):
            text = str(item.get(key) or "").strip()
            if text:
                normalized[key] = text
        result.append(normalized)
    return result


def _external_state_capability_issues(
    capability_issues: list[Any],
    *,
    target_capability_ids: list[str],
) -> list[dict[str, Any]]:
    normalized = _normalize_capability_issues([
        item for item in capability_issues if isinstance(item, dict)
    ])
    if target_capability_ids:
        target_set = set(target_capability_ids)
        return [
            item for item in normalized
            if str(item.get("capability_id") or "") in target_set
        ]
    return [
        item for item in normalized
        if str(item.get("source_type") or "") == "mcp"
    ]


def _issue_to_advisory(issue: dict[str, Any]) -> dict[str, Any]:
    advisory = {
        "code": str(issue.get("code") or "capability_unavailable"),
        "capability_id": str(issue.get("capability_id") or ""),
        "message": str(issue.get("message") or "Capability is unavailable."),
    }
    recommended_action = str(issue.get("recommended_action") or "").strip()
    if recommended_action:
        advisory["recommended_action"] = recommended_action
    source_type = str(issue.get("source_type") or "").strip()
    source_id = str(issue.get("source_id") or "").strip()
    if source_type:
        advisory["source_type"] = source_type
    if source_id:
        advisory["source_id"] = source_id
    tool_id = str(issue.get("tool_id") or "").strip()
    remote_name = str(issue.get("remote_name") or "").strip()
    if tool_id:
        advisory["tool_id"] = tool_id
    if remote_name:
        advisory["remote_name"] = remote_name
    return advisory
