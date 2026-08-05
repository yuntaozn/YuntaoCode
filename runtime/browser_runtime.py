"""浏览器类能力的 Runtime 就绪事实。

能导入 Playwright Python 包并不代表其托管的浏览器二进制文件已经安装。
本模块只报告这一差异，不启动浏览器，也不把就绪状态变成任务路由策略。"""

from __future__ import annotations

import os
import platform
import time
from pathlib import Path
from typing import Any


_CACHE_TTL_SECONDS = 10.0
_cached_at = 0.0
_cached_result: dict[str, Any] | None = None
_CHROMIUM_EXECUTABLE_NAMES = {
    "chrome",
    "chrome.exe",
    "chrome-headless-shell",
    "chrome-headless-shell.exe",
    "chromium",
    "headless_shell",
    "headless_shell.exe",
}


def playwright_chromium_readiness() -> dict[str, Any]:
    """返回 Playwright 管理的 Chromium 二进制文件是否存在。"""

    global _cached_at, _cached_result
    now = time.monotonic()
    if _cached_result is not None and now - _cached_at < _CACHE_TTL_SECONDS:
        return _copy_result(_cached_result)

    try:
        import playwright
    except Exception as exc:
        result = {
            "available": False,
            "health": "unavailable",
            "code": "playwright_package_missing",
            "message": f"Playwright Python package is unavailable: {exc}",
            "details": {"dependency": "playwright", "browser": "chromium"},
        }
    else:
        roots = _playwright_browser_roots(Path(playwright.__file__).resolve().parent)
        executable = _find_chromium_executable(roots)
        if executable is not None:
            result = {
                "available": True,
                "health": "available",
                "code": "playwright_chromium_ready",
                "message": "",
                "details": {
                    "dependency": "playwright",
                    "browser": "chromium",
                    "executable": str(executable),
                },
            }
        else:
            result = {
                "available": False,
                "health": "unavailable",
                "code": "playwright_browser_missing",
                "message": (
                    "Playwright is installed, but its Chromium browser is missing. "
                    "Install it with: python -m playwright install chromium"
                ),
                "details": {
                    "dependency": "playwright",
                    "browser": "chromium",
                    "searched_roots": [str(root) for root in roots],
                },
            }

    _cached_at = now
    _cached_result = result
    return _copy_result(result)


def playwright_optional_html_readiness() -> dict[str, Any]:
    """报告非 HTML 路径仍可工作的工具降级就绪状态。"""

    result = playwright_chromium_readiness()
    if result.get("available"):
        return result
    return {
        **result,
        "available": True,
        "health": "degraded",
        "code": "playwright_html_route_unavailable",
        "message": (
            f"{result.get('message', '')} Browser-backed HTML preview is unavailable, "
            "but image or PDF file preview routes may still work."
        ).strip(),
    }


def clear_browser_readiness_cache() -> None:
    """在安装依赖后或测试中清除短期缓存。"""

    global _cached_at, _cached_result
    _cached_at = 0.0
    _cached_result = None


def _playwright_browser_roots(package_root: Path) -> tuple[Path, ...]:
    configured = str(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    roots: list[Path] = []
    if configured == "0":
        roots.extend([
            package_root / "driver" / "package" / ".local-browsers",
            package_root / ".local-browsers",
        ])
    elif configured:
        roots.append(Path(configured).expanduser())
    else:
        system = platform.system().lower()
        if system == "windows":
            local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
            if local_app_data:
                roots.append(Path(local_app_data) / "ms-playwright")
        elif system == "darwin":
            roots.append(Path.home() / "Library" / "Caches" / "ms-playwright")
        else:
            cache_home = str(os.environ.get("XDG_CACHE_HOME") or "").strip()
            roots.append(
                (Path(cache_home).expanduser() if cache_home else Path.home() / ".cache")
                / "ms-playwright"
            )
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def _find_chromium_executable(roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        if not root.is_dir():
            continue
        browser_dirs = [
            *root.glob("chromium-*"),
            *root.glob("chromium_headless_shell-*"),
        ]
        for browser_dir in browser_dirs:
            if not browser_dir.is_dir():
                continue
            for candidate in browser_dir.rglob("*"):
                if (
                    candidate.is_file()
                    and candidate.name.lower() in _CHROMIUM_EXECUTABLE_NAMES
                ):
                    return candidate
    return None


def _copy_result(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    if isinstance(value.get("details"), dict):
        result["details"] = dict(value["details"])
    return result
