from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.core.capability import normalize_provider_kind


CAPABILITY_ROUTER_SCHEMA_VERSION = "0.1"
TASK_ROUTE_EVIDENCE_SCHEMA_VERSION = "task_route_evidence.v1"


@dataclass(frozen=True)
class CapabilityContract:
    id: str
    name: str
    description: str
    tool_ids: tuple[str, ...]
    artifacts: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    verification_strengths: tuple[str, ...] = ()
    requires_confirmation: bool = False
    long_running: bool = False
    retry_safe: bool = False
    idempotent: bool = False
    source: str = "builtin"
    provider_kinds: tuple[str, ...] = ("builtin",)
    provider_ids: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_ROUTER_SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tool_ids": list(self.tool_ids),
            "artifacts": list(self.artifacts),
            "effects": list(self.effects),
            "roles": list(self.roles),
            "verification_strengths": list(self.verification_strengths),
            "requires_confirmation": self.requires_confirmation,
            "long_running": self.long_running,
            "retry_safe": self.retry_safe,
            "idempotent": self.idempotent,
            "source": self.source,
            "provider_kinds": list(self.provider_kinds),
            "provider_ids": list(self.provider_ids),
        }


@dataclass(frozen=True)
class TaskRouteProposal:
    """Model-owned task understanding; runtime-owned capability validation.

    This object is intentionally separate from ``task_intent``.  Intent is a
    legacy execution hint; a route proposal describes what capability the model
    believes should be used and what artifact or verification the task needs.
    """

    goal: str
    capability_id: str
    tool_id: str | None = None
    expected_artifacts: tuple[str, ...] = ()
    requires_write: bool = False
    requires_verification: bool = False
    confidence: float = 0.0
    rationale: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_ROUTER_SCHEMA_VERSION,
            "goal": self.goal,
            "capability_id": self.capability_id,
            "tool_id": self.tool_id,
            "expected_artifacts": list(self.expected_artifacts),
            "requires_write": self.requires_write,
            "requires_verification": self.requires_verification,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


PREFIX_CAPABILITIES: dict[str, tuple[str, str, str]] = {
    "attachment": (
        "attachment.user_input",
        "Conversation Attachments",
        "Read user-provided, immutable conversation attachments without treating them as project files.",
    ),
    "filesystem": (
        "filesystem.local_files",
        "Local Files",
        "Read and scan files inside the configured workspace boundary.",
    ),
    "code": (
        "code.local_project",
        "Local Code",
        "Search and edit project code inside the configured workspace boundary.",
    ),
    "document": (
        "document.local_documents",
        "Local Documents",
        "Read, export, convert, merge, split, and translate local document files.",
    ),
    "shell": (
        "shell.local_command",
        "Local Shell",
        "Run local shell commands with runtime confirmation and workspace context.",
    ),
    "git": (
        "git.local_repo",
        "Local Git",
        "Inspect and update the local Git repository with confirmation for writes.",
    ),
    "web": (
        "web.network_fetch",
        "Web Fetch",
        "Fetch or search network content when the runtime and settings allow it.",
    ),
    "preview": (
        "preview.visual_debug",
        "Preview And Visual Debug",
        "Capture visual previews, screenshots, browser console errors, page errors, and failed requests for local HTML or URL-based UI verification.",
    ),
    "memory": (
        "memory.local_memory",
        "Local Memory",
        "Store and recall local project/user memories.",
    ),
}


TEXT_WRITE_CAPABILITY = (
    "code.text_write",
    "Text Write",
    "Create or modify text/code files through one unified write route. Draft chunk writing is suited to long prose, complete pages, multi-file rewrites, and non-trivial full artifacts: create_text_draft, repeated append_text_chunk, inspect when useful, then finalize_text_file. Precise edits fit small existing-file changes; direct write fits tiny complete files.",
)

TEXT_WRITE_TOOL_PROMPT_ORDER: dict[str, int] = {
    "filesystem.create_text_draft": 0,
    "filesystem.append_text_chunk": 1,
    "filesystem.inspect_text_draft": 2,
    "filesystem.finalize_text_file": 3,
    "code.edit_file": 10,
    "code.replace_text": 11,
    "code.apply_patch": 12,
    "filesystem.apply_changes": 13,
    "filesystem.write_file": 20,
}

