"""Thin YuntaoCode adapter for the incubating Desktop Observation Provider."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from providers.desktop_observation import DesktopObservationService
from runtime.tool_registry import ToolRegistry, ToolSpec


TASK_TEMP_ALIASES = {"", "task_temp", "__task_temp__", "$TASK_TEMP", "{task_temp}"}
DEFAULT_SCREENSHOT_FORMAT = "png"
DESKTOP_PROVIDER_ID = "desktop"
DESKTOP_CAPABILITY_ID = "desktop.observation"


async def list_windows(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    service = _service()
    result = service.list_windows(
        limit=_bounded_int(input_data.get("limit"), default=80, minimum=1, maximum=300),
        include_minimized=bool(input_data.get("include_minimized", False)),
    )
    _log(context, "info", "desktop windows observed", {"count": result.get("counts", {}).get("windows")})
    return {
        "type": "desktop_observation",
        "source_type": "desktop_windows",
        "desktop_state": result,
        "windows": result.get("windows") or [],
        "active_window": result.get("active_window") or {},
        "diagnostics": result.get("diagnostics") or [],
        "artifacts": ["desktop_state"],
        "effects": [],
        "roles": ["evidence", "verification"],
        "verification_strength": "weak",
    }


async def active_window(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    result = _service().active_window()
    _log(context, "info", "desktop active window observed", {"active": result.get("active_window")})
    return {
        "type": "desktop_observation",
        "source_type": "desktop_active_window",
        "desktop_state": result,
        "active_window": result.get("active_window") or {},
        "windows": result.get("windows") or [],
        "diagnostics": result.get("diagnostics") or [],
        "artifacts": ["desktop_state"],
        "effects": [],
        "roles": ["evidence", "verification"],
        "verification_strength": "weak",
    }


async def list_processes(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    result = _service().list_processes(
        limit=_bounded_int(input_data.get("limit"), default=120, minimum=1, maximum=1000),
    )
    _log(context, "info", "desktop processes observed", {"count": result.get("counts", {}).get("processes")})
    return {
        "type": "desktop_observation",
        "source_type": "desktop_processes",
        "desktop_state": result,
        "processes": result.get("processes") or [],
        "diagnostics": result.get("diagnostics") or [],
        "artifacts": ["desktop_state", "process_list"],
        "effects": [],
        "roles": ["evidence", "verification"],
        "verification_strength": "weak",
    }


async def capture_screen(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    output_path = _resolve_output_path(input_data, context, default_label="screen")
    result = _service().capture_screen(
        output_path=output_path,
        format=_capture_format(input_data.get("format"), output_path),
    )
    _log(context, "info", "desktop screen captured", {"path": result.get("path")})
    return result


async def capture_window(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    title = str(input_data.get("title") or "").strip()
    window_id = str(input_data.get("window_id") or "").strip()
    output_path = _resolve_output_path(
        input_data,
        context,
        default_label=_safe_label(title or window_id or "window"),
    )
    result = _service().capture_window(
        output_path=output_path,
        window_id=window_id,
        title=title,
        format=_capture_format(input_data.get("format"), output_path),
    )
    _log(context, "info", "desktop window captured", {"path": result.get("path"), "window": result.get("window")})
    return result


def desktop_observation_readiness() -> dict[str, Any]:
    return _service().readiness()


def desktop_screenshot_readiness() -> dict[str, Any]:
    return _service().screenshot_readiness()


def register_desktop_tools(registry: ToolRegistry) -> None:
    registry.set_provider_metadata(
        DESKTOP_PROVIDER_ID,
        source_type="desktop_observation",
        source_id="desktop_observation",
        provider_kind="desktop",
        display_name="Desktop Observation Provider",
        lifecycle="local_observer",
    )
    registry.register(
        ToolSpec(
            id="desktop.list_windows",
            name="列出桌面窗口",
            description=(
                "只读列出当前本机可观察窗口、活动窗口、标题、进程和窗口边界。"
                "用于让模型了解外部应用是否打开，不执行点击、输入或窗口控制。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 80},
                    "include_minimized": {"type": "boolean", "default": False},
                },
            },
            requires_confirmation=False,
            local_only=True,
            capability=DESKTOP_CAPABILITY_ID,
            artifacts=["desktop_state"],
            effects=[],
            roles=["evidence", "verification"],
            verification_strength="weak",
            retry_safe=True,
            idempotent=True,
            readiness_probe=desktop_observation_readiness,
        ),
        list_windows,
    )
    registry.register(
        ToolSpec(
            id="desktop.active_window",
            name="读取活动窗口",
            description="只读返回当前活动窗口事实，不执行焦点切换或窗口控制。",
            input_schema={"type": "object", "properties": {}},
            requires_confirmation=False,
            local_only=True,
            capability=DESKTOP_CAPABILITY_ID,
            artifacts=["desktop_state"],
            effects=[],
            roles=["evidence", "verification"],
            verification_strength="weak",
            retry_safe=True,
            idempotent=True,
            readiness_probe=desktop_observation_readiness,
        ),
        active_window,
    )
    registry.register(
        ToolSpec(
            id="desktop.list_processes",
            name="列出本机进程",
            description="只读列出本机进程摘要，用于确认外部程序或服务是否运行。",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 120},
                },
            },
            requires_confirmation=False,
            local_only=True,
            capability=DESKTOP_CAPABILITY_ID,
            artifacts=["desktop_state", "process_list"],
            effects=[],
            roles=["evidence", "verification"],
            verification_strength="weak",
            retry_safe=True,
            idempotent=True,
            readiness_probe=desktop_observation_readiness,
        ),
        list_processes,
    )
    registry.register(
        ToolSpec(
            id="desktop.capture_screen",
            name="截取当前桌面",
            description=(
                "截取当前桌面并写入任务临时目录，返回 desktop_state 和 visual_evidence。"
                "这是只读观察，但可能包含隐私内容，因此默认需要用户确认。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "output_path": {"type": "string", "description": "可选输出路径；默认写入 task_temp/desktop"},
                    "output_dir": {"type": "string", "description": "可选输出目录；传 task_temp 使用任务临时目录"},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": DEFAULT_SCREENSHOT_FORMAT},
                },
            },
            requires_confirmation=True,
            local_only=True,
            optional_dependencies=["PIL"],
            capability=DESKTOP_CAPABILITY_ID,
            artifacts=["screenshot", "visual_evidence", "desktop_state"],
            effects=["artifact_write"],
            roles=["evidence", "verification"],
            verification_strength="standard",
            retry_safe=True,
            readiness_probe=desktop_screenshot_readiness,
        ),
        capture_screen,
    )
    registry.register(
        ToolSpec(
            id="desktop.capture_window",
            name="截取指定窗口",
            description=(
                "按 window_id 或窗口标题截取指定窗口，返回 desktop_state 和 visual_evidence。"
                "标题匹配到多个窗口时返回候选，不自动选择。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "window_id": {"type": "string", "description": "desktop.list_windows 返回的 window_id"},
                    "title": {"type": "string", "description": "窗口标题片段；与 window_id 二选一"},
                    "output_path": {"type": "string", "description": "可选输出路径；默认写入 task_temp/desktop"},
                    "output_dir": {"type": "string", "description": "可选输出目录；传 task_temp 使用任务临时目录"},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": DEFAULT_SCREENSHOT_FORMAT},
                },
            },
            requires_confirmation=True,
            local_only=True,
            optional_dependencies=["PIL"],
            capability=DESKTOP_CAPABILITY_ID,
            artifacts=["screenshot", "visual_evidence", "desktop_state"],
            effects=["artifact_write"],
            roles=["evidence", "verification"],
            verification_strength="standard",
            retry_safe=True,
            readiness_probe=desktop_screenshot_readiness,
        ),
        capture_window,
    )


def _service() -> DesktopObservationService:
    return DesktopObservationService()


def _resolve_output_path(input_data: dict[str, Any], context: Any, *, default_label: str) -> Path:
    raw_output = str(input_data.get("output_path") or "").strip()
    if raw_output:
        if _is_task_temp_path(raw_output):
            return _resolve_task_temp_file(context, raw_output, default_label)
        return context.path_guard.resolve(raw_output)

    raw_output_dir = str(input_data.get("output_dir") or "").strip()
    filename = f"{default_label}.{_capture_format(input_data.get('format'), Path(default_label + '.png'))}"
    if not raw_output_dir or raw_output_dir in TASK_TEMP_ALIASES:
        return _task_temp_root(context) / "desktop" / filename
    return context.path_guard.resolve(raw_output_dir) / filename


def _resolve_task_temp_file(context: Any, raw_output: str, default_label: str) -> Path:
    temp_root = _task_temp_root(context)
    value = raw_output.strip().replace("\\", "/")
    for alias in ("task_temp/", "__task_temp__/", "$TASK_TEMP/", "{task_temp}/"):
        if value.startswith(alias):
            value = value[len(alias):]
            break
    if not value or value in TASK_TEMP_ALIASES:
        value = f"desktop/{default_label}.png"
    path = (temp_root / value).resolve()
    if temp_root not in path.parents and path != temp_root:
        raise ValueError("output_path escapes task_temp")
    if not path.suffix:
        path = path.with_suffix(".png")
    return path


def _task_temp_root(context: Any) -> Path:
    temp_dir = getattr(context, "temp_dir", None)
    if temp_dir is None:
        raise RuntimeError("desktop captures require a task temp directory or explicit output_path")
    root = Path(temp_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_task_temp_path(value: str) -> bool:
    normalized = str(value or "").strip().replace("\\", "/")
    return normalized in TASK_TEMP_ALIASES or normalized.startswith((
        "task_temp/",
        "__task_temp__/",
        "$TASK_TEMP/",
        "{task_temp}/",
    ))


def _capture_format(value: Any, output_path: Path) -> str:
    fmt = str(value or "").strip().lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt in {"png", "jpeg"}:
        return fmt
    suffix = output_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "jpeg"
    return "png"


def _safe_label(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return text[:80] or "window"


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _log(context: Any, level: str, message: str, data: dict[str, Any]) -> None:
    logger = getattr(context, "log", None)
    if callable(logger):
        logger(level, message, data)

