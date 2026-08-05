"""可打开 Run 产物的路径解析。

本模块有意保持狭窄：只将 Run 证据中已记录的路径解析为 UI 可打开的本地路径。
它不执行任务工具、不推断意图，也不判断 Run 是否成功。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from runtime.run_evidence import build_run_evidence


RUN_ARTIFACT_IMAGE_PREVIEW_MAX_BYTES = 10 * 1024 * 1024

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

_PATH_KEYS = (
    "path",
    "model_context_path",
    "source_path",
    "artifact_path",
    "output_path",
    "file_path",
    "screenshot_path",
    "image_path",
    "render_path",
)


def collect_run_artifact_paths(evidence: dict[str, Any]) -> list[str]:
    """收集 Run 证据中明确存在的路径。"""

    paths: list[str] = []
    for section in (
        evidence.get("artifacts"),
        evidence.get("verification_evidence"),
        evidence.get("visual_context"),
        evidence.get("tool_steps"),
        evidence.get("failures"),
        evidence.get("failure_details"),
        _dict(evidence.get("visual_verification")).get("records"),
        _dict(evidence.get("visual_verification")).get("model_context_records"),
        _dict(evidence.get("visual_verification")).get("debug_sessions"),
        _dict(evidence.get("result")).get("artifacts"),
        _dict(evidence.get("result")).get("run_artifacts"),
        _dict(evidence.get("result")).get("verification_evidence"),
        _dict(evidence.get("result")).get("visual_evidence"),
        _dict(evidence.get("result")).get("failure_details"),
    ):
        _collect_paths_from_value(section, paths)

    closure_paths = _dict(_dict(evidence.get("verification_closure")).get("artifact_paths"))
    for value in closure_paths.values():
        _collect_paths_from_value(value, paths)

    return _unique_paths(paths)


def resolve_run_artifact_path(
    run: Any,
    raw_path: str,
    *,
    path_guard: Any,
    data_dir: str | Path | None,
) -> Path:
    """当 UI 请求的路径属于 Run 证据边界时解析该路径。"""

    return resolve_run_artifact_path_from_evidence(
        build_run_evidence(run),
        raw_path,
        path_guard=path_guard,
        data_dir=data_dir,
    )


def resolve_run_artifact_path_from_evidence(
    evidence: dict[str, Any],
    raw_path: str,
    *,
    path_guard: Any,
    data_dir: str | Path | None,
) -> Path:
    requested = _normalize_path_text(raw_path)
    if not requested:
        raise ValueError("path is required")

    recorded = set(collect_run_artifact_paths(evidence))
    if requested not in recorded:
        raise PermissionError("path is not recorded in this run evidence")

    workspace_roots = tuple(getattr(path_guard, "workspace_roots", ()) or ())
    allowed_roots = [Path(root).expanduser().resolve() for root in workspace_roots]
    if data_dir:
        allowed_roots.append(Path(data_dir).expanduser().resolve())

    resolved = _resolve_recorded_path(requested, workspace_roots=workspace_roots, data_dir=data_dir)
    if not _is_under_any(resolved, allowed_roots):
        raise PermissionError("path is outside run artifact access boundaries")
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return resolved


def run_artifact_image_preview_media_type(path: Path) -> str:
    """返回已解析产物路径所支持的内联图片媒体类型。"""

    return _IMAGE_MEDIA_TYPES.get(path.suffix.lower(), "")


def _collect_paths_from_value(value: Any, paths: list[str]) -> None:
    if isinstance(value, dict):
        for key in _PATH_KEYS:
            path = _normalize_path_text(value.get(key))
            if path:
                paths.append(path)
        metadata = value.get("metadata")
        if isinstance(metadata, dict):
            _collect_paths_from_value(metadata, paths)
        artifact = value.get("artifact")
        if isinstance(artifact, dict):
            _collect_paths_from_value(artifact, paths)
        source = value.get("source")
        if isinstance(source, dict):
            _collect_paths_from_value(source, paths)
        return
    if isinstance(value, list):
        for item in value:
            _collect_paths_from_value(item, paths)
        return
    path = _normalize_path_text(value)
    if path:
        paths.append(path)


def _resolve_recorded_path(
    value: str,
    *,
    workspace_roots: Iterable[Path],
    data_dir: str | Path | None,
) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()

    candidates = [Path(root).expanduser().resolve() / value for root in workspace_roots]
    if data_dir:
        candidates.append(Path(data_dir).expanduser().resolve() / value)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve() if candidates else raw.resolve()


def _normalize_path_text(value: Any) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    if not text or "\x00" in text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "data:", "blob:")):
        return ""
    return text.replace("\\", "/")


def _unique_paths(paths: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = _normalize_path_text(path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _is_under_any(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