TEMP_ARTIFACT_CAPABILITY = (
    "filesystem.temp_artifact",
    "Task Temporary Artifacts",
    "Create temporary scripts, probe outputs, and intermediate files in the task temp directory instead of the user project.",
)

LOCAL_STATE_CAPABILITY = (
    "filesystem.local_state",
    "Local File State",
    "Create, update, delete, or otherwise change files inside the configured workspace boundary with confirmation and audit evidence.",
)

EXPLICIT_CAPABILITIES: dict[str, tuple[str, str, str]] = {
    "code.apply_patch": TEXT_WRITE_CAPABILITY,
    "code.edit_file": TEXT_WRITE_CAPABILITY,
    "code.replace_text": TEXT_WRITE_CAPABILITY,
    "filesystem.write_file": TEXT_WRITE_CAPABILITY,
    "filesystem.apply_changes": (
        "filesystem.change_set",
        "Local File Change Set",
        "Apply a bounded transaction of local file create, overwrite, literal replace, and delete operations.",
    ),
    "filesystem.delete_file": LOCAL_STATE_CAPABILITY,
    "filesystem.create_text_draft": TEXT_WRITE_CAPABILITY,
    "filesystem.append_text_chunk": TEXT_WRITE_CAPABILITY,
    "filesystem.inspect_text_draft": TEXT_WRITE_CAPABILITY,
    "filesystem.finalize_text_file": TEXT_WRITE_CAPABILITY,
    "filesystem.write_temp_file": TEMP_ARTIFACT_CAPABILITY,
    "filesystem.transform_text": (
        "filesystem.text_transform",
        "Text Transform",
        "Apply a whitelisted local text transformation to an existing file, such as HTML entity unescape, without retransmitting the full artifact.",
    ),
    "document.extract_pdf_to_docx": (
        "document.pdf_to_docx",
        "PDF To Word",
        "Convert a PDF into a Word document, including text-only and approximate text-with-images modes.",
    ),
    "document.translate_docx": (
        "document.translate_docx",
        "Word Translation",
        "Translate a Word document into another language with checkpointed long-task progress.",
    ),
    "web.collect_site_assets": (
        "web.site_assets",
        "Site Assets",
        "Collect public website pages and static assets into a bounded local snapshot with an index.",
    ),
    "web.capture_page": (
        "web.page_capture",
        "Web Page Capture",
        "Render a public webpage and save it as PDF or screenshot for review and design reference.",
    ),
}


def infer_capability_metadata(tool_id: str) -> tuple[str, str, str]:
    if tool_id in EXPLICIT_CAPABILITIES:
        return EXPLICIT_CAPABILITIES[tool_id]
    prefix = tool_id.split(".", 1)[0]
    if prefix in PREFIX_CAPABILITIES:
        return PREFIX_CAPABILITIES[prefix]
    return (
        f"{prefix}.capability" if prefix else "unknown.capability",
        prefix.title() if prefix else "Unknown",
        "Runtime capability inferred from the tool namespace.",
    )


def capability_from_tool_spec(spec: dict[str, Any]) -> CapabilityContract:
    tool_id = str(spec.get("id") or "")
    provider_kind = normalize_provider_kind(
        str(spec.get("provider_kind") or ""),
        fallback=str(spec.get("source_type") or "builtin"),
    )
    provider_id = str(spec.get("provider_id") or spec.get("source_id") or tool_id.split(".", 1)[0]).strip()
    explicit_capability = str(spec.get("capability") or "").strip()
    if explicit_capability:
        inferred_id, inferred_name, inferred_description = infer_capability_metadata(tool_id)
        capability_id = explicit_capability
        name = inferred_name
        description = inferred_description
    else:
        capability_id, name, description = infer_capability_metadata(tool_id)
    return CapabilityContract(
        id=capability_id,
        name=name,
        description=description,
        tool_ids=(tool_id,) if tool_id else (),
        artifacts=tuple(str(item) for item in (spec.get("artifacts") or []) if item),
        effects=tuple(str(item) for item in (spec.get("effects") or []) if item),
        roles=tuple(str(item) for item in (spec.get("roles") or []) if item),
        verification_strengths=(
            (str(spec.get("verification_strength")).strip(),)
            if str(spec.get("verification_strength") or "").strip()
            else ()
        ),
        requires_confirmation=bool(spec.get("requires_confirmation")),
        long_running=bool(spec.get("long_running")),
        retry_safe=bool(spec.get("retry_safe")),
        idempotent=bool(spec.get("idempotent")),
        source=str(spec.get("source_type") or provider_kind),
        provider_kinds=(provider_kind,),
        provider_ids=(provider_id,) if provider_id else (),
    )


