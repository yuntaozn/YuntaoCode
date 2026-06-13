from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.version import __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = (
    ("Gitee", "https://gitee.com/yuntaozn/YuntaoCode.git"),
    ("GitHub", "https://github.com/yuntaozn/YuntaoCode.git"),
)
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


@dataclass(frozen=True)
class SourceUpdateSource:
    name: str
    url: str


def normalize_release_version(value: str) -> str:
    value = str(value or "").strip()
    if value.startswith("refs/tags/"):
        value = value.rsplit("/", 1)[-1]
    if value.lower().startswith("v"):
        value = value[1:]
    return value


def release_version_key(value: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.match(str(value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def compare_release_versions(current: str, latest: str) -> int:
    current_key = release_version_key(current)
    latest_key = release_version_key(latest)
    if current_key is None or latest_key is None:
        return 0
    if current_key < latest_key:
        return -1
    if current_key > latest_key:
        return 1
    return 0


def parse_ls_remote_tags(output: str) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    for line in str(output or "").splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        sha, ref = parts[0], parts[1]
        if not ref.startswith("refs/tags/"):
            continue
        tag = ref.rsplit("/", 1)[-1]
        version = normalize_release_version(tag)
        if release_version_key(version) is None:
            continue
        tags.append({"tag": tag, "version": version, "sha": sha})
    return tags


def choose_latest_tag(tags: list[dict[str, str]]) -> dict[str, str] | None:
    valid = [tag for tag in tags if release_version_key(tag.get("version", "")) is not None]
    if not valid:
        return None
    return max(valid, key=lambda tag: release_version_key(tag.get("version", "")) or (0, 0, 0))


def check_source_update(root: Path | None = None, timeout_seconds: int = 6) -> dict[str, Any]:
    project_root = (root or PROJECT_ROOT).resolve()
    checked_at = datetime.now(timezone.utc).isoformat()
    base: dict[str, Any] = {
        "schema_version": "source_update.v1",
        "current_version": __version__,
        "current_tag": f"v{__version__}",
        "project_root": str(project_root),
        "checked_at": checked_at,
    }

    repo_root, repo_error = _git_repo_root(project_root, timeout_seconds=timeout_seconds)
    if repo_root is None:
        return {
            **base,
            "is_git_repo": False,
            "update_available": False,
            "update_supported": False,
            "status": "not_git_repo",
            "message": repo_error or "current source directory is not a git repository",
            "sources": [],
            "update_commands": [],
        }

    branch = _git_output(["rev-parse", "--abbrev-ref", "HEAD"], repo_root, timeout_seconds=timeout_seconds)
    commit = _git_output(["rev-parse", "--short", "HEAD"], repo_root, timeout_seconds=timeout_seconds)
    dirty_output = _git_output(["status", "--porcelain"], repo_root, timeout_seconds=timeout_seconds)
    dirty = bool((dirty_output or "").strip())
    sources = discover_update_sources(repo_root, timeout_seconds=timeout_seconds)
    source_results = [_check_source(source, repo_root, timeout_seconds=timeout_seconds) for source in sources]
    latest = _choose_latest_source_tag(source_results)
    latest_version = latest.get("version") if latest else ""
    version_compare = compare_release_versions(__version__, latest_version)
    update_available = bool(latest and version_compare < 0)
    update_commands = _update_commands(update_available=update_available, dirty=dirty, branch=branch or "")
    status = "update_available" if update_available else "up_to_date"
    if not latest:
        status = "no_release_tags" if any(item.get("status") == "no_tags" for item in source_results) else "check_failed"

    return {
        **base,
        "is_git_repo": True,
        "repo_root": str(repo_root),
        "branch": branch or "",
        "commit": commit or "",
        "dirty": dirty,
        "sources": source_results,
        "latest_version": latest_version,
        "latest_tag": latest.get("tag") if latest else "",
        "latest_source": latest.get("source") if latest else "",
        "release_url": latest.get("release_url") if latest else "",
        "update_available": update_available,
        "update_supported": update_available and not dirty,
        "status": status,
        "version_compare": version_compare,
        "update_commands": update_commands,
    }


def discover_update_sources(root: Path, timeout_seconds: int = 6) -> list[SourceUpdateSource]:
    sources: list[SourceUpdateSource] = []
    remote_output = _git_output(["remote", "-v"], root, timeout_seconds=timeout_seconds) or ""
    for line in remote_output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "(fetch)":
            sources.append(SourceUpdateSource(name=parts[0], url=parts[1]))
    for name, url in DEFAULT_SOURCES:
        sources.append(SourceUpdateSource(name=name, url=url))
    return _dedupe_sources(sources)


def _check_source(source: SourceUpdateSource, root: Path, timeout_seconds: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": source.name,
        "url": source.url,
        "status": "failed",
    }
    try:
        output = _run_git(["ls-remote", "--tags", "--refs", source.url, "v*"], root, timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - surface git/network errors as update evidence.
        result["error"] = str(exc)[:500]
        return result
    tags = parse_ls_remote_tags(output)
    latest = choose_latest_tag(tags)
    if not latest:
        result["status"] = "no_tags"
        return result
    result.update({
        "status": "ok",
        "latest_tag": latest["tag"],
        "latest_version": latest["version"],
        "latest_sha": latest["sha"],
        "release_url": release_page_url(source.url, latest["tag"]),
    })
    return result


def _choose_latest_source_tag(results: list[dict[str, Any]]) -> dict[str, str] | None:
    candidates: list[dict[str, str]] = []
    for result in results:
        if result.get("status") != "ok":
            continue
        version = str(result.get("latest_version") or "")
        if release_version_key(version) is None:
            continue
        candidates.append({
            "source": str(result.get("name") or ""),
            "tag": str(result.get("latest_tag") or ""),
            "version": version,
            "release_url": str(result.get("release_url") or ""),
        })
    if not candidates:
        return None
    return max(candidates, key=lambda item: release_version_key(item["version"]) or (0, 0, 0))


def _dedupe_sources(sources: list[SourceUpdateSource]) -> list[SourceUpdateSource]:
    seen: set[str] = set()
    unique: list[SourceUpdateSource] = []
    for source in sorted(sources, key=_source_priority):
        key = source.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def _source_priority(source: SourceUpdateSource) -> tuple[int, str]:
    url = source.url.lower()
    if "gitee.com" in url:
        return (0, source.name)
    if "github.com" in url:
        return (1, source.name)
    return (2, source.name)


def _git_repo_root(root: Path, timeout_seconds: int) -> tuple[Path | None, str]:
    try:
        output = _run_git(["rev-parse", "--show-toplevel"], root, timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - non-git source trees should be reported, not raised.
        return None, str(exc)[:500]
    value = output.strip()
    return (Path(value).resolve(), "") if value else (None, "git repository root not found")


def _git_output(args: list[str], root: Path, timeout_seconds: int) -> str:
    try:
        return _run_git(args, root, timeout_seconds).strip()
    except Exception:
        return ""


def _run_git(args: list[str], root: Path, timeout_seconds: int) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git command timed out after {timeout_seconds}s") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "git command failed").strip()
        raise RuntimeError(message)
    return completed.stdout or ""


def _update_commands(*, update_available: bool, dirty: bool, branch: str) -> list[str]:
    if not update_available:
        return []
    if dirty:
        return ["git status --short", "git stash push -u", "git pull --ff-only", "git stash pop"]
    if branch and branch != "HEAD":
        return ["git pull --ff-only"]
    return ["git fetch --tags", "git checkout <latest-tag>"]


def release_page_url(repo_url: str, tag: str) -> str:
    base = repo_url.rstrip("/")
    if base.endswith(".git"):
        base = base[:-4]
    if "github.com" in base:
        return f"{base}/releases/tag/{tag}"
    if "gitee.com" in base:
        return f"{base}/releases/tag/{tag}"
    return base
