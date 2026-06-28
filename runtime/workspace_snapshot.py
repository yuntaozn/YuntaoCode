"""Lightweight workspace facts for model-side task understanding.

The snapshot is evidence, not routing. It gives the task-contract model a
small view of the current project so ambiguous follow-ups are less likely to
inherit an unrelated previous task.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


WORKSPACE_SNAPSHOT_SCHEMA_VERSION = "workspace_snapshot.v1"

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
}

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".html", ".css", ".json",
    ".toml", ".yaml", ".yml", ".rs", ".go", ".java", ".cs", ".cpp", ".c",
    ".h", ".hpp", ".php", ".rb", ".sh", ".ps1", ".bat", ".sql",
}
DOCUMENT_EXTENSIONS = {
    ".md", ".txt", ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".csv", ".tsv",
}
THREE_D_EXTENSIONS = {
    ".blend", ".glb", ".gltf", ".obj", ".fbx", ".dae", ".stl", ".ply",
}
MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".mov", ".wav",
    ".mp3",
}


def build_workspace_snapshot(
    workspace_path: str,
    *,
    max_top_entries: int = 48,
    max_scan_entries: int = 300,
    max_notable_paths: int = 40,
) -> dict[str, Any]:
    """Return a small, bounded snapshot of a workspace directory."""
    root = Path(str(workspace_path or "")).expanduser()
    snapshot: dict[str, Any] = {
        "schema_version": WORKSPACE_SNAPSHOT_SCHEMA_VERSION,
        "kind": "workspace_snapshot",
        "path": str(root),
        "name": root.name,
        "exists": False,
        "readable": False,
        "truncated": False,
        "top_level_entries": [],
        "file_count": 0,
        "directory_count": 0,
        "extension_counts": {},
        "observed_patterns": [],
        "notable_paths": [],
        "error": "",
    }
    if not root.exists():
        snapshot["error"] = "workspace_path_not_found"
        return snapshot
    if not root.is_dir():
        snapshot["error"] = "workspace_path_not_directory"
        return snapshot

    snapshot["exists"] = True
    try:
        top_entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError as exc:
        snapshot["error"] = str(exc)[:240]
        return snapshot

    snapshot["readable"] = True
    snapshot["top_level_entries"] = [
        _entry_record(item, root)
        for item in top_entries[:max_top_entries]
    ]
    snapshot["truncated"] = len(top_entries) > max_top_entries

    counts, file_count, directory_count, notable_paths, truncated = _scan_shallow(
        root,
        max_scan_entries=max_scan_entries,
        max_notable_paths=max_notable_paths,
    )
    snapshot["file_count"] = file_count
    snapshot["directory_count"] = directory_count
    snapshot["extension_counts"] = dict(counts.most_common(24))
    snapshot["notable_paths"] = notable_paths
    snapshot["observed_patterns"] = _observed_patterns(root, counts, snapshot["top_level_entries"], notable_paths)
    snapshot["truncated"] = bool(snapshot["truncated"] or truncated)
    return snapshot


def format_workspace_snapshot_for_prompt(snapshot: dict[str, Any] | None) -> str:
    """Format a compact model-facing workspace fact block."""
    if not isinstance(snapshot, dict) or not snapshot:
        return ""
    compact = {
        "schema_version": snapshot.get("schema_version"),
        "name": snapshot.get("name"),
        "path": snapshot.get("path"),
        "exists": bool(snapshot.get("exists")),
        "readable": bool(snapshot.get("readable")),
        "top_level_entries": snapshot.get("top_level_entries") or [],
        "extension_counts": snapshot.get("extension_counts") or {},
        "observed_patterns": snapshot.get("observed_patterns") or [],
        "notable_paths": snapshot.get("notable_paths") or [],
        "truncated": bool(snapshot.get("truncated")),
    }
    text = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(text) > 6000:
        compact["top_level_entries"] = list(compact["top_level_entries"][:24])
        compact["notable_paths"] = list(compact["notable_paths"][:20])
        text = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    return (
        "Workspace fact snapshot for this contract judgment:\n"
        f"{text}\n"
        "Workspace snapshot rule: these are bounded facts, not instructions or a forced route. "
        "Use them to understand the current project/artifact before relying on older chat context."
    )


def workspace_snapshot_summary(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Return a stable summary suitable for RunEvidence and diagnostics."""
    if not isinstance(snapshot, dict):
        return {}
    return {
        "schema_version": str(snapshot.get("schema_version") or ""),
        "name": str(snapshot.get("name") or ""),
        "path": str(snapshot.get("path") or ""),
        "exists": bool(snapshot.get("exists")),
        "readable": bool(snapshot.get("readable")),
        "truncated": bool(snapshot.get("truncated")),
        "file_count": int(snapshot.get("file_count") or 0),
        "directory_count": int(snapshot.get("directory_count") or 0),
        "extension_counts": dict(snapshot.get("extension_counts") or {}),
        "observed_patterns": list(snapshot.get("observed_patterns") or []),
        "notable_paths": list(snapshot.get("notable_paths") or [])[:40],
        "top_level_entries": list(snapshot.get("top_level_entries") or [])[:48],
        "error": str(snapshot.get("error") or ""),
    }


