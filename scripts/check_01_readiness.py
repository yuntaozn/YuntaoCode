"""Run the focused 0.1 readiness gate for YuntaoCode.

This script is a release hygiene aggregator, not a runtime feature.  It checks
the facts that should be true before treating the current tree as a 0.1
foundation candidate.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = (
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "AGENTS.md",
    "runtime/version.py",
    "runtime/app.py",
    "runtime/conversation_runner.py",
    "runtime/tool_call_loop.py",
    "runtime/tool_execution_batch.py",
    "runtime/run_execution_state.py",
    "runtime/run_finalizer.py",
    "runtime/run_result.py",
    "runtime/run_evidence.py",
    "runtime/run_workbench.py",
    "runtime/run_artifact_access.py",
    "runtime/artifacts.py",
    "runtime/verification_closure.py",
    "runtime/run_fact_summary.py",
    "runtime/context_pack.py",
    "runtime/model_harness.py",
    "runtime/model_calls.py",
    "runtime/user_guidance.py",
    "runtime/core/task.py",
    "runtime/core/capability.py",
    "docs/README.md",
    "docs/0.1-foundation-inventory.md",
    "docs/architecture.md",
    "docs/runtime-foundation.md",
    "docs/task-model.md",
    "docs/context-runtime.md",
    "docs/capability-runtime.md",
    "docs/experience-runtime.md",
    "docs/evaluation.md",
    "docs/automation-runtime.md",
    "docs/model-harness.md",
    "docs/run-artifacts.md",
    "docs/desktop-observation-provider.md",
    "docs/0.1-readiness.md",
)

CORE_COMPILE_PATHS = (
    "runtime/app.py",
    "runtime/api/conversations.py",
    "runtime/conversation_runner.py",
    "runtime/run_execution_state.py",
    "runtime/tool_call_loop.py",
    "runtime/tool_execution_batch.py",
    "runtime/run_finalizer.py",
    "runtime/run_result.py",
    "runtime/run_evidence.py",
    "runtime/run_workbench.py",
    "runtime/run_artifact_access.py",
    "runtime/artifacts.py",
    "runtime/verification_closure.py",
    "runtime/run_fact_summary.py",
    "runtime/context_pack.py",
    "runtime/model_harness.py",
    "runtime/model_calls.py",
    "runtime/model_providers/client.py",
    "runtime/user_guidance.py",
    "runtime/agent_strategy/conversation_task_context.py",
    "runtime/agent_strategy/prompts.py",
    "runtime/agent_strategy/tool_result_risks.py",
    "runtime/skills/desktop.py",
    "providers/desktop_observation/contracts.py",
    "providers/desktop_observation/service.py",
)

FRONTEND_CHECKS = (
    "runtime/panel/static/panel.js",
    "runtime/panel/static/i18n.js",
)

FOCUSED_TESTS = (
    "tests/test_user_guidance.py",
    "tests/test_model_harness.py",
    "tests/test_model_calls.py",
    "tests/test_run_events.py",
    "tests/test_desktop_observation_provider.py",
    "tests/test_run_execution_state.py",
    "tests/test_run_finalizer.py",
    "tests/test_tool_call_loop.py",
    "tests/test_tool_result_risks.py",
    "tests/test_artifacts.py",
    "tests/test_verification_closure.py",
    "tests/test_run_result.py",
    "tests/test_run_evidence.py",
    "tests/test_run_workbench.py",
    "tests/test_run_artifact_access.py",
    "tests/test_capability_preflight.py",
    "tests/test_context_pack.py",
)

LOCAL_GENERATED_PATHS = (
    ".venv-sidecar-build",
    "generated",
    "promo-video",
    "ai-plugins",
    "capability-packs",
    "desktop-shell/dist",
    "desktop-shell/src-tauri/binaries/local-runtime-x86_64-pc-windows-msvc.exe",
    "desktop-shell/src-tauri/target",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _run(
    name: str,
    args: list[str],
    *,
    timeout: int = 120,
    warn_only: bool = False,
) -> CheckResult:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        status = "WARN" if warn_only else "FAIL"
        return CheckResult(name, status, f"command not found: {exc.filename}")
    except subprocess.TimeoutExpired:
        status = "WARN" if warn_only else "FAIL"
        return CheckResult(name, status, f"timed out after {timeout}s")

    output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )
    if completed.returncode == 0:
        return CheckResult(name, "PASS", output or "ok")
    status = "WARN" if warn_only else "FAIL"
    return CheckResult(
        name,
        status,
        output or f"command exited with code {completed.returncode}",
    )


def check_required_paths() -> CheckResult:
    missing = [item for item in REQUIRED_PATHS if not (ROOT / item).exists()]
    if missing:
        return CheckResult("required paths", "FAIL", "missing: " + ", ".join(missing))
    return CheckResult("required paths", "PASS", f"{len(REQUIRED_PATHS)} paths present")


def check_release_version() -> CheckResult:
    return _run(
        "release version sync",
        [sys.executable, "scripts/sync_release_version.py", "--check"],
    )


def check_doc_encoding() -> CheckResult:
    return _run(
        "documentation encoding",
        [sys.executable, "scripts/check_doc_encoding.py"],
    )


def check_core_compile() -> CheckResult:
    existing = [item for item in CORE_COMPILE_PATHS if (ROOT / item).exists()]
    missing = sorted(set(CORE_COMPILE_PATHS) - set(existing))
    if missing:
        return CheckResult("core syntax", "FAIL", "missing: " + ", ".join(missing))
    failures: list[str] = []
    for item in existing:
        path = ROOT / item
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, item, "exec")
        except SyntaxError as exc:
            failures.append(f"{item}:{exc.lineno}: {exc.msg}")
        except UnicodeDecodeError as exc:
            failures.append(f"{item}: not valid UTF-8: {exc}")
    if failures:
        return CheckResult("core syntax", "FAIL", "\n".join(failures))
    return CheckResult("core syntax", "PASS", f"{len(existing)} files checked")


def check_frontend_syntax(*, strict: bool) -> CheckResult:
    node = shutil.which("node")
    if not node:
        return CheckResult(
            "frontend syntax",
            "FAIL" if strict else "WARN",
            "node is not available; skipped JS syntax checks",
        )
    results = [
        _run(f"node --check {item}", [node, "--check", item], warn_only=not strict)
        for item in FRONTEND_CHECKS
    ]
    failures = [item for item in results if item.status == "FAIL"]
    warnings = [item for item in results if item.status == "WARN"]
    if failures:
        return CheckResult(
            "frontend syntax",
            "FAIL",
            "\n".join(f"{item.name}: {item.detail}" for item in failures),
        )
    if warnings:
        return CheckResult(
            "frontend syntax",
            "WARN",
            "\n".join(f"{item.name}: {item.detail}" for item in warnings),
        )
    return CheckResult("frontend syntax", "PASS", f"{len(results)} files checked")


def check_focused_tests(*, skip: bool) -> CheckResult:
    if skip:
        return CheckResult("focused tests", "WARN", "skipped by --skip-tests")
    existing = [item for item in FOCUSED_TESTS if (ROOT / item).exists()]
    missing = sorted(set(FOCUSED_TESTS) - set(existing))
    if missing:
        return CheckResult("focused tests", "FAIL", "missing: " + ", ".join(missing))
    result = _run(
        "focused tests",
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *existing],
        timeout=240,
    )
    if result.status == "PASS":
        summary = ""
        for line in reversed(result.detail.splitlines()):
            text = line.strip("= ").strip()
            if " passed" in text or text.startswith("passed"):
                summary = text
                break
        detail = f"{len(existing)} files checked"
        if summary:
            detail = f"{detail}; {summary}"
        return CheckResult("focused tests", "PASS", detail)
    return result


def check_local_generated_paths() -> CheckResult:
    found = [_rel(ROOT / item) for item in LOCAL_GENERATED_PATHS if (ROOT / item).exists()]
    if found:
        return CheckResult(
            "local generated paths",
            "WARN",
            "review before release: " + ", ".join(found),
        )
    return CheckResult("local generated paths", "PASS", "no known local generated roots")


def _git_lines(args: list[str]) -> tuple[int, list[str]]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    lines = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode, lines


def check_inventory_coverage() -> CheckResult:
    if not shutil.which("git"):
        return CheckResult("inventory coverage", "WARN", "git is not available")
    inventory_path = ROOT / "docs/0.1-foundation-inventory.md"
    if not inventory_path.exists():
        return CheckResult("inventory coverage", "FAIL", "docs/0.1-foundation-inventory.md is missing")
    text = inventory_path.read_text(encoding="utf-8")
    include_section = text.split("## Keep Local-Only", 1)[0]
    declared = sorted(set(match.group(1).strip().replace("\\", "/") for match in re.finditer(r"`([^`]+)`", include_section)))
    if not declared:
        return CheckResult("inventory coverage", "FAIL", "no source paths declared in include section")

    diff_code, changed = _git_lines(["diff", "--name-only", "--"])
    staged_code, staged = _git_lines(["diff", "--cached", "--name-only", "--"])
    other_code, other = _git_lines(["ls-files", "--others", "--exclude-standard"])
    if diff_code != 0 or staged_code != 0 or other_code != 0:
        return CheckResult("inventory coverage", "WARN", "could not inspect git changed paths")
    missing: list[str] = []
    for path in sorted(set(changed + staged + other)):
        covered = False
        for entry in declared:
            if entry.endswith("/") and path.startswith(entry):
                covered = True
                break
            if entry == path:
                covered = True
                break
        if not covered:
            missing.append(path)
    if missing:
        return CheckResult(
            "inventory coverage",
            "FAIL",
            "changed path(s) missing from 0.1 inventory: " + ", ".join(missing[:12]),
        )
    count = len(set(changed + staged + other))
    return CheckResult("inventory coverage", "PASS", f"{count} changed path(s) covered")


def check_git_state(*, strict: bool) -> CheckResult:
    if not shutil.which("git"):
        return CheckResult("git state", "WARN", "git is not available")
    result = _run("git state", ["git", "status", "--short"], warn_only=True)
    if result.status == "PASS" and result.detail == "ok":
        return CheckResult("git state", "PASS", "clean")
    lines = [line for line in result.detail.splitlines() if line.strip()]
    if not lines:
        return CheckResult("git state", "PASS", "clean")
    return CheckResult(
        "git state",
        "FAIL" if strict else "WARN",
        f"{len(lines)} changed path(s); review before tagging",
    )


def print_report(results: list[CheckResult]) -> None:
    width = max(len(item.name) for item in results)
    for item in results:
        first_line, *_ = item.detail.splitlines() or [""]
        print(f"[{item.status}] {item.name:<{width}}  {first_line}")
        extra_lines = item.detail.splitlines()[1:6]
        for line in extra_lines:
            print(f"{'':8}{line}")
        if len(item.detail.splitlines()) > 6:
            print("        ...")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip the focused runtime test subset.",
    )
    parser.add_argument(
        "--strict-js",
        action="store_true",
        help="Treat missing node or JS syntax-check failures as release blockers.",
    )
    parser.add_argument(
        "--strict-git",
        action="store_true",
        help="Treat a dirty git worktree as a release blocker.",
    )
    args = parser.parse_args()

    results = [
        check_required_paths(),
        check_release_version(),
        check_doc_encoding(),
        check_core_compile(),
        check_frontend_syntax(strict=args.strict_js),
        check_focused_tests(skip=args.skip_tests),
        check_local_generated_paths(),
        check_inventory_coverage(),
        check_git_state(strict=args.strict_git),
    ]
    print_report(results)

    failures = [item for item in results if item.status == "FAIL"]
    if failures:
        print(f"\n0.1 readiness: FAILED ({len(failures)} blocker(s))")
        return 1
    warnings = [item for item in results if item.status == "WARN"]
    if warnings:
        print(f"\n0.1 readiness: PASSED WITH WARNINGS ({len(warnings)} warning(s))")
        return 0
    print("\n0.1 readiness: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