def merge_capability_contracts(items: list[CapabilityContract]) -> list[CapabilityContract]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        bucket = grouped.setdefault(
            item.id,
            {
                "name": item.name,
                "description": item.description,
                "tool_ids": [],
                "artifacts": set(),
                "effects": set(),
                "roles": set(),
                "verification_strengths": set(),
                "requires_confirmation": False,
                "long_running": False,
                "retry_safe": False,
                "idempotent": True,
                "source": item.source,
                "provider_kinds": set(),
                "provider_ids": [],
            },
        )
        bucket["tool_ids"].extend(item.tool_ids)
        bucket["artifacts"].update(item.artifacts)
        bucket["effects"].update(item.effects)
        bucket["roles"].update(item.roles)
        bucket["verification_strengths"].update(item.verification_strengths)
        bucket["requires_confirmation"] = bool(bucket["requires_confirmation"] or item.requires_confirmation)
        bucket["long_running"] = bool(bucket["long_running"] or item.long_running)
        bucket["retry_safe"] = bool(bucket["retry_safe"] or item.retry_safe)
        bucket["idempotent"] = bool(bucket["idempotent"] and item.idempotent)
        bucket["provider_kinds"].update(item.provider_kinds)
        bucket["provider_ids"].extend(item.provider_ids)
        if bucket["source"] != item.source:
            bucket["source"] = "mixed"

    return [
        CapabilityContract(
            id=capability_id,
            name=str(bucket["name"]),
            description=str(bucket["description"]),
            tool_ids=_ordered_tool_ids(capability_id, bucket["tool_ids"]),
            artifacts=tuple(sorted(bucket["artifacts"])),
            effects=tuple(sorted(bucket["effects"])),
            roles=tuple(sorted(bucket["roles"])),
            verification_strengths=tuple(sorted(bucket["verification_strengths"])),
            requires_confirmation=bool(bucket["requires_confirmation"]),
            long_running=bool(bucket["long_running"]),
            retry_safe=bool(bucket["retry_safe"]),
            idempotent=bool(bucket["idempotent"]),
            source=str(bucket["source"]),
            provider_kinds=tuple(sorted(bucket["provider_kinds"])) or ("unknown",),
            provider_ids=tuple(dict.fromkeys(bucket["provider_ids"])),
        )
        for capability_id, bucket in sorted(grouped.items())
    ]


def build_capability_catalog(tool_specs: list[dict[str, Any]]) -> list[CapabilityContract]:
    return merge_capability_contracts([capability_from_tool_spec(spec) for spec in tool_specs])


def _ordered_tool_ids(capability_id: str, tool_ids: list[str]) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(tool_ids))
    if capability_id != "code.text_write":
        return unique
    return tuple(
        sorted(
            unique,
            key=lambda tool_id: (
                TEXT_WRITE_TOOL_PROMPT_ORDER.get(tool_id, 100),
                unique.index(tool_id),
            ),
        )
    )


def order_tool_specs_for_model_prompt(tool_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(tool_specs))
    text_write_indexes = [
        index for index, spec in indexed
        if str(spec.get("id") or "") in TEXT_WRITE_TOOL_PROMPT_ORDER
    ]
    if not text_write_indexes:
        return list(tool_specs)
    first_text_write_index = min(text_write_indexes)

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        index, spec = item
        tool_id = str(spec.get("id") or "")
        if tool_id in TEXT_WRITE_TOOL_PROMPT_ORDER:
            return (
                first_text_write_index,
                TEXT_WRITE_TOOL_PROMPT_ORDER[tool_id],
                index,
            )
        return (index, 0, index)

    return [spec for _, spec in sorted(indexed, key=sort_key)]