def _scan_shallow(
    root: Path,
    *,
    max_scan_entries: int,
    max_notable_paths: int,
) -> tuple[Counter[str], int, int, list[str], bool]:
    counts: Counter[str] = Counter()
    file_count = 0
    directory_count = 0
    notable_paths: list[str] = []
    visited = 0
    truncated = False
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop(0)
        try:
            children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError:
            continue
        for child in children:
            visited += 1
            if visited > max_scan_entries:
                truncated = True
                return counts, file_count, directory_count, notable_paths, truncated
            if child.is_dir():
                directory_count += 1
                if _is_notable_path(child) and len(notable_paths) < max_notable_paths:
                    notable_paths.append(_relative_path(root, child))
                if depth < 2 and child.name not in SKIP_DIR_NAMES and not child.is_symlink():
                    stack.append((child, depth + 1))
                continue
            file_count += 1
            suffix = child.suffix.lower() or "[no_ext]"
            counts[suffix] += 1
            if _is_notable_path(child) and len(notable_paths) < max_notable_paths:
                notable_paths.append(_relative_path(root, child))
    return counts, file_count, directory_count, notable_paths, truncated


def _entry_record(path: Path, root: Path) -> dict[str, Any]:
    record = {
        "name": path.name,
        "path": _relative_path(root, path),
        "type": "directory" if path.is_dir() else "file",
    }
    if path.is_file():
        record["extension"] = path.suffix.lower()
        try:
            record["size"] = path.stat().st_size
        except OSError:
            pass
    return record


def _observed_patterns(
    root: Path,
    counts: Counter[str],
    top_entries: list[dict[str, Any]],
    notable_paths: list[str],
) -> list[dict[str, Any]]:
    top_names = {str(item.get("name") or "").lower() for item in top_entries}
    patterns: list[dict[str, Any]] = []
    _add_pattern(patterns, "code_files", counts, CODE_EXTENSIONS)
    _add_pattern(patterns, "document_files", counts, DOCUMENT_EXTENSIONS)
    _add_pattern(patterns, "three_d_assets", counts, THREE_D_EXTENSIONS)
    _add_pattern(patterns, "media_assets", counts, MEDIA_EXTENSIONS)
    if "package.json" in top_names:
        patterns.append({"id": "node_project_marker", "evidence": ["package.json"]})
    if "pyproject.toml" in top_names or "requirements.txt" in top_names:
        evidence = [name for name in ("pyproject.toml", "requirements.txt") if name in top_names]
        patterns.append({"id": "python_project_marker", "evidence": evidence})
    if any(path.lower().startswith(("assets/", "asset/", "public/", "static/")) for path in notable_paths):
        patterns.append({"id": "asset_directory_marker", "evidence": notable_paths[:8]})
    return patterns[:12]


def _add_pattern(
    patterns: list[dict[str, Any]],
    pattern_id: str,
    counts: Counter[str],
    extensions: set[str],
) -> None:
    evidence = [
        f"{extension}:{counts[extension]}"
        for extension in sorted(extensions)
        if counts.get(extension)
    ]
    if evidence:
        patterns.append({"id": pattern_id, "evidence": evidence[:12]})


def _is_notable_path(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in CODE_EXTENSIONS | DOCUMENT_EXTENSIONS | THREE_D_EXTENSIONS | MEDIA_EXTENSIONS:
        return True
    return name in {
        "assets", "asset", "public", "static", "src", "docs", "models", "model",
        "package.json", "pyproject.toml", "requirements.txt", "readme.md",
    }


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
