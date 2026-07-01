"""Preview and visual-debug tools backed by Playwright."""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import re
from pathlib import Path
from threading import Thread
import time
from typing import Any
from urllib.parse import quote

from runtime.debug_session import build_debug_session
from runtime.tool_registry import ToolRegistry, ToolSpec
from runtime.visual_evidence import build_visual_evidence

from .web import _validate_url


DEFAULT_TIMEOUT = 20
MAX_TIMEOUT = 60
USER_AGENT = (
    "YuntaoCode/0.1 "
    "(preview capability; +https://localhost.local)"
)
TASK_TEMP_ALIASES = {"", "task_temp", "__task_temp__", "$TASK_TEMP", "{task_temp}"}


async def capture_url(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    """Capture a visual preview of an HTTP(S) page."""

    url = _validate_url(input_data.get("url"))
    output_path = _resolve_output_path(
        input_data,
        context,
        default_label=_safe_label(url, "page"),
    )
    return await _capture_page(
        url,
        output_path,
        input_data,
        context,
        source_type="url",
        source_path="",
    )


async def capture_local_html(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    """Capture a visual preview of a local HTML file inside the workspace."""

    source_path = context.path_guard.resolve(input_data.get("path"))
    if not source_path.is_file():
        raise ValueError(f"HTML file not found: {source_path}")
    if source_path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("preview.capture_local_html expects a .html or .htm file")
    output_path = _resolve_output_path(
        input_data,
        context,
        default_label=_safe_label(source_path.stem, "local-html"),
    )
    serve_mode = str(input_data.get("serve_mode") or "http").strip().lower()
    if serve_mode == "file":
        return await _capture_page(
            source_path.as_uri(),
            output_path,
            input_data,
            context,
            source_type="local_html",
            source_path=str(source_path),
            served_via="file",
            served_root=str(source_path.parent),
        )
    if serve_mode not in {"http", "localhost", "static"}:
        raise ValueError("serve_mode must be http or file")
    with _local_static_server(source_path.parent) as base_url:
        url = f"{base_url}/{quote(source_path.name)}"
        return await _capture_page(
            url,
            output_path,
            input_data,
            context,
            source_type="local_html",
            source_path=str(source_path),
            served_via="localhost",
            served_root=str(source_path.parent),
        )


async def interact_page(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    """Open a page, run bounded Playwright actions, and capture verification evidence."""

    path_value = str(input_data.get("path") or "").strip()
    url_value = str(input_data.get("url") or "").strip()
    if not path_value and not url_value:
        raise ValueError("preview.interact_page requires either url or path")
    output_path = _resolve_output_path(
        input_data,
        context,
        default_label=_safe_label(path_value or url_value, "interaction"),
    )
    if url_value:
        url = _validate_url(url_value)
        return await _interact_with_page(
            url,
            output_path,
            input_data,
            context,
            source_type="url",
            source_path="",
        )

    source_path = context.path_guard.resolve(path_value)
    if not source_path.is_file():
        raise ValueError(f"HTML file not found: {source_path}")
    if source_path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("preview.interact_page path expects a .html or .htm file")
    serve_mode = str(input_data.get("serve_mode") or "http").strip().lower()
    if serve_mode == "file":
        return await _interact_with_page(
            source_path.as_uri(),
            output_path,
            input_data,
            context,
            source_type="local_html",
            source_path=str(source_path),
            served_via="file",
            served_root=str(source_path.parent),
        )
    if serve_mode not in {"http", "localhost", "static"}:
        raise ValueError("serve_mode must be http or file")
    with _local_static_server(source_path.parent) as base_url:
        url = f"{base_url}/{quote(source_path.name)}"
        return await _interact_with_page(
            url,
            output_path,
            input_data,
            context,
            source_type="local_html",
            source_path=str(source_path),
            served_via="localhost",
            served_root=str(source_path.parent),
        )


async def _capture_page(
    url: str,
    output_path: Path,
    input_data: dict[str, Any],
    context: Any,
    *,
    source_type: str,
    source_path: str,
    served_via: str = "",
    served_root: str = "",
) -> dict[str, Any]:
    capture_format = _capture_format(input_data.get("format"), output_path)
    timeout = max(1, min(int(input_data.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    wait_until = str(input_data.get("wait_until") or "networkidle").strip()
    if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
        wait_until = "networkidle"
    full_page = input_data.get("full_page", True) is not False
    width = max(320, int(input_data.get("width") or 1440))
    height = max(240, int(input_data.get("height") or 1000))
    ignore_https_errors = input_data.get("ignore_https_errors", True) is not False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if callable(getattr(context, "backup_file", None)) and output_path.exists():
        context.backup_file(output_path)

    console_messages: list[dict[str, str]] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, str]] = []
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()

    async with _async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=USER_AGENT,
            viewport={"width": width, "height": height},
            ignore_https_errors=ignore_https_errors,
        )
        page.on("console", lambda message: _record_console(console_messages, message))
        page.on("pageerror", lambda error: page_errors.append(str(error)[:500]))
        page.on("requestfailed", lambda request: _record_failed_request(failed_requests, request))
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
            title = await page.title()
            if capture_format in {"png", "jpeg"}:
                await page.screenshot(
                    path=str(output_path),
                    full_page=full_page,
                    type=capture_format,
                )
            else:
                raise ValueError("format must be png or jpeg for preview captures")
            status_code = response.status if response else 0
        finally:
            await browser.close()

    error_messages = [
        item for item in console_messages
        if item.get("type") in {"error", "assert"}
    ]
    warning_messages = [
        item for item in console_messages
        if item.get("type") == "warning"
    ]
    blocking_failed_requests = [
        item for item in failed_requests
        if _failed_request_is_blocking(item)
    ]
    has_runtime_errors = bool(error_messages or page_errors or blocking_failed_requests)
    debug_session = build_debug_session(
        source_type="preview.capture_page",
        command=f"playwright capture {url}",
        executable="playwright.chromium",
        cwd=served_root,
        exit_code=1 if has_runtime_errors else 0,
        timed_out=False,
        timeout=timeout,
        stdout=f"title={title}; status_code={status_code}",
        stderr=_preview_error_summary(error_messages, page_errors, blocking_failed_requests),
        service={
            "kind": "browser_preview",
            "url": url,
            "status_code": status_code,
            "served_via": served_via,
            "served_root": served_root,
            "wait_until": wait_until,
            "ignore_https_errors": ignore_https_errors,
        },
        started_at=started_at,
        finished_at=_utc_now_iso(),
        duration_seconds=round(max(0.0, time.monotonic() - started_monotonic), 3),
    )
    visual_evidence = build_visual_evidence(
        source_type=source_type,
        source_url=url,
        source_path=source_path,
        served_via=served_via,
        served_root=served_root,
        screenshot_path=str(output_path),
        artifact_kind="screenshot",
        format=capture_format,
        size=output_path.stat().st_size,
        width=width,
        height=height,
        full_page=full_page,
        status_code=status_code,
        title=title,
        console_errors=error_messages,
        console_warnings=warning_messages,
        page_errors=page_errors,
        failed_requests=failed_requests,
        has_runtime_errors=has_runtime_errors,
        provider="playwright",
    )
    context.log("info", "preview captured", {"url": url, "path": str(output_path)})
    return {
        "type": "preview_capture",
        "source_type": source_type,
        "source_path": source_path,
        "served_via": served_via,
        "served_root": served_root,
        "url": url,
        "status_code": status_code,
        "title": title,
        "path": str(output_path),
        "format": capture_format,
        "size": output_path.stat().st_size,
        "width": width,
        "height": height,
        "full_page": full_page,
        "artifact_kind": "screenshot",
        "artifacts": ["screenshot", "visual_evidence"],
        "effects": ["artifact_write"],
        "roles": ["verification"],
        "verification_strength": "standard",
        "console_errors": error_messages[:20],
        "console_warnings": warning_messages[:20],
        "page_errors": page_errors[:20],
        "failed_requests": failed_requests[:20],
        "has_runtime_errors": has_runtime_errors,
        "debug_session": debug_session,
        "visual_evidence": visual_evidence,
    }


async def _interact_with_page(
    url: str,
    output_path: Path,
    input_data: dict[str, Any],
    context: Any,
    *,
    source_type: str,
    source_path: str,
    served_via: str = "",
    served_root: str = "",
) -> dict[str, Any]:
    capture_format = _capture_format(input_data.get("format"), output_path)
    timeout = max(1, min(int(input_data.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    action_timeout = max(1, min(int(input_data.get("action_timeout") or 5), MAX_TIMEOUT))
    wait_until = str(input_data.get("wait_until") or "networkidle").strip()
    if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
        wait_until = "networkidle"
    full_page = input_data.get("full_page", True) is not False
    width = max(320, int(input_data.get("width") or 1440))
    height = max(240, int(input_data.get("height") or 1000))
    ignore_https_errors = input_data.get("ignore_https_errors", True) is not False
    actions = _normalize_actions(input_data.get("actions"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if callable(getattr(context, "backup_file", None)) and output_path.exists():
        context.backup_file(output_path)

    console_messages: list[dict[str, str]] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, str]] = []
    action_results: list[dict[str, Any]] = []
    assertion_failures: list[dict[str, Any]] = []
    status_code = 0
    title = ""
    body_text = ""
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()

    async with _async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=USER_AGENT,
            viewport={"width": width, "height": height},
            ignore_https_errors=ignore_https_errors,
        )
        page.on("console", lambda message: _record_console(console_messages, message))
        page.on("pageerror", lambda error: page_errors.append(str(error)[:500]))
        page.on("requestfailed", lambda request: _record_failed_request(failed_requests, request))
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
            status_code = response.status if response else 0
            for index, action in enumerate(actions):
                result = await _run_interaction_action(
                    page,
                    action,
                    index=index,
                    action_timeout_ms=action_timeout * 1000,
                )
                action_results.append(result)
                if not result.get("ok"):
                    assertion_failures.append(result)
            title = await page.title()
            body_text = await _read_body_text(page)
            if capture_format in {"png", "jpeg"}:
                await page.screenshot(
                    path=str(output_path),
                    full_page=full_page,
                    type=capture_format,
                )
            else:
                raise ValueError("format must be png or jpeg for preview interactions")
        finally:
            await browser.close()

    error_messages = [
        item for item in console_messages
        if item.get("type") in {"error", "assert"}
    ]
    warning_messages = [
        item for item in console_messages
        if item.get("type") == "warning"
    ]
    blocking_failed_requests = [
        item for item in failed_requests
        if _failed_request_is_blocking(item)
    ]
    has_runtime_errors = bool(
        error_messages or page_errors or blocking_failed_requests or assertion_failures
    )
    stderr = _preview_error_summary(error_messages, page_errors, blocking_failed_requests)
    if assertion_failures:
        suffix = f"assertion_failures={len(assertion_failures)}"
        stderr = f"{stderr}; {suffix}" if stderr else suffix
    debug_session = build_debug_session(
        source_type="preview.interact_page",
        command=f"playwright interact {url}",
        executable="playwright.chromium",
        cwd=served_root,
        exit_code=1 if has_runtime_errors else 0,
        timed_out=False,
        timeout=timeout,
        stdout=f"title={title}; status_code={status_code}; actions={len(action_results)}",
        stderr=stderr,
        service={
            "kind": "browser_interaction",
            "url": url,
            "status_code": status_code,
            "served_via": served_via,
            "served_root": served_root,
            "wait_until": wait_until,
            "ignore_https_errors": ignore_https_errors,
            "action_timeout": action_timeout,
        },
        diagnostics=[
            {
                "code": "interaction_action_failed",
                "message": str(item.get("message") or item.get("error") or "interaction action failed")[:500],
                "action_index": item.get("index"),
                "action": item.get("action"),
            }
            for item in assertion_failures[:10]
        ],
        started_at=started_at,
        finished_at=_utc_now_iso(),
        duration_seconds=round(max(0.0, time.monotonic() - started_monotonic), 3),
    )
    visual_evidence = build_visual_evidence(
        source_type=source_type,
        source_url=url,
        source_path=source_path,
        served_via=served_via,
        served_root=served_root,
        screenshot_path=str(output_path),
        artifact_kind="screenshot",
        format=capture_format,
        size=output_path.stat().st_size,
        width=width,
        height=height,
        full_page=full_page,
        status_code=status_code,
        title=title,
        console_errors=error_messages,
        console_warnings=warning_messages,
        page_errors=page_errors,
        failed_requests=failed_requests,
        has_runtime_errors=has_runtime_errors,
        provider="playwright",
    )
    context.log("info", "preview interaction captured", {"url": url, "path": str(output_path)})
    return {
        "type": "preview_interaction",
        "source_type": source_type,
        "source_path": source_path,
        "served_via": served_via,
        "served_root": served_root,
        "url": url,
        "status_code": status_code,
        "title": title,
        "path": str(output_path),
        "format": capture_format,
        "size": output_path.stat().st_size,
        "width": width,
        "height": height,
        "full_page": full_page,
        "artifact_kind": "screenshot",
        "artifacts": ["screenshot", "visual_evidence", "interaction_trace", "dom_text"],
        "effects": ["artifact_write"],
        "roles": ["verification"],
        "verification_strength": "standard" if not has_runtime_errors else "none",
        "interaction": {
            "actions": action_results[:40],
            "action_count": len(action_results),
            "assertion_failed_count": len(assertion_failures),
        },
        "text": body_text[:8000],
        "text_chars": len(body_text),
        "console_errors": error_messages[:20],
        "console_warnings": warning_messages[:20],
        "page_errors": page_errors[:20],
        "failed_requests": failed_requests[:20],
        "has_runtime_errors": has_runtime_errors,
        "debug_session": debug_session,
        "visual_evidence": visual_evidence,
    }


def _normalize_actions(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("actions must be an array")
    actions: list[dict[str, Any]] = []
    for index, item in enumerate(value[:40]):
        if not isinstance(item, dict):
            raise ValueError(f"actions[{index}] must be an object")
        action = str(item.get("action") or item.get("type") or item.get("name") or "").strip().lower()
        if not action:
            raise ValueError(f"actions[{index}] is missing action")
        if action not in {
            "click",
            "fill",
            "press",
            "wait",
            "wait_for_selector",
            "read_text",
            "assert_text",
            "assert_not_text",
        }:
            raise ValueError(f"unsupported preview interaction action: {action}")
        normalized = dict(item)
        normalized["action"] = action
        actions.append(normalized)
    return actions


async def _run_interaction_action(
    page: Any,
    action: dict[str, Any],
    *,
    index: int,
    action_timeout_ms: int,
) -> dict[str, Any]:
    kind = str(action.get("action") or "").strip().lower()
    selector = str(action.get("selector") or "").strip()
    label = str(action.get("label") or selector or kind)
    result: dict[str, Any] = {
        "index": index,
        "action": kind,
        "label": label[:200],
    }
    try:
        if kind == "click":
            if not selector:
                raise ValueError("click action requires selector")
            await page.locator(selector).click(timeout=action_timeout_ms)
        elif kind == "fill":
            if not selector:
                raise ValueError("fill action requires selector")
            await page.locator(selector).fill(str(action.get("value") or ""), timeout=action_timeout_ms)
        elif kind == "press":
            key = str(action.get("key") or action.get("value") or "").strip()
            if not key:
                raise ValueError("press action requires key")
            if selector:
                await page.locator(selector).press(key, timeout=action_timeout_ms)
            else:
                await page.keyboard.press(key)
        elif kind == "wait":
            milliseconds = max(0, min(int(action.get("milliseconds") or action.get("ms") or 500), 30_000))
            await page.wait_for_timeout(milliseconds)
            result["milliseconds"] = milliseconds
        elif kind == "wait_for_selector":
            if not selector:
                raise ValueError("wait_for_selector action requires selector")
            await page.wait_for_selector(selector, timeout=action_timeout_ms)
        elif kind == "read_text":
            text = await _read_selector_or_body_text(page, selector)
            result["text"] = text[:2000]
            result["text_chars"] = len(text)
        elif kind in {"assert_text", "assert_not_text"}:
            expected = str(action.get("text") or action.get("contains") or action.get("value") or "")
            if not expected:
                raise ValueError(f"{kind} action requires text")
            text = await _read_selector_or_body_text(page, selector)
            case_sensitive = action.get("case_sensitive", True) is not False
            haystack = text if case_sensitive else text.lower()
            needle = expected if case_sensitive else expected.lower()
            contains = needle in haystack
            ok = contains if kind == "assert_text" else not contains
            result.update({
                "expected": expected[:500],
                "matched": contains,
                "text_preview": text[:1200],
                "text_chars": len(text),
            })
            if not ok:
                result["ok"] = False
                result["message"] = (
                    f"expected text {'to be present' if kind == 'assert_text' else 'to be absent'}: "
                    f"{expected[:200]}"
                )
                return result
        result["ok"] = True
        return result
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)[:500]
        result["message"] = result["error"]
        return result


async def _read_selector_or_body_text(page: Any, selector: str) -> str:
    if selector:
        locator = page.locator(selector)
        if callable(getattr(locator, "inner_text", None)):
            return str(await locator.inner_text(timeout=1000))
    return await _read_body_text(page)


async def _read_body_text(page: Any) -> str:
    try:
        locator = page.locator("body")
        if callable(getattr(locator, "inner_text", None)):
            return str(await locator.inner_text(timeout=1000))
    except Exception:
        pass
    try:
        return str(await page.evaluate("() => document.body ? document.body.innerText : ''"))
    except Exception:
        return ""


def _resolve_output_path(input_data: dict[str, Any], context: Any, *, default_label: str) -> Path:
    raw_output = str(input_data.get("output_path") or "").strip()
    if raw_output:
        if _is_task_temp_path(raw_output):
            return _resolve_task_temp_file(context, raw_output, default_label)
        return context.path_guard.resolve(raw_output)

    raw_output_dir = str(input_data.get("output_dir") or "").strip()
    filename = f"{default_label}.{_capture_format(input_data.get('format'), Path(default_label + '.png'))}"
    if not raw_output_dir or raw_output_dir in TASK_TEMP_ALIASES:
        return _task_temp_root(context) / "preview" / filename
    return context.path_guard.resolve(raw_output_dir) / filename


def _resolve_task_temp_file(context: Any, raw_output: str, default_label: str) -> Path:
    temp_root = _task_temp_root(context)
    value = raw_output.strip().replace("\\", "/")
    for alias in ("task_temp/", "__task_temp__/", "$TASK_TEMP/", "{task_temp}/"):
        if value.startswith(alias):
            value = value[len(alias):]
            break
    if not value or value in TASK_TEMP_ALIASES:
        value = f"preview/{default_label}.png"
    path = (temp_root / value).resolve()
    if temp_root not in path.parents and path != temp_root:
        raise ValueError("output_path escapes task_temp")
    if not path.suffix:
        path = path.with_suffix(".png")
    return path


def _task_temp_root(context: Any) -> Path:
    temp_dir = getattr(context, "temp_dir", None)
    if temp_dir is None:
        raise RuntimeError("preview captures require a task temp directory or explicit output_path")
    root = Path(temp_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _capture_format(value: Any, output_path: Path) -> str:
    fmt = str(value or "").strip().lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if not fmt:
        fmt = {
            ".png": "png",
            ".jpg": "jpeg",
            ".jpeg": "jpeg",
        }.get(output_path.suffix.lower(), "png")
    if fmt not in {"png", "jpeg"}:
        raise ValueError("format must be png or jpeg")
    return fmt


def _record_console(target: list[dict[str, str]], message: Any) -> None:
    target.append({
        "type": str(_read_attr(message, "type") or ""),
        "text": str(_read_attr(message, "text") or "")[:500],
    })


def _record_failed_request(target: list[dict[str, str]], request: Any) -> None:
    failure = getattr(request, "failure", None)
    if callable(failure):
        try:
            failure = failure()
        except Exception:
            failure = None
    error_text = ""
    if isinstance(failure, dict):
        error_text = str(failure.get("errorText") or "")
    elif failure is not None:
        error_text = str(failure)
    target.append({
        "url": str(_read_attr(request, "url") or "")[:500],
        "method": str(_read_attr(request, "method") or "")[:40],
        "error": error_text[:500],
    })


def _read_attr(obj: Any, name: str) -> Any:
    value = getattr(obj, name, "")
    if callable(value):
        try:
            return value()
        except TypeError:
            return value
    return value


def _preview_error_summary(
    console_errors: list[dict[str, str]],
    page_errors: list[str],
    failed_requests: list[dict[str, str]],
) -> str:
    parts: list[str] = []
    if console_errors:
        parts.append(f"console_errors={len(console_errors)}")
    if page_errors:
        parts.append(f"page_errors={len(page_errors)}")
    if failed_requests:
        parts.append(f"failed_requests={len(failed_requests)}")
    return "; ".join(parts)


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_label(value: Any, default: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[a-z]+://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    return (text[:90].strip(".-_") or default).lower()


def _is_task_temp_path(value: str) -> bool:
    normalized = str(value or "").strip().replace("\\", "/")
    return any(normalized == alias.rstrip("/") or normalized.startswith(alias) for alias in (
        "task_temp/",
        "__task_temp__/",
        "$TASK_TEMP/",
        "{task_temp}/",
    ))


def _async_playwright() -> Any:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise ValueError(
            "playwright is required for preview captures. Install: pip install playwright && playwright install chromium"
        ) from exc
    return async_playwright()


class _PreviewHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return None

    def copyfile(self, source: Any, outputfile: Any) -> None:
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            return None


@contextmanager
def _local_static_server(directory: Path):
    root = Path(directory).resolve()
    handler = partial(_QuietStaticHandler, directory=str(root))
    server = _PreviewHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _failed_request_is_blocking(item: dict[str, str]) -> bool:
    error = str(item.get("error") or "").strip().lower()
    url = str(item.get("url") or "").strip().lower()
    if error == "net::err_aborted" and url.endswith((
        ".mp4",
        ".webm",
        ".ogg",
        ".mp3",
        ".wav",
        ".m4a",
    )):
        return False
    return True


def register_preview_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="preview.capture_url",
            name="网页视觉预览",
            description=(
                "使用 Playwright 打开 http/https URL，生成截图并返回 console、page error、failed request 等视觉调试证据。"
                "适合验证网页、localhost 页面或前端界面是否真实渲染。默认截图写入任务临时目录，不污染项目文件。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要预览的 http/https URL"},
                    "output_path": {"type": "string", "description": "可选输出路径；默认写入 task_temp/preview"},
                    "output_dir": {"type": "string", "description": "可选输出目录；传 task_temp 使用任务临时目录"},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                    "wait_until": {"type": "string", "default": "networkidle"},
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "width": {"type": "integer", "default": 1440},
                    "height": {"type": "integer", "default": 1000},
                    "full_page": {"type": "boolean", "default": True},
                    "ignore_https_errors": {"type": "boolean", "default": True},
                },
                "required": ["url"],
            },
            requires_confirmation=False,
            local_only=False,
            optional_dependencies=["playwright"],
            capability="preview.visual_debug",
            artifacts=["screenshot", "visual_evidence"],
            effects=["artifact_write"],
            roles=["verification"],
            verification_strength="standard",
            retry_safe=True,
        ),
        capture_url,
    )
    registry.register(
        ToolSpec(
            id="preview.capture_local_html",
            name="本地 HTML 视觉预览",
            description=(
                "使用 Playwright 打开工作区内的 .html/.htm 文件，生成截图并返回 console、page error、failed request 等视觉调试证据。"
                "适合 HTML、CSS、JS、宣传页、3D viewer 等本地页面写入后的视觉验证。默认截图写入任务临时目录。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内 HTML 文件路径"},
                    "output_path": {"type": "string", "description": "可选输出路径；默认写入 task_temp/preview"},
                    "output_dir": {"type": "string", "description": "可选输出目录；传 task_temp 使用任务临时目录"},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                    "wait_until": {"type": "string", "default": "networkidle"},
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "width": {"type": "integer", "default": 1440},
                    "height": {"type": "integer", "default": 1000},
                    "full_page": {"type": "boolean", "default": True},
                    "serve_mode": {"type": "string", "enum": ["http", "file"], "default": "http"},
                },
                "required": ["path"],
            },
            requires_confirmation=False,
            local_only=True,
            optional_dependencies=["playwright"],
            capability="preview.visual_debug",
            artifacts=["screenshot", "visual_evidence"],
            effects=["artifact_write"],
            roles=["verification"],
            verification_strength="standard",
            retry_safe=True,
        ),
        capture_local_html,
    )
    registry.register(
        ToolSpec(
            id="preview.interact_page",
            name="页面交互验证",
            description=(
                "使用 Playwright 打开 http/https URL 或工作区内的 .html/.htm 文件，执行一组有界交互动作，"
                "并返回截图、DOM 文本、console/page/network/debug 证据。"
                "适合在前端或 HTML 写入后，让模型自行点击、输入、等待和断言页面反馈是否符合目标。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要验证的 http/https URL；与 path 二选一"},
                    "path": {"type": "string", "description": "工作区内 HTML 文件路径；与 url 二选一"},
                    "actions": {
                        "type": "array",
                        "description": "按顺序执行的页面动作；最多 40 步",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": [
                                        "click",
                                        "fill",
                                        "press",
                                        "wait",
                                        "wait_for_selector",
                                        "read_text",
                                        "assert_text",
                                        "assert_not_text",
                                    ],
                                },
                                "selector": {"type": "string", "description": "CSS/text selector；例如 button 或 text=开始"},
                                "value": {"type": "string", "description": "fill/press/assert 的值"},
                                "text": {"type": "string", "description": "assert_text/assert_not_text 的期望文本"},
                                "key": {"type": "string", "description": "press 使用的按键名"},
                                "milliseconds": {"type": "integer", "description": "wait 使用的等待毫秒数"},
                                "label": {"type": "string", "description": "动作说明，便于任务记录展示"},
                                "case_sensitive": {"type": "boolean", "default": True},
                            },
                            "required": ["action"],
                        },
                    },
                    "output_path": {"type": "string", "description": "可选输出路径；默认写入 task_temp/preview"},
                    "output_dir": {"type": "string", "description": "可选输出目录；传 task_temp 使用任务临时目录"},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                    "wait_until": {"type": "string", "default": "networkidle"},
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "action_timeout": {"type": "integer", "default": 5},
                    "width": {"type": "integer", "default": 1440},
                    "height": {"type": "integer", "default": 1000},
                    "full_page": {"type": "boolean", "default": True},
                    "serve_mode": {"type": "string", "enum": ["http", "file"], "default": "http"},
                    "ignore_https_errors": {"type": "boolean", "default": True},
                },
            },
            requires_confirmation=False,
            local_only=False,
            optional_dependencies=["playwright"],
            capability="preview.visual_debug",
            artifacts=["screenshot", "visual_evidence", "interaction_trace", "dom_text"],
            effects=["artifact_write"],
            roles=["verification"],
            verification_strength="standard",
            retry_safe=True,
        ),
        interact_page,
    )
