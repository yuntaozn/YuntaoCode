from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def draft_store_root(data_dir: Path | str) -> Path:
    root = Path(data_dir).expanduser().resolve() / "document-drafts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def draft_path(data_dir: Path | str, draft_id: str) -> Path:
    safe_id = normalize_draft_id(draft_id)
    return draft_store_root(data_dir) / f"{safe_id}.json"


def normalize_draft_id(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", text):
        raise ValueError("draft_id must be 8-80 characters using letters, numbers, '_' or '-'")
    return text


def normalize_section_id(value: Any, title: str, existing: set[str]) -> str:
    raw = str(value or "").strip()
    if raw:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-_")[:60]
    else:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", title.strip().lower()).strip("-_")[:60]
    if not base:
        base = "section"
    candidate = base
    index = 2
    while candidate in existing:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def create_draft_record(
    title: str,
    sections: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    record: dict[str, Any] = {
        "draft_id": f"draft_{uuid.uuid4().hex[:16]}",
        "title": str(title or "Untitled Draft").strip() or "Untitled Draft",
        "created_at": now,
        "updated_at": now,
        "metadata": dict(metadata or {}),
        "sections": [],
        "citations": [],
    }
    existing: set[str] = set()
    for item in sections or []:
        if not isinstance(item, dict):
            item = {"title": str(item)}
        section = normalize_section(item, existing)
        existing.add(section["section_id"])
        record["sections"].append(section)
    return record


def normalize_section(item: dict[str, Any], existing: set[str]) -> dict[str, Any]:
    title = str(item.get("title") or item.get("text") or "Untitled Section").strip() or "Untitled Section"
    level = safe_int(item.get("level"), 1)
    level = max(1, min(level, 6))
    section_id = normalize_section_id(item.get("section_id") or item.get("id"), title, existing)
    return {
        "section_id": section_id,
        "title": title,
        "level": level,
        "blocks": [],
        "metadata": dict(item.get("metadata") or {}),
    }


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def save_draft(data_dir: Path | str, record: dict[str, Any]) -> dict[str, Any]:
    record = deepcopy(record)
    record["updated_at"] = utc_now()
    path = draft_path(data_dir, record["draft_id"])
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def load_draft(data_dir: Path | str, draft_id: str) -> dict[str, Any]:
    path = draft_path(data_dir, draft_id)
    if not path.exists():
        raise FileNotFoundError(f"document draft not found: {draft_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid document draft: {draft_id}")
    data.setdefault("sections", [])
    data.setdefault("citations", [])
    data.setdefault("metadata", {})
    return data


def add_section_block(
    record: dict[str, Any],
    *,
    content: str,
    section_id: str | None = None,
    title: str | None = None,
    level: int = 1,
    citation_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise ValueError("content is required")
    sections = record.setdefault("sections", [])
    section = find_section(record, section_id)
    if section is None:
        existing = {str(item.get("section_id") or "") for item in sections}
        section = normalize_section(
            {
                "section_id": section_id,
                "title": title or "Untitled Section",
                "level": level,
            },
            existing,
        )
        sections.append(section)
    block = {
        "block_id": f"block_{uuid.uuid4().hex[:12]}",
        "created_at": utc_now(),
        "text": text,
        "citation_ids": [str(item).strip() for item in citation_ids or [] if str(item).strip()],
        "metadata": dict(metadata or {}),
    }
    section.setdefault("blocks", []).append(block)
    return block


def find_section(record: dict[str, Any], section_id: str | None) -> dict[str, Any] | None:
    if not section_id:
        return None
    for section in record.get("sections") or []:
        if str(section.get("section_id") or "") == section_id:
            return section
    return None


def add_citation(record: dict[str, Any], citation: dict[str, Any]) -> dict[str, Any]:
    citations = record.setdefault("citations", [])
    existing = {str(item.get("citation_id") or "") for item in citations}
    raw_id = str(citation.get("citation_id") or citation.get("id") or "").strip()
    citation_id = raw_id if raw_id else f"cite_{len(citations) + 1}"
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", citation_id).strip("-_") or f"cite_{len(citations) + 1}"
    candidate = base
    index = 2
    while candidate in existing:
        candidate = f"{base}-{index}"
        index += 1
    item = {
        "citation_id": candidate,
        "title": str(citation.get("title") or citation.get("label") or candidate).strip() or candidate,
        "source_type": str(citation.get("source_type") or "source").strip() or "source",
        "url": str(citation.get("url") or "").strip(),
        "doi": str(citation.get("doi") or "").strip(),
        "author": str(citation.get("author") or "").strip(),
        "year": str(citation.get("year") or "").strip(),
        "note": str(citation.get("note") or "").strip(),
    }
    citations.append(item)
    return item


def draft_stats(record: dict[str, Any]) -> dict[str, Any]:
    sections = record.get("sections") or []
    citations = record.get("citations") or []
    blocks = [block for section in sections for block in section.get("blocks") or []]
    text = "\n".join(str(block.get("text") or "") for block in blocks)
    known_citations = {str(item.get("citation_id") or "") for item in citations}
    referenced = {
        str(citation_id)
        for block in blocks
        for citation_id in block.get("citation_ids") or []
        if str(citation_id).strip()
    }
    return {
        "draft_id": record.get("draft_id"),
        "title": record.get("title"),
        "section_count": len(sections),
        "block_count": len(blocks),
        "citation_count": len(citations),
        "text_chars": len(text),
        "approx_words": len(re.findall(r"\w+", text)),
        "empty_section_count": sum(1 for section in sections if not section.get("blocks")),
        "unknown_citation_ids": sorted(referenced - known_citations),
    }


def inspect_draft_record(record: dict[str, Any]) -> dict[str, Any]:
    sections = []
    for section in record.get("sections") or []:
        blocks = section.get("blocks") or []
        sections.append(
            {
                "section_id": section.get("section_id"),
                "title": section.get("title"),
                "level": section.get("level"),
                "block_count": len(blocks),
                "text_chars": sum(len(str(block.get("text") or "")) for block in blocks),
            }
        )
    return {
        "draft_id": record.get("draft_id"),
        "title": record.get("title"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "metadata": record.get("metadata") or {},
        "stats": draft_stats(record),
        "sections": sections,
        "citations": record.get("citations") or [],
    }


def draft_to_markdown(record: dict[str, Any], *, include_citations: bool = True) -> str:
    lines: list[str] = [f"# {record.get('title') or 'Untitled Draft'}", ""]
    for section in record.get("sections") or []:
        level = max(1, min(int(section.get("level") or 1), 6))
        lines.append(f"{'#' * min(level + 1, 6)} {section.get('title') or 'Untitled Section'}")
        lines.append("")
        for block in section.get("blocks") or []:
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            citation_ids = [str(item) for item in block.get("citation_ids") or [] if str(item).strip()]
            suffix = f" [{' '.join(citation_ids)}]" if citation_ids else ""
            lines.append(f"{text}{suffix}")
            lines.append("")
    if include_citations and record.get("citations"):
        lines.append("## References")
        lines.append("")
        for citation in record.get("citations") or []:
            parts = [
                str(citation.get("author") or "").strip(),
                str(citation.get("year") or "").strip(),
                str(citation.get("title") or citation.get("citation_id") or "").strip(),
                str(citation.get("doi") or citation.get("url") or "").strip(),
                str(citation.get("note") or "").strip(),
            ]
            text = ". ".join(part for part in parts if part)
            lines.append(f"- [{citation.get('citation_id')}] {text}")
    return "\n".join(lines).strip() + "\n"