def format_capability_catalog_for_prompt(
    catalog: list[CapabilityContract],
    *,
    max_items: int | None = None,
    compact: bool = False,
) -> str:
    visible = catalog if max_items is None else catalog[:max(0, max_items)]
    if compact:
        lines = [
            "",
            "## Available Runtime Capabilities",
            "<available_capabilities>",
        ]
        for item in visible:
            labels: list[str] = []
            if item.artifacts:
                labels.append(f"artifacts={','.join(item.artifacts[:3])}")
            if item.effects:
                labels.append(f"effects={','.join(item.effects[:3])}")
            if item.roles:
                labels.append(f"roles={','.join(item.roles[:3])}")
            if item.verification_strengths:
                labels.append(f"verification={','.join(item.verification_strengths[:3])}")
            if item.provider_kinds:
                labels.append(f"providers={','.join(item.provider_kinds[:3])}")
            suffix = f" ({'; '.join(labels)})" if labels else ""
            lines.append(f"- {item.id}: tools={', '.join(item.tool_ids[:8])}{suffix}")
        if len(catalog) > len(visible):
            lines.append(f"- ... {len(catalog) - len(visible)} more capabilities omitted")
        lines.append("</available_capabilities>")
        return "\n".join(lines)

    lines = [
        "",
        "## Capability Router",
        "你负责理解用户任务，优先从已注册能力中选择合适工具；系统负责校验权限、参数、确认、产物和执行轨迹。",
        "不要发明不存在的工具；需要文件产物的任务应调用能生成该产物的工具，不能只用自然语言宣布完成。",
        "如果缺少能力，先说明当前边界；只有用户明确要求扩展时，才创建隔离能力包草稿，优先沉淀为方法型 Skill。",
        "",
        "<available_capabilities>",
    ]
    for item in visible:
        flags: list[str] = []
        if item.artifacts:
            flags.append(f"artifacts={','.join(item.artifacts)}")
        if item.effects:
            flags.append(f"effects={','.join(item.effects)}")
        if item.roles:
            flags.append(f"roles={','.join(item.roles)}")
        if item.verification_strengths:
            flags.append(f"verification={','.join(item.verification_strengths)}")
        if item.long_running:
            flags.append("long_running=true")
        if item.retry_safe:
            flags.append("retry_safe=true")
        if item.requires_confirmation:
            flags.append("confirm=true")
        if item.provider_kinds:
            flags.append(f"providers={','.join(item.provider_kinds)}")
        suffix = f" ({'; '.join(flags)})" if flags else ""
        lines.append(f"- {item.id}: {item.description}; tools={', '.join(item.tool_ids)}{suffix}")
    if len(catalog) > len(visible):
        lines.append(f"- ... {len(catalog) - len(visible)} more capabilities omitted from prompt")
    lines.append("</available_capabilities>")
    return "\n".join(lines)


