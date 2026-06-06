"""Synchronize generated release-version references from runtime/version.py."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "runtime" / "version.py"
VERSION_PATTERN = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def release_version() -> str:
    text = VERSION_FILE.read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(text)
    if not match:
        raise ValueError(f"release version not found in {VERSION_FILE}")
    version = match.group(1)
    if not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(f"release version must use semantic versioning: {version}")
    return version


def _replace_once(text: str, pattern: str, replacement: str, *, path: Path) -> str:
    result, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"expected one release-version marker in {path}, found {count}")
    return result


def _json_with_version(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    return _replace_once(
        text,
        r'^(\s*"version"\s*:\s*)"[^"]+"',
        rf'\g<1>"{version}"',
        path=path,
    )


def _package_lock_with_version(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    result, count = re.subn(
        r'^(\s*"version"\s*:\s*)"[^"]+"',
        rf'\g<1>"{version}"',
        text,
        count=2,
        flags=re.MULTILINE,
    )
    if count != 2:
        raise ValueError(f"expected two project version markers in {path}, found {count}")
    return result


def _cargo_toml_with_version(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    return _replace_once(
        text,
        r'^(version\s*=\s*)"[^"]+"',
        rf'\g<1>"{version}"',
        path=path,
    )


def _cargo_lock_with_version(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = (
        r'(\[\[package\]\]\s*\nname\s*=\s*"local-intelligent-terminal"\s*\n'
        r'version\s*=\s*)"[^"]+"'
    )
    return _replace_once(text, pattern, rf'\g<1>"{version}"', path=path)


def _readme_with_version(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name == "README.en.md":
        pattern = r"^(Current Development Version:\s*\*\*)[^*]+(\*\*)$"
    else:
        pattern = r"^(当前开发版本：)[^\s]+$"
    replacement = rf"\g<1>{version}\g<2>" if path.name == "README.en.md" else rf"\g<1>{version}"
    return _replace_once(text, pattern, replacement, path=path)


def rendered_targets(version: str) -> dict[Path, str]:
    renderers: dict[Path, Callable[[Path, str], str]] = {
        ROOT / "desktop-shell" / "package.json": _json_with_version,
        ROOT / "desktop-shell" / "package-lock.json": _package_lock_with_version,
        ROOT / "desktop-shell" / "src-tauri" / "tauri.conf.json": _json_with_version,
        ROOT / "desktop-shell" / "src-tauri" / "Cargo.toml": _cargo_toml_with_version,
        ROOT / "desktop-shell" / "src-tauri" / "Cargo.lock": _cargo_lock_with_version,
        ROOT / "README.md": _readme_with_version,
        ROOT / "README.en.md": _readme_with_version,
    }
    return {path: renderer(path, version) for path, renderer in renderers.items()}


def sync_release_version(*, check: bool) -> list[Path]:
    version = release_version()
    changed: list[Path] = []
    for path, expected in rendered_targets(version).items():
        current = path.read_text(encoding="utf-8")
        if current == expected:
            continue
        changed.append(path)
        if not check:
            path.write_text(expected, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize product release-version references from runtime/version.py."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report out-of-sync files without modifying them.",
    )
    args = parser.parse_args()

    changed = sync_release_version(check=args.check)
    if args.check and changed:
        print("Release version references are out of sync:", file=sys.stderr)
        for path in changed:
            print(f"- {path.relative_to(ROOT)}", file=sys.stderr)
        print("Run: python scripts/sync_release_version.py", file=sys.stderr)
        return 1
    if changed:
        for path in changed:
            print(f"updated {path.relative_to(ROOT)}")
    else:
        print(f"release version references are synchronized: {release_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
