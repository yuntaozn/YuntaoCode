"""Check documentation files for UTF-8 encoding and common mojibake markers."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_PATHS = (
    "README.md",
    "README.en.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "AGENTS.md",
    "docs",
)

TEXT_SUFFIXES = {".md", ".txt"}

MOJIBAKE_MARKERS = (
    "\ufffd",  # replacement character
    "銆",
    "锛",
    "鏋",
    "绛",
    "鐨",
    "鏄",
    "瀹",
    "€?",
    "â€œ",
    "â€",
)


def iter_text_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
            continue
        if path.is_dir():
            files.extend(
                item for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in TEXT_SUFFIXES
            )
    return sorted(set(files))


def check_file(path: Path) -> list[str]:
    issues: list[str] = []
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        issues.append("has UTF-8 BOM; use UTF-8 without BOM")
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(f"is not valid UTF-8: {exc}")
        return issues
    for marker in MOJIBAKE_MARKERS:
        if marker in text:
            issues.append(f"contains possible mojibake marker {marker!r}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_PATHS),
        help="Files or directories to check. Defaults to public docs.",
    )
    args = parser.parse_args()

    root = Path.cwd()
    files = iter_text_files([root / item for item in args.paths])
    failures: list[tuple[Path, list[str]]] = []
    for path in files:
        issues = check_file(path)
        if issues:
            failures.append((path, issues))

    if failures:
        for path, issues in failures:
            rel = path.relative_to(root)
            for issue in issues:
                print(f"{rel}: {issue}")
        return 1
    print(f"documentation encoding ok ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
