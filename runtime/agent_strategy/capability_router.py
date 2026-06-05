from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CAPABILITY_ROUTER_SCHEMA_VERSION = "0.1"


@dataclass(frozen=True)
class CapabilityContract:
    id: str
    name: str
    description: str
    tool_ids: tuple[str, ...]
    artifacts: tuple[str, ...] = ()
    requires_confirmation: bool = False
    long_running: bool = False
    retry_safe: bool = False
    idempotent: bool = False
    source: str = "builtin"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_ROUTER_SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tool_ids": list(self.tool_ids),
            "artifacts": list(self.artifacts),
            "requires_confirmation": self.requires_confirmation,
            "long_running": self.long_running,
            "retry_safe": self.retry_safe,
            "idempotent": self.idempotent,
            "source": self.source,
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
    "filesystem": (
        "filesystem.local_files",
        "Local Files",
        "Read, scan, and write files inside the configured workspace boundary.",
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
    "memory": (
        "memory.local_memory",
        "Local Memory",
        "Store and recall local project/user memories.",
    ),
}


EXPLICIT_CAPABILITIES: dict[str, tuple[str, str, str]] = {
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
        requires_confirmation=bool(spec.get("requires_confirmation")),
        long_running=bool(spec.get("long_running")),
        retry_safe=bool(spec.get("retry_safe")),
        idempotent=bool(spec.get("idempotent")),
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
                "requires_confirmation": False,
                "long_running": False,
                "retry_safe": False,
                "idempotent": True,
                "source": item.source,
            },
        )
        bucket["tool_ids"].extend(item.tool_ids)
        bucket["artifacts"].update(item.artifacts)
        bucket["requires_confirmation"] = bool(bucket["requires_confirmation"] or item.requires_confirmation)
        bucket["long_running"] = bool(bucket["long_running"] or item.long_running)
        bucket["retry_safe"] = bool(bucket["retry_safe"] or item.retry_safe)
        bucket["idempotent"] = bool(bucket["idempotent"] and item.idempotent)

    return [
        CapabilityContract(
            id=capability_id,
            name=str(bucket["name"]),
            description=str(bucket["description"]),
            tool_ids=tuple(dict.fromkeys(bucket["tool_ids"])),
            artifacts=tuple(sorted(bucket["artifacts"])),
            requires_confirmation=bool(bucket["requires_confirmation"]),
            long_running=bool(bucket["long_running"]),
            retry_safe=bool(bucket["retry_safe"]),
            idempotent=bool(bucket["idempotent"]),
            source=str(bucket["source"]),
        )
        for capability_id, bucket in sorted(grouped.items())
    ]


def build_capability_catalog(tool_specs: list[dict[str, Any]]) -> list[CapabilityContract]:
    return merge_capability_contracts([capability_from_tool_spec(spec) for spec in tool_specs])


def format_capability_catalog_for_prompt(catalog: list[CapabilityContract], *, max_items: int = 16) -> str:
    visible = catalog[:max_items]
    lines = [
        "",
        "## Capability Router",
        "你负责理解用户任务，优先从已注册能力中选择合适工具；系统负责校验权限、参数、确认、产物和执行轨迹。",
        "不要发明不存在的工具；需要文件产物的任务必须调用能生成该产物的工具，不能只用自然语言宣布完成。",
        "如果缺少能力，先说明当前边界；只有用户明确要求扩展时，才创建隔离插件草稿。",
        "",
        "<available_capabilities>",
    ]
    for item in visible:
        flags: list[str] = []
        if item.artifacts:
            flags.append(f"artifacts={','.join(item.artifacts)}")
        if item.long_running:
            flags.append("long_running=true")
        if item.retry_safe:
            flags.append("retry_safe=true")
        if item.requires_confirmation:
            flags.append("confirm=true")
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
