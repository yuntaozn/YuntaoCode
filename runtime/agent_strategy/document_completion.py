"""Evidence helpers for long-form text/document completion.

The runtime should not judge prose quality, but it can verify hard facts:
whether a text/document artifact exists and whether tool-reported character
counts satisfy a task contract's declared output-length target.
"""

from __future__ import annotations

from typing import Any

from .classifiers import canonical_tool_id
from .tool_event_roles import successful_deliverable_events


TEXT_OUTPUT_TOOL_IDS: frozenset[str] = frozenset({
    "document.export_docx",
    "document.export_draft_docx",
    "document.export_markdown",
    "filesystem.finalize_text_file",
    "filesystem.write_file",
})

DOCUMENT_INTENTS: frozenset[str] = frozenset({
    "document_export",
    "paper_workflow",
})

DOCUMENT_DELIVERABLE_KINDS: frozenset[str] = frozenset({
    "document",
    "markdown",
    "docx",
})

TEXT_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".docx",
    ".md",
    ".markdown",
    ".odt",
    ".pdf",
    ".rtf",
    ".txt",
})


def contract_expects_text_output(task_contract: dict[str, Any] | None) -> bool:
    """Return True when a task contract expects a prose/document artifact."""
    if not isinstance(task_contract, dict):
        return False
    if str(task_contract.get("intent") or "").strip() in DOCUMENT_INTENTS:
        return True
    if task_contract.get("expected_document_coverage"):
        return True

    deliverables = [
        item for item in task_contract.get("deliverables") or []
        if isinstance(item, dict)
    ]
    kinds = {
        str(item.get("kind") or "").strip().lower()
        for item in deliverables
        if str(item.get("kind") or "").strip()
    }
    if kinds & DOCUMENT_DELIVERABLE_KINDS:
        return True
    if kinds & {"code", "external_state"}:
        return False

    if _safe_int(task_contract.get("expected_min_output_chars")) <= 0:
        return False
    for item in deliverables:
        if str(item.get("kind") or "").strip().lower() != "file":
            continue
        path_hint = str(
            item.get("path_hint")
            or item.get("path")
            or item.get("output_path")
            or ""
        ).strip()
        suffix = _path_suffix(path_hint)
        if not suffix or suffix in TEXT_FILE_EXTENSIONS:
            return True
    return bool(not kinds and deliverables)


def text_output_candidate_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """Return successful deliverable events that can carry text length facts."""
    if isinstance(task_contract, dict):
        candidates = successful_deliverable_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
    else:
        candidates = tool_events
    return [
        event for event in candidates
        if str(event.get("status") or "") in {"success", "partial"}
        and canonical_tool_id(str(event.get("tool") or "")) in TEXT_OUTPUT_TOOL_IDS
    ]


def text_output_char_count(event: dict[str, Any]) -> int:
    """Extract character-count evidence without treating byte size as chars."""
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    draft_stats = output.get("draft_stats") if isinstance(output.get("draft_stats"), dict) else {}
    validation = output.get("validation") if isinstance(output.get("validation"), dict) else {}
    stats = output.get("stats") if isinstance(output.get("stats"), dict) else {}
    content = event_input.get("content")
    return max(
        _safe_int(output.get("content_chars")),
        _safe_int(output.get("text_chars")),
        _safe_int(draft_stats.get("text_chars")),
        _safe_int(validation.get("text_chars")),
        _safe_int(stats.get("text_chars")),
        len(content) if isinstance(content, str) else 0,
    )


def min_text_output_check(
    tool_events: list[dict[str, Any]],
    *,
    expected_min_output_chars: int,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic length-check result for long text outputs."""
    expected = _safe_int(expected_min_output_chars)
    if expected <= 0 or (
        isinstance(task_contract, dict)
        and not contract_expects_text_output(task_contract)
    ):
        return {
            "required": False,
            "ok": True,
            "expected": expected,
            "observed": 0,
            "reason": "",
            "event": None,
        }

    candidates = text_output_candidate_events(
        tool_events,
        task_contract=task_contract,
        workspace_path=workspace_path,
        mode=mode,
    )
    best_event: dict[str, Any] | None = None
    best_chars = 0
    for event in candidates:
        chars = text_output_char_count(event)
        if best_event is None or chars > best_chars:
            best_event = event
            best_chars = chars

    if best_event is None:
        return {
            "required": True,
            "ok": False,
            "expected": expected,
            "observed": 0,
            "reason": "document_output_length_unknown",
            "event": None,
        }
    if best_chars <= 0:
        return {
            "required": True,
            "ok": False,
            "expected": expected,
            "observed": 0,
            "reason": "document_output_length_unknown",
            "event": best_event,
        }
    if best_chars < expected:
        return {
            "required": True,
            "ok": False,
            "expected": expected,
            "observed": best_chars,
            "reason": "document_output_too_short",
            "event": best_event,
        }
    return {
        "required": True,
        "ok": True,
        "expected": expected,
        "observed": best_chars,
        "reason": "",
        "event": best_event,
    }


def _path_suffix(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/").lower()
    name = text.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