def parse_task_route_proposal(payload: dict[str, Any]) -> TaskRouteProposal:
    confidence = payload.get("confidence", 0.0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0
    confidence_value = max(0.0, min(1.0, confidence_value))
    artifacts = payload.get("expected_artifacts") or []
    if not isinstance(artifacts, list):
        artifacts = []
    return TaskRouteProposal(
        goal=str(payload.get("goal") or "").strip(),
        capability_id=str(payload.get("capability_id") or "").strip(),
        tool_id=str(payload.get("tool_id") or "").strip() or None,
        expected_artifacts=tuple(str(item) for item in artifacts if item),
        requires_write=bool(payload.get("requires_write")),
        requires_verification=bool(payload.get("requires_verification")),
        confidence=confidence_value,
        rationale=str(payload.get("rationale") or "").strip(),
    )


def validate_task_route_proposal(
    proposal: TaskRouteProposal,
    catalog: list[CapabilityContract],
) -> dict[str, Any]:
    by_capability = {item.id: item for item in catalog}
    contract = by_capability.get(proposal.capability_id)
    errors: list[str] = []
    if not proposal.goal:
        errors.append("missing_goal")
    if not contract:
        errors.append("unknown_capability")
    elif proposal.tool_id and proposal.tool_id not in contract.tool_ids:
        errors.append("tool_not_in_capability")
    return {
        "ok": not errors,
        "errors": errors,
        "proposal": proposal.to_public_dict(),
        "capability": contract.to_public_dict() if contract else None,
    }


def build_task_route_evidence(
    task_contract: dict[str, Any],
    capability_snapshot: dict[str, Any] | None,
    capability_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an evidence-only route record from the model task contract.

    The model still owns semantic route selection.  The runtime only converts
    the declared capability facts into a stable evidence shape and validates
    them against the current capability snapshot.
    """

    contract = task_contract if isinstance(task_contract, dict) else {}
    snapshot = capability_snapshot if isinstance(capability_snapshot, dict) else {}
    preflight = capability_preflight if isinstance(capability_preflight, dict) else {}
    capability_records = [
        item for item in snapshot.get("capabilities") or []
        if isinstance(item, dict)
    ]
    catalog = [_capability_contract_from_snapshot_item(item) for item in capability_records]
    route_proposals = _route_proposals_from_contract(contract)
    validations = [
        validate_task_route_proposal(proposal, catalog)
        for proposal in route_proposals
    ]
    advisory_codes = _validation_advisory_codes(validations)
    preflight_advisories = [
        str(item.get("code") or "").strip()
        for item in preflight.get("advisories") or []
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    return {
        "schema_version": TASK_ROUTE_EVIDENCE_SCHEMA_VERSION,
        "kind": "task_route_evidence",
        "boundary": "evidence_only",
        "strategy_owner": "model",
        "safety_owner": "runtime",
        "source": str(contract.get("source") or "unknown"),
        "goal": str(contract.get("goal") or "").strip(),
        "proposal_count": len(route_proposals),
        "valid_proposal_count": sum(1 for item in validations if item.get("ok")),
        "proposals": [proposal.to_public_dict() for proposal in route_proposals],
        "validations": validations,
        "target_capability_ids": _contract_capability_ids(contract),
        "preflight_target_capability_ids": _string_list(preflight.get("target_capability_ids")),
        "advisory_codes": list(dict.fromkeys([*advisory_codes, *preflight_advisories])),
        "flags": {
            "has_model_route": bool(route_proposals),
            "all_routes_valid": bool(route_proposals) and all(item.get("ok") for item in validations),
            "has_route_advisories": bool(advisory_codes or preflight_advisories),
            "has_unknown_capability": any(
                "unknown_capability" in (item.get("errors") or [])
                for item in validations
            ),
            "has_tool_mismatch": any(
                "tool_not_in_capability" in (item.get("errors") or [])
                for item in validations
            ),
        },
        "model_facts": _route_model_facts(route_proposals, validations, preflight),
    }


def format_task_route_evidence_for_prompt(evidence: dict[str, Any] | None) -> str:
    if not isinstance(evidence, dict):
        return ""
    if evidence.get("kind") != "task_route_evidence":
        return ""
    lines = [
        "Task route evidence:",
        "- Boundary: evidence only; the model owns task strategy, runtime validates capability facts.",
    ]
    for fact in _string_list(evidence.get("model_facts"))[:8]:
        lines.append(f"- {fact}")
    advisories = _string_list(evidence.get("advisory_codes"))
    if advisories:
        lines.append("- route_advisories=" + ", ".join(advisories[:8]))
    return "\n".join(lines) + "\n"


def _route_proposals_from_contract(contract: dict[str, Any]) -> list[TaskRouteProposal]:
    explicit = contract.get("route_proposals") or contract.get("task_route_proposals")
    if isinstance(explicit, list):
        proposals = [
            _route_proposal_with_contract_goal(parse_task_route_proposal(item), contract)
            for item in explicit
            if isinstance(item, dict)
        ]
        proposals = [item for item in proposals if item.capability_id or item.tool_id][:6]
        if proposals:
            return proposals
    single = contract.get("route_proposal") or contract.get("task_route_proposal")
    if isinstance(single, dict):
        proposal = _route_proposal_with_contract_goal(parse_task_route_proposal(single), contract)
        if proposal.capability_id or proposal.tool_id:
            return [proposal]

    capability_ids = _contract_capability_ids(contract)
    tool_ids = _contract_tool_ids(contract)
    expected_artifacts = _contract_expected_artifacts(contract)
    proposals: list[TaskRouteProposal] = []
    for index, capability_id in enumerate(capability_ids[:6]):
        proposals.append(TaskRouteProposal(
            goal=str(contract.get("goal") or "").strip(),
            capability_id=capability_id,
            tool_id=tool_ids[index] if index < len(tool_ids) else None,
            expected_artifacts=tuple(expected_artifacts),
            requires_write=bool(contract.get("requires_write")),
            requires_verification=bool(contract.get("requires_verification")),
            confidence=_contract_confidence(contract),
            rationale="derived from model task_contract capability_ids",
        ))
    return proposals


def _route_proposal_with_contract_goal(
    proposal: TaskRouteProposal,
    contract: dict[str, Any],
) -> TaskRouteProposal:
    if proposal.goal:
        return proposal
    return TaskRouteProposal(
        goal=str(contract.get("goal") or "").strip(),
        capability_id=proposal.capability_id,
        tool_id=proposal.tool_id,
        expected_artifacts=proposal.expected_artifacts,
        requires_write=proposal.requires_write,
        requires_verification=proposal.requires_verification,
        confidence=proposal.confidence,
        rationale=proposal.rationale,
    )


def _capability_contract_from_snapshot_item(item: dict[str, Any]) -> CapabilityContract:
    tool_ids = _string_tuple(item.get("tool_ids"))
    available_tool_ids = _string_tuple(item.get("available_tool_ids"))
    return CapabilityContract(
        id=str(item.get("id") or ""),
        name=str(item.get("name") or item.get("id") or ""),
        description=str(item.get("description") or ""),
        tool_ids=tool_ids or available_tool_ids,
        artifacts=tuple(sorted(set(_string_tuple(item.get("artifacts")) + _string_tuple(item.get("available_artifacts"))))),
        effects=tuple(sorted(set(_string_tuple(item.get("effects")) + _string_tuple(item.get("available_effects"))))),
        roles=tuple(sorted(set(_string_tuple(item.get("roles")) + _string_tuple(item.get("available_roles"))))),
        verification_strengths=tuple(sorted(set(
            _string_tuple(item.get("verification_strengths"))
            + _string_tuple(item.get("available_verification_strengths"))
        ))),
        requires_confirmation=bool(item.get("requires_confirmation")),
        long_running=bool(item.get("long_running")),
        retry_safe=bool(item.get("retry_safe")),
        idempotent=bool(item.get("idempotent")),
        source=str(item.get("source") or "snapshot"),
        provider_kinds=_string_tuple(item.get("provider_kinds")) or ("unknown",),
        provider_ids=_string_tuple(item.get("provider_ids")),
    )


def _contract_capability_ids(contract: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("capability_ids", "target_capability_ids"):
        result.extend(_string_list(contract.get(key)))
    single = str(contract.get("capability_id") or "").strip()
    if single:
        result.append(single)
    for item in contract.get("deliverables") or []:
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("capability_id") or "").strip()
        if capability_id:
            result.append(capability_id)
    return list(dict.fromkeys(result))


def _contract_tool_ids(contract: dict[str, Any]) -> list[str]:
    result = _string_list(contract.get("tool_ids"))
    single = str(contract.get("tool_id") or "").strip()
    if single:
        result.append(single)
    for item in contract.get("deliverables") or []:
        if not isinstance(item, dict):
            continue
        tool_id = str(item.get("tool_id") or "").strip()
        if tool_id:
            result.append(tool_id)
    return list(dict.fromkeys(result))


def _contract_expected_artifacts(contract: dict[str, Any]) -> list[str]:
    result: list[str] = []
    result.extend(_string_list(contract.get("expected_artifacts")))
    for item in contract.get("deliverables") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind:
            result.append(kind)
    return list(dict.fromkeys(result))


def _validation_advisory_codes(validations: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in validations:
        for error in item.get("errors") or []:
            text = str(error or "").strip()
            if text:
                result.append(text)
    return list(dict.fromkeys(result))


def _route_model_facts(
    proposals: list[TaskRouteProposal],
    validations: list[dict[str, Any]],
    preflight: dict[str, Any],
) -> list[str]:
    facts: list[str] = []
    if proposals:
        facts.append(
            "route_proposals="
            + "; ".join(
                f"{item.capability_id or 'unknown'}"
                + (f"/{item.tool_id}" if item.tool_id else "")
                for item in proposals[:6]
            )
        )
    facts.append(
        "route_validation="
        f"valid:{sum(1 for item in validations if item.get('ok'))}; "
        f"invalid:{sum(1 for item in validations if not item.get('ok'))}"
    )
    target_ids = _string_list(preflight.get("target_capability_ids"))
    if target_ids:
        facts.append("preflight_targets=" + ",".join(target_ids[:8]))
    advisories = [
        str(item.get("code") or "").strip()
        for item in preflight.get("advisories") or []
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    if advisories:
        facts.append("preflight_advisories=" + ",".join(advisories[:8]))
    return facts


def _contract_confidence(contract: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(contract.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(_string_list(value))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result
