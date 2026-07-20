from __future__ import annotations

import csv
import io
import platform
import subprocess
from pathlib import Path
from typing import Any

from .contracts import build_desktop_state, build_visual_evidence, diagnostic, utc_now_iso


class DesktopObservationService:
    """Read-only local desktop observation.

    The service does not click, type, focus, move, resize, close windows, or
    terminate processes.  Platform-specific operations degrade to structured
    diagnostics when unavailable.
    """

    def __init__(self, *, platform_name: str | None = None) -> None:
        self.platform_name = platform_name or platform.system() or "unknown"

    def readiness(self) -> dict[str, Any]:
        supported = self._is_windows
        return {
            "available": True,
            "health": "available" if supported else "degraded",
            "code": "ready" if supported else "platform_partial_support",
            "message": "" if supported else "Window enumeration is currently implemented for Windows; process listing remains best-effort.",
            "details": {
                "platform": self.platform_name,
                "window_observation": "windows" if supported else "unsupported",
                "process_observation": "best_effort",
            },
        }

    def screenshot_readiness(self) -> dict[str, Any]:
        try:
            import PIL.ImageGrab  # noqa: F401
        except Exception:
            return {
                "available": False,
                "health": "unavailable",
                "code": "pillow_imagegrab_missing",
                "message": "Pillow ImageGrab is required for desktop screenshots.",
                "details": {"platform": self.platform_name, "python_dependency": "PIL"},
            }
        return {
            "available": True,
            "health": "available",
            "code": "ready",
            "message": "",
            "details": {"platform": self.platform_name},
        }

    def list_windows(
        self,
        *,
        limit: int = 80,
        include_minimized: bool = False,
    ) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        windows: list[dict[str, Any]] = []
        active: dict[str, Any] = {}
        if self._is_windows:
            windows = _windows_list(include_minimized=include_minimized)
            active = next((window for window in windows if window.get("active")), {})
        else:
            diagnostics.append(diagnostic(
                "window_observation_unsupported",
                "Window enumeration is not implemented for this platform yet.",
                severity="warning",
                platform=self.platform_name,
            ))
        return build_desktop_state(
            platform_name=self.platform_name,
            scope="windows",
            windows=windows[:max(1, int(limit or 80))],
            active_window=active,
            diagnostics=diagnostics,
        )

    def active_window(self) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        active: dict[str, Any] = {}
        if self._is_windows:
            active = _active_window() or {}
        else:
            diagnostics.append(diagnostic(
                "active_window_unsupported",
                "Active window detection is not implemented for this platform yet.",
                severity="warning",
                platform=self.platform_name,
            ))
        return build_desktop_state(
            platform_name=self.platform_name,
            scope="active_window",
            active_window=active,
            windows=[active] if active else [],
            diagnostics=diagnostics,
        )

    def list_processes(self, *, limit: int = 120) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        processes: list[dict[str, Any]] = []
        try:
            processes = _process_list(self.platform_name)
        except Exception as exc:
            diagnostics.append(diagnostic(
                "process_observation_failed",
                f"Process listing failed: {exc}",
                severity="warning",
                platform=self.platform_name,
            ))
        return build_desktop_state(
            platform_name=self.platform_name,
            scope="processes",
            processes=processes[:max(1, int(limit or 120))],
            diagnostics=diagnostics,
        )

    def capture_screen(
        self,
        *,
        output_path: Path,
        format: str = "png",
    ) -> dict[str, Any]:
        image = _grab_screen()
        output = _save_image(image, output_path, format)
        captured_at = utc_now_iso()
        state = build_desktop_state(
            platform_name=self.platform_name,
            scope="screen",
            active_window=self.active_window().get("active_window") or {},
            diagnostics=[],
            captured_at=captured_at,
        )
        evidence = build_visual_evidence(
            source_type="desktop_screen",
            screenshot_path=str(output["path"]),
            platform_name=self.platform_name,
            format=output["format"],
            width=output["width"],
            height=output["height"],
            size=output["size"],
            captured_at=captured_at,
        )
        return {
            "type": "desktop_observation",
            "source_type": "desktop_screen",
            "path": str(output["path"]),
            "format": output["format"],
            "size": output["size"],
            "width": output["width"],
            "height": output["height"],
            "artifact_kind": "screenshot",
            "artifacts": ["screenshot", "visual_evidence", "desktop_state"],
            "effects": ["artifact_write"],
            "roles": ["evidence", "verification"],
            "verification_strength": "standard",
            "desktop_state": state,
            "visual_evidence": evidence,
        }

    def capture_window(
        self,
        *,
        output_path: Path,
        window_id: str = "",
        title: str = "",
        format: str = "png",
    ) -> dict[str, Any]:
        window = self._resolve_window(window_id=window_id, title=title)
        bounds = window.get("bounds") if isinstance(window.get("bounds"), dict) else {}
        bbox = (
            int(bounds.get("left") or 0),
            int(bounds.get("top") or 0),
            int(bounds.get("right") or 0),
            int(bounds.get("bottom") or 0),
        )
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("window has invalid or empty bounds")
        image = _grab_screen(bbox=bbox)
        output = _save_image(image, output_path, format)
        captured_at = utc_now_iso()
        state = build_desktop_state(
            platform_name=self.platform_name,
            scope="window",
            windows=[window],
            active_window=self.active_window().get("active_window") or {},
            captured_at=captured_at,
        )
        evidence = build_visual_evidence(
            source_type="desktop_window",
            screenshot_path=str(output["path"]),
            platform_name=self.platform_name,
            source_window=window,
            format=output["format"],
            width=output["width"],
            height=output["height"],
            size=output["size"],
            captured_at=captured_at,
        )
        return {
            "type": "desktop_observation",
            "source_type": "desktop_window",
            "path": str(output["path"]),
            "format": output["format"],
            "size": output["size"],
            "width": output["width"],
            "height": output["height"],
            "artifact_kind": "screenshot",
            "artifacts": ["screenshot", "visual_evidence", "desktop_state"],
            "effects": ["artifact_write"],
            "roles": ["evidence", "verification"],
            "verification_strength": "standard",
            "window": window,
            "desktop_state": state,
            "visual_evidence": evidence,
        }

    def _resolve_window(self, *, window_id: str, title: str) -> dict[str, Any]:
        windows = self.list_windows(limit=300, include_minimized=False).get("windows") or []
        normalized_id = str(window_id or "").strip()
        if normalized_id:
            for window in windows:
                if str(window.get("window_id") or "") == normalized_id:
                    return window
            raise ValueError(f"window_id not found: {normalized_id}")
        needle = str(title or "").strip().lower()
        if not needle:
            active = self.active_window().get("active_window") or {}
            if active:
                return active
            raise ValueError("window_id or title is required when no active window is available")
        matches = [
            window for window in windows
            if needle in str(window.get("title") or "").lower()
        ]
        if not matches:
            raise ValueError(f"window title not found: {title}")
        if len(matches) > 1:
            candidates = [
                {
                    "window_id": item.get("window_id"),
                    "title": item.get("title"),
                    "process_id": item.get("process_id"),
                    "process_name": item.get("process_name"),
                }
                for item in matches[:10]
            ]
            raise ValueError(f"window title is ambiguous: {title}; candidates={candidates}")
        return matches[0]

    @property
    def _is_windows(self) -> bool:
        return self.platform_name.strip().lower().startswith("win")


def _grab_screen(*, bbox: tuple[int, int, int, int] | None = None) -> Any:
    from PIL import ImageGrab

    if bbox:
        return ImageGrab.grab(bbox=bbox)
    try:
        return ImageGrab.grab(all_screens=True)
    except TypeError:
        return ImageGrab.grab()


def _save_image(image: Any, output_path: Path, format: str) -> dict[str, Any]:
    fmt = _format_name(format)
    path = output_path
    if not path.suffix:
        path = path.with_suffix(f".{fmt if fmt != 'jpeg' else 'jpg'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    save_format = "JPEG" if fmt == "jpeg" else "PNG"
    image.save(path, format=save_format)
    width, height = image.size
    return {
        "path": path,
        "format": fmt,
        "width": int(width),
        "height": int(height),
        "size": path.stat().st_size,
    }


def _format_name(value: Any) -> str:
    fmt = str(value or "").strip().lower()
    if fmt == "jpg":
        return "jpeg"
    if fmt not in {"png", "jpeg"}:
        return "png"
    return fmt


def _windows_list(*, include_minimized: bool) -> list[dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    enum_windows = user32.EnumWindows
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    is_window_visible = user32.IsWindowVisible
    is_iconic = user32.IsIconic
    get_window_text_length = user32.GetWindowTextLengthW
    get_window_text = user32.GetWindowTextW
    get_window_thread_process_id = user32.GetWindowThreadProcessId
    get_window_rect = user32.GetWindowRect
    get_foreground_window = user32.GetForegroundWindow
    process_names = _windows_process_names()
    active_hwnd = int(get_foreground_window() or 0)
    records: list[dict[str, Any]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not is_window_visible(hwnd):
            return True
        minimized = bool(is_iconic(hwnd))
        if minimized and not include_minimized:
            return True
        length = int(get_window_text_length(hwnd))
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        get_window_text(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        get_window_thread_process_id(hwnd, ctypes.byref(pid))
        rect = wintypes.RECT()
        get_window_rect(hwnd, ctypes.byref(rect))
        records.append({
            "window_id": str(int(hwnd)),
            "title": title,
            "process_id": int(pid.value or 0),
            "process_name": process_names.get(int(pid.value or 0), ""),
            "visible": True,
            "minimized": minimized,
            "active": int(hwnd) == active_hwnd,
            "bounds": {
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
                "width": max(0, int(rect.right - rect.left)),
                "height": max(0, int(rect.bottom - rect.top)),
            },
        })
        return True

    enum_windows(enum_windows_proc(callback), 0)
    records.sort(key=lambda item: (not bool(item.get("active")), str(item.get("title") or "").lower()))
    return records


def _active_window() -> dict[str, Any] | None:
    windows = _windows_list(include_minimized=True)
    for window in windows:
        if window.get("active"):
            return window
    return None


def _process_list(platform_name: str) -> list[dict[str, Any]]:
    if platform_name.strip().lower().startswith("win"):
        return _windows_processes()
    return _posix_processes()


def _windows_process_names() -> dict[int, str]:
    return {
        int(item.get("process_id") or 0): str(item.get("name") or "")
        for item in _windows_processes(limit=10000)
        if int(item.get("process_id") or 0)
    }


def _windows_processes(*, limit: int = 10000) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "tasklist failed").strip())
    rows = csv.reader(io.StringIO(completed.stdout))
    records: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            pid = int(str(row[1]).strip())
        except ValueError:
            pid = 0
        records.append({
            "process_id": pid,
            "name": str(row[0]).strip(),
            "session_name": str(row[2]).strip() if len(row) > 2 else "",
            "memory": str(row[4]).strip() if len(row) > 4 else "",
        })
        if len(records) >= limit:
            break
    return records


def _posix_processes() -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,comm=,args="],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "ps failed").strip())
    records: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            pid = 0
        try:
            ppid = int(parts[1])
        except ValueError:
            ppid = 0
        records.append({
            "process_id": pid,
            "parent_process_id": ppid,
            "name": parts[2],
            "command": parts[3] if len(parts) > 3 else "",
        })
    return records
