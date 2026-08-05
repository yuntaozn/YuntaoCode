"""基于 Playwright 和本地渲染器的预览工具。"""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import shutil
from pathlib import Path
from threading import Thread
import time
from typing import Any
from urllib.parse import quote

from runtime.debug_session import build_debug_session
from runtime.browser_runtime import (
    playwright_chromium_readiness,
    playwright_optional_html_readiness,
)
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
HTML_EXTENSIONS = {".html", ".htm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_EXTENSIONS = {".pdf"}


async def capture_url(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    """捕获 HTTP(S) 页面的视觉预览。"""

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
    """捕获工作区内本地 HTML 文件的视觉预览。"""

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


async def capture_file(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    """捕获工作区文件的视觉或调试证据。

    这是通用观察入口：将 HTML 委托给浏览器预览路径，把图片记录为视觉证据，
    并在 PyMuPDF 可用时渲染 PDF 页面。它返回结构化诊断，不成为任务路由器。"""

    source_path = context.path_guard.resolve(input_data.get("path"))
    if not source_path.is_file():
        raise ValueError(f"file not found: {source_path}")
    suffix = source_path.suffix.lower()
    if suffix in HTML_EXTENSIONS:
        try:
            result = await capture_local_html(input_data, context)
        except ValueError as exc:
            if "playwright is required" in str(exc).lower():
                return _file_preview_failure(
                    source_path,
                    code="preview_dependency_missing",
                    message=str(exc),
                    dependency="playwright",
                )
            raise
        result["file_preview_type"] = "html"
        result["via_tool"] = "preview.capture_file"
        return result
    if suffix in IMAGE_EXTENSIONS:
        return _capture_image_file(source_path, input_data, context)
    if suffix in PDF_EXTENSIONS:
        return _capture_pdf_file(source_path, input_data, context)
    return _file_preview_failure(
        source_path,
        code="file_preview_unsupported_format",
        message=(
            "preview.capture_file currently supports HTML, common image files, "
            "and PDF page rendering. Use a document-specific read/export tool "
            "or another provider for this file type."
        ),
        severity="info",
    )


async def interact_page(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    """打开页面、执行有界 Playwright 操作并捕获验证证据。"""

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


def _capture_image_file(source_path: Path, input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    artifact_path = source_path
    copied = False
    if input_data.get("output_path") or input_data.get("output_dir"):
        artifact_path = _resolve_file_copy_output_path(
            input_data,
            context,
            default_label=_safe_label(source_path.stem, "image"),
            suffix=source_path.suffix or ".png",
        )
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        if callable(getattr(context, "backup_file", None)) and artifact_path.exists():
            context.backup_file(artifact_path)
        shutil.copyfile(source_path, artifact_path)
        copied = True

    width, height = _read_image_dimensions(source_path)
    format_name = _image_format_name(source_path)
    diagnostics: list[dict[str, Any]] = []
    if width is None or height is None:
        diagnostics.append({
            "code": "image_dimensions_unreadable",
            "severity": "info",
            "message": "Image preview was recorded, but dimensions could not be read without additional image support.",
            "source": "file_preview",
        })
    debug_session = build_debug_session(
        source_type="preview.capture_file",
        command=f"preview image {source_path}",
        executable="filesystem",
        cwd=str(source_path.parent),
        exit_code=0,
        timed_out=False,
        stdout=f"file_type=image; copied={copied}",
        stderr="",
        service={
            "kind": "file_preview",
            "file_type": "image",
            "source_path": str(source_path),
            "artifact_path": str(artifact_path),
        },
        diagnostics=diagnostics,
        started_at=started_at,
        finished_at=_utc_now_iso(),
        duration_seconds=round(max(0.0, time.monotonic() - started_monotonic), 3),
    )
    visual_evidence = build_visual_evidence(
        source_type="image_file",
        source_path=str(source_path),
        screenshot_path=str(artifact_path),
        artifact_kind="image",
        format=format_name,
        size=artifact_path.stat().st_size,
        width=width,
        height=height,
        has_runtime_errors=False,
        provider="filesystem",
    )
    effects = ["artifact_write"] if copied else ["artifact_reference"]
    context.log("info", "file preview captured", {"path": str(source_path), "artifact": str(artifact_path)})
    return {
        "type": "file_preview",
        "file_preview_type": "image",
        "source_type": "image_file",
        "source_path": str(source_path),
        "path": str(artifact_path),
        "format": format_name,
        "size": artifact_path.stat().st_size,
        "width": width,
        "height": height,
        "artifact_kind": "image",
        "artifacts": ["image", "visual_evidence"],
        "effects": effects,
        "roles": ["verification"],
        "verification_strength": "standard",
        "has_runtime_errors": False,
        "runtime_diagnostics": diagnostics,
        "debug_session": debug_session,
        "visual_evidence": visual_evidence,
    }


def _capture_pdf_file(source_path: Path, input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception as exc:
        return _file_preview_failure(
            source_path,
            code="preview_dependency_missing",
            message=(
                "PDF visual preview requires PyMuPDF/fitz. Install the documents "
                "extra or use a document text extraction tool when visual rendering "
                "is unavailable."
            ),
            dependency="fitz",
            detail=str(exc),
        )

    started_at = _utc_now_iso()
    started_monotonic = time.monotonic()
    page_number = max(1, _safe_int(input_data.get("page") or input_data.get("page_number") or 1))
    output_path = _resolve_output_path(
        input_data,
        context,
        default_label=f"{_safe_label(source_path.stem, 'pdf')}-page-{page_number}",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if callable(getattr(context, "backup_file", None)) and output_path.exists():
        context.backup_file(output_path)

    capture_format = _capture_format(input_data.get("format"), output_path)
    zoom = _safe_float(input_data.get("scale") or input_data.get("zoom") or 2.0, default=2.0)
    zoom = max(0.5, min(4.0, zoom))
    diagnostics: list[dict[str, Any]] = []
    doc = fitz.open(str(source_path))
    try:
        page_count = int(getattr(doc, "page_count", 0) or 0)
        if page_count <= 0:
            return _file_preview_failure(
                source_path,
                code="pdf_has_no_pages",
                message="PDF file has no renderable pages.",
            )
        page_index = min(page_number - 1, page_count - 1)
        if page_index != page_number - 1:
            diagnostics.append({
                "code": "pdf_page_clamped",
                "severity": "info",
                "message": f"Requested page {page_number}, rendered last available page {page_index + 1}.",
                "source": "file_preview",
                "page_count": page_count,
            })
        page = doc.load_page(page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pixmap.save(str(output_path))
        width = _safe_int(getattr(pixmap, "width", 0))
        height = _safe_int(getattr(pixmap, "height", 0))
    finally:
        doc.close()

    debug_session = build_debug_session(
        source_type="preview.capture_file",
        command=f"render pdf page {page_number} {source_path}",
        executable="fitz",
        cwd=str(source_path.parent),
        exit_code=0,
        timed_out=False,
        stdout=f"file_type=pdf; page={page_number}; output={output_path.name}",
        stderr="",
        service={
            "kind": "file_preview",
            "file_type": "pdf",
            "source_path": str(source_path),
            "artifact_path": str(output_path),
            "page": page_number,
            "scale": zoom,
        },
        diagnostics=diagnostics,
        started_at=started_at,
        finished_at=_utc_now_iso(),
        duration_seconds=round(max(0.0, time.monotonic() - started_monotonic), 3),
    )
    visual_evidence = build_visual_evidence(
        source_type="pdf_file",
        source_path=str(source_path),
        screenshot_path=str(output_path),
        artifact_kind="render",
        format=capture_format,
        size=output_path.stat().st_size,
        width=width,
        height=height,
        has_runtime_errors=False,
        provider="pymupdf",
    )
    context.log("info", "pdf preview captured", {"path": str(source_path), "artifact": str(output_path)})
    return {
        "type": "file_preview",
        "file_preview_type": "pdf",
        "source_type": "pdf_file",
        "source_path": str(source_path),
        "path": str(output_path),
        "format": capture_format,
        "size": output_path.stat().st_size,
        "width": width,
        "height": height,
        "page": page_number,
        "artifact_kind": "render",
        "artifacts": ["screenshot", "visual_evidence", "pdf_page_render"],
        "effects": ["artifact_write"],
        "roles": ["verification"],
        "verification_strength": "standard",
        "has_runtime_errors": False,
        "runtime_diagnostics": diagnostics,
        "debug_session": debug_session,
        "visual_evidence": visual_evidence,
    }


def _file_preview_failure(
    source_path: Path,
    *,
    code: str,
    message: str,
    severity: str = "error",
    dependency: str = "",
    detail: str = "",
) -> dict[str, Any]:
    diagnostics = [{
        "code": code,
        "severity": severity,
        "message": message[:800],
        "source": "file_preview",
    }]
    if dependency:
        diagnostics[0]["dependency"] = dependency
    if detail:
        diagnostics[0]["detail"] = detail[:500]
    debug_session = build_debug_session(
        source_type="preview.capture_file",
        command=f"preview file {source_path}",
        executable="preview.capture_file",
        cwd=str(source_path.parent),
        exit_code=1,
        timed_out=False,
        stdout=f"file_type={source_path.suffix.lower().lstrip('.') or 'unknown'}",
        stderr=message[:1000],
        service={
            "kind": "file_preview",
            "file_type": source_path.suffix.lower().lstrip(".") or "unknown",
            "source_path": str(source_path),
        },
        diagnostics=diagnostics,
        started_at=_utc_now_iso(),
        finished_at=_utc_now_iso(),
        duration_seconds=0.0,
    )
    return {
        "type": "file_preview",
        "file_preview_type": "unsupported",
        "source_type": "file",
        "source_path": str(source_path),
        "path": "",
        "artifact_kind": "",
        "artifacts": [],
        "effects": [],
        "roles": ["evidence"],
        "verification_strength": "none",
        "status": "unsupported",
        "error": True,
        "has_runtime_errors": True,
        "runtime_diagnostics": diagnostics,
        "debug_session": debug_session,
    }


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
    page_error_details: list[dict[str, str]] = []
    failed_requests: list[dict[str, str]] = []
    resource_responses: list[dict[str, Any]] = []
    dom_snapshot: dict[str, Any] = {}
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
        page.on("pageerror", lambda error: _record_page_error(page_errors, page_error_details, error))
        page.on("requestfailed", lambda request: _record_failed_request(failed_requests, request))
        page.on("response", lambda response: _record_resource_response(resource_responses, response))
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
            title = await page.title()
            dom_snapshot = await _read_dom_snapshot(page)
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
    diagnostics = _build_preview_diagnostics(
        source_type=source_type,
        served_via=served_via,
        console_errors=error_messages,
        page_errors=page_errors,
        page_error_details=page_error_details,
        failed_requests=failed_requests,
        blocking_failed_requests=blocking_failed_requests,
        resource_responses=resource_responses,
        dom_snapshot=dom_snapshot,
    )
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
        diagnostics=diagnostics,
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
        "page_error_details": page_error_details[:20],
        "failed_requests": failed_requests[:20],
        "resource_responses": resource_responses[:40],
        "has_runtime_errors": has_runtime_errors,
        "dom_snapshot": dom_snapshot,
        "runtime_diagnostics": diagnostics,
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
    page_error_details: list[dict[str, str]] = []
    failed_requests: list[dict[str, str]] = []
    resource_responses: list[dict[str, Any]] = []
    action_results: list[dict[str, Any]] = []
    assertion_failures: list[dict[str, Any]] = []
    status_code = 0
    title = ""
    body_text = ""
    dom_snapshot: dict[str, Any] = {}
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
        page.on("pageerror", lambda error: _record_page_error(page_errors, page_error_details, error))
        page.on("requestfailed", lambda request: _record_failed_request(failed_requests, request))
        page.on("response", lambda response: _record_resource_response(resource_responses, response))
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
            dom_snapshot = await _read_dom_snapshot(page)
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
    diagnostics = _build_preview_diagnostics(
        source_type=source_type,
        served_via=served_via,
        console_errors=error_messages,
        page_errors=page_errors,
        page_error_details=page_error_details,
        failed_requests=failed_requests,
        blocking_failed_requests=blocking_failed_requests,
        resource_responses=resource_responses,
        dom_snapshot=dom_snapshot,
        assertion_failures=assertion_failures,
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
        diagnostics=diagnostics,
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
        "page_error_details": page_error_details[:20],
        "failed_requests": failed_requests[:20],
        "resource_responses": resource_responses[:40],
        "has_runtime_errors": has_runtime_errors,
        "dom_snapshot": dom_snapshot,
        "runtime_diagnostics": diagnostics,
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
            result.update(await _click_with_recovery(page, selector, action_timeout_ms))
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


async def _click_with_recovery(page: Any, selector: str, timeout_ms: int) -> dict[str, Any]:
    """点击选择器；当文本选择器解析到子节点时进行恢复。

    Playwright 文本选择器经常定位到真实按钮内部的 span 或图标标签，使原本有效的
    模型操作在浏览器验证中变得脆弱：模型选中了正确可见文本，但可操作元素是祖先节点。
    先执行标准 Playwright 点击，失败后再在 DOM 侧有界点击最近的可见可点击目标。"""

    try:
        await page.locator(selector).click(timeout=timeout_ms)
        return {
            "selector": selector[:300],
            "click_strategy": "locator.click",
        }
    except Exception as first_error:
        fallback = await _click_clickable_dom_target(page, selector)
        if str(fallback.get("reason") or "") == "ambiguous_text_selector":
            candidates = fallback.get("candidates") if isinstance(fallback.get("candidates"), list) else []
            raise RuntimeError(
                f"{str(first_error)[:500]}; selector is ambiguous and matched "
                f"{fallback.get('candidate_count') or len(candidates)} clickable targets. "
                "Use a more specific selector. candidates="
                f"{json.dumps(candidates[:8], ensure_ascii=False)}"
            ) from first_error
        if fallback.get("clicked"):
            return {
                "selector": selector[:300],
                "click_strategy": str(fallback.get("strategy") or "dom_clickable_target")[:80],
                "recovered_from_error": str(first_error)[:500],
                "click_target": {
                    key: fallback.get(key)
                    for key in (
                        "target_tag",
                        "target_role",
                        "target_text",
                        "original_tag",
                        "selector_kind",
                    )
                    if fallback.get(key) not in (None, "")
                },
            }
        reason = str(fallback.get("reason") or "no fallback target").strip()
        raise RuntimeError(
            f"{str(first_error)[:500]}; fallback click failed: {reason[:240]}"
        ) from first_error


async def _click_clickable_dom_target(page: Any, selector: str) -> dict[str, Any]:
    try:
        value = await page.evaluate(_CLICK_FALLBACK_SCRIPT, selector)
    except TypeError:
        return {
            "clicked": False,
            "reason": "page.evaluate does not support selector arguments",
        }
    except Exception as exc:
        return {
            "clicked": False,
            "reason": str(exc)[:500],
        }
    return value if isinstance(value, dict) else {
        "clicked": False,
        "reason": "fallback returned no structured result",
    }


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


_CLICK_FALLBACK_SCRIPT = r"""(selector) => {
  const YUNTAOCODE_PREVIEW_CLICK_FALLBACK = true;
  const rawSelector = String(selector || "").trim();
  const cleanTextSelector = (value) => {
    const raw = String(value || "").trim();
    if (!/^text\s*=/i.test(raw)) return "";
    return raw.replace(/^text\s*=/i, "").trim().replace(/^['"]|['"]$/g, "");
  };
  const textOf = (element) => (element.innerText || element.textContent || "").trim();
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const opacity = Number.parseFloat(style.opacity || "1");
    return style.display !== "none"
      && style.visibility !== "hidden"
      && opacity > 0.01
      && rect.width > 0
      && rect.height > 0;
  };
  const isDisabled = (element) => {
    if (!element) return true;
    return Boolean(element.disabled)
      || String(element.getAttribute("aria-disabled") || "").toLowerCase() === "true";
  };
  const clickableSelector = [
    "button",
    "a[href]",
    "[role='button']",
    "[onclick]",
    "[tabindex]",
    "input",
    "select",
    "textarea",
    "label"
  ].join(",");
  const nearestClickable = (element) => {
    if (!element) return null;
    const candidate = element.closest(clickableSelector) || element;
    if (!isVisible(candidate) || isDisabled(candidate)) return null;
    return candidate;
  };
  const text = cleanTextSelector(rawSelector);
  let candidates = [];
  let selectorKind = "css";
  if (text) {
    selectorKind = "text";
    const clickables = Array.from(document.querySelectorAll(clickableSelector))
      .filter((element) => isVisible(element) && textOf(element).includes(text));
    const textNodes = Array.from(document.querySelectorAll("body *"))
      .filter((element) => isVisible(element) && textOf(element).includes(text));
    candidates = [...clickables, ...textNodes];
  } else {
    try {
      candidates = Array.from(document.querySelectorAll(rawSelector));
    } catch (error) {
      return {
        clicked: false,
        reason: `invalid selector for fallback: ${error.message || error}`,
        selector: rawSelector,
      };
    }
  }
  const clickableTargets = [];
  const seenTargets = new Set();
  for (const element of candidates) {
    const target = nearestClickable(element);
    if (!target || seenTargets.has(target)) continue;
    seenTargets.add(target);
    clickableTargets.push({element, target});
  }
  if (selectorKind === "text" && clickableTargets.length > 1) {
    return {
      clicked: false,
      reason: "ambiguous_text_selector",
      selector: rawSelector,
      text,
      candidate_count: clickableTargets.length,
      candidates: clickableTargets.slice(0, 8).map(({element, target}, index) => ({
        index,
        target_tag: target.tagName ? target.tagName.toLowerCase() : "",
        target_role: target.getAttribute("role") || "",
        target_id: target.id || "",
        target_class: target.className && typeof target.className === "string" ? target.className.slice(0, 120) : "",
        target_text: textOf(target).slice(0, 200),
        original_tag: element.tagName ? element.tagName.toLowerCase() : "",
      })),
    };
  }
  const seen = new Set();
  for (const {element, target} of clickableTargets) {
    if (seen.has(target)) continue;
    seen.add(target);
    try {
      target.scrollIntoView({block: "center", inline: "center"});
      target.click();
      return {
        clicked: true,
        strategy: target === element ? "dom_target_click" : "dom_clickable_ancestor",
        selector_kind: selectorKind,
        original_tag: element.tagName ? element.tagName.toLowerCase() : "",
        target_tag: target.tagName ? target.tagName.toLowerCase() : "",
        target_role: target.getAttribute("role") || "",
        target_text: textOf(target).slice(0, 200),
      };
    } catch (error) {
      return {
        clicked: false,
        reason: `fallback target click failed: ${error.message || error}`,
        selector: rawSelector,
      };
    }
  }
  return {
    clicked: false,
    reason: text ? "no visible clickable text target" : "no visible clickable selector target",
    selector: rawSelector,
    text,
  };
}"""


_DOM_SNAPSHOT_SCRIPT = r"""() => {
  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const opacity = Number.parseFloat(style.opacity || "1");
    return style.display !== "none"
      && style.visibility !== "hidden"
      && opacity > 0.01
      && rect.width > 0
      && rect.height > 0;
  };
  const textOf = (element) => (element.innerText || element.textContent || "").trim();
  const takeTexts = (selector, limit) => Array.from(document.querySelectorAll(selector))
    .filter(isVisible)
    .map(textOf)
    .filter(Boolean)
    .slice(0, limit);
  const loadingSelector = [
    '[id*="loading" i]',
    '[class*="loading" i]',
    '[aria-busy="true"]',
    '[role="progressbar"]',
    '[class*="spinner" i]'
  ].join(",");
  const loadingTexts = takeTexts(loadingSelector, 8);
  const scripts = Array.from(document.scripts).map((script) => ({
    src: script.src || "",
    type: script.type || "",
    inline_chars: script.src ? 0 : (script.textContent || "").length
  })).slice(0, 30);
  const importHosts = [];
  for (const item of Array.from(document.querySelectorAll('script[type="importmap"]'))) {
    try {
      const parsed = JSON.parse(item.textContent || "{}");
      for (const value of Object.values(parsed.imports || {})) {
        if (typeof value !== "string") continue;
        if (!/^https?:\/\//i.test(value)) continue;
        importHosts.push(new URL(value, document.baseURI).host);
      }
    } catch (error) {
      importHosts.push("invalid-importmap");
    }
  }
  const externalHosts = [];
  for (const script of scripts) {
    if (!/^https?:\/\//i.test(script.src)) continue;
    externalHosts.push(new URL(script.src, document.baseURI).host);
  }
  const bodyText = document.body ? textOf(document.body) : "";
  return {
    marker: "YUNTAOCODE_PREVIEW_RUNTIME_SNAPSHOT",
    ready_state: document.readyState,
    title: document.title || "",
    body_text: bodyText.slice(0, 4000),
    body_text_chars: bodyText.length,
    loading_visible: loadingTexts.length > 0,
    loading_texts: loadingTexts,
    headings: takeTexts("h1,h2,h3", 10),
    buttons: takeTexts("button,[role=button]", 20),
    scripts,
    external_resource_hosts: Array.from(new Set([...externalHosts, ...importHosts])).slice(0, 20),
    importmap_hosts: Array.from(new Set(importHosts)).slice(0, 20)
  };
}"""


async def _read_dom_snapshot(page: Any) -> dict[str, Any]:
    try:
        raw = await page.evaluate(_DOM_SNAPSHOT_SCRIPT)
    except Exception as exc:
        return {
            "snapshot_error": str(exc)[:300],
        }
    if not isinstance(raw, dict):
        text = str(raw or "")
        return {
            "body_text": text[:4000],
            "body_text_chars": len(text),
        }
    return {
        "ready_state": str(raw.get("ready_state") or "")[:40],
        "title": str(raw.get("title") or "")[:200],
        "body_text": str(raw.get("body_text") or "")[:4000],
        "body_text_chars": _safe_int(raw.get("body_text_chars")),
        "loading_visible": bool(raw.get("loading_visible")),
        "loading_texts": _string_list(raw.get("loading_texts"), limit=8, item_limit=300),
        "headings": _string_list(raw.get("headings"), limit=10, item_limit=300),
        "buttons": _string_list(raw.get("buttons"), limit=20, item_limit=200),
        "scripts": _script_list(raw.get("scripts")),
        "external_resource_hosts": _string_list(raw.get("external_resource_hosts"), limit=20, item_limit=120),
        "importmap_hosts": _string_list(raw.get("importmap_hosts"), limit=20, item_limit=120),
    }


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


def _resolve_file_copy_output_path(
    input_data: dict[str, Any],
    context: Any,
    *,
    default_label: str,
    suffix: str,
) -> Path:
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    raw_output = str(input_data.get("output_path") or "").strip()
    if raw_output:
        if _is_task_temp_path(raw_output):
            path = _resolve_task_temp_file_with_suffix(
                context,
                raw_output,
                default_label,
                normalized_suffix,
            )
        else:
            path = context.path_guard.resolve(raw_output)
        return path if path.suffix else path.with_suffix(normalized_suffix)

    raw_output_dir = str(input_data.get("output_dir") or "").strip()
    filename = f"{default_label}{normalized_suffix}"
    if not raw_output_dir or raw_output_dir in TASK_TEMP_ALIASES:
        return _task_temp_root(context) / "preview" / filename
    return context.path_guard.resolve(raw_output_dir) / filename


def _resolve_task_temp_file_with_suffix(
    context: Any,
    raw_output: str,
    default_label: str,
    suffix: str,
) -> Path:
    temp_root = _task_temp_root(context)
    value = raw_output.strip().replace("\\", "/")
    for alias in ("task_temp/", "__task_temp__/", "$TASK_TEMP/", "{task_temp}/"):
        if value.startswith(alias):
            value = value[len(alias):]
            break
    if not value or value in TASK_TEMP_ALIASES:
        value = f"preview/{default_label}{suffix}"
    path = (temp_root / value).resolve()
    if temp_root not in path.parents and path != temp_root:
        raise ValueError("output_path escapes task_temp")
    if not path.suffix:
        path = path.with_suffix(suffix)
    return path


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


def _image_format_name(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "jpg":
        return "jpeg"
    return suffix or "image"


def _read_image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(path) as image:
            width, height = image.size
            return int(width), int(height)
    except Exception:
        pass
    try:
        return _read_image_dimensions_stdlib(path)
    except Exception:
        return None, None


def _read_image_dimensions_stdlib(path: Path) -> tuple[int | None, int | None]:
    suffix = path.suffix.lower()
    with path.open("rb") as handle:
        header = handle.read(32)
        if suffix == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
        if suffix == ".gif" and header[:6] in {b"GIF87a", b"GIF89a"} and len(header) >= 10:
            return int.from_bytes(header[6:8], "little"), int.from_bytes(header[8:10], "little")
        if suffix in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8"):
            return _read_jpeg_dimensions(handle)
    return None, None


def _read_jpeg_dimensions(handle: Any) -> tuple[int | None, int | None]:
    handle.seek(2)
    while True:
        marker_prefix = handle.read(1)
        if not marker_prefix:
            return None, None
        if marker_prefix != b"\xff":
            continue
        marker = handle.read(1)
        while marker == b"\xff":
            marker = handle.read(1)
        if not marker or marker in {b"\xd8", b"\xd9"}:
            continue
        length_bytes = handle.read(2)
        if len(length_bytes) != 2:
            return None, None
        length = int.from_bytes(length_bytes, "big")
        if length < 2:
            return None, None
        if marker[0] in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            data = handle.read(5)
            if len(data) != 5:
                return None, None
            return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
        handle.seek(length - 2, 1)


def _record_console(target: list[dict[str, str]], message: Any) -> None:
    target.append({
        "type": str(_read_attr(message, "type") or ""),
        "text": str(_read_attr(message, "text") or "")[:500],
    })


def _record_page_error(
    messages: list[str],
    details: list[dict[str, str]],
    error: Any,
) -> None:
    message = str(error or "")[:500]
    messages.append(message)
    name = str(_read_attr(error, "name") or "")[:120]
    stack = str(_read_attr(error, "stack") or "")[:2000]
    details.append({
        "name": name,
        "message": message,
        "stack": stack,
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
        "resource_type": str(_read_attr(request, "resource_type") or "")[:80],
        "error": error_text[:500],
    })


def _record_resource_response(target: list[dict[str, Any]], response: Any) -> None:
    if len(target) >= 80:
        return
    request = _read_attr(response, "request")
    resource_type = str(_read_attr(request, "resource_type") or "").strip().lower()
    url = str(_read_attr(response, "url") or _read_attr(request, "url") or "").strip()
    if not _resource_response_is_relevant(url, resource_type):
        return
    headers = _read_attr(response, "headers")
    if not isinstance(headers, dict):
        headers = {}
    normalized_headers = {str(k).lower(): str(v) for k, v in headers.items()}
    try:
        status = int(_read_attr(response, "status") or 0)
    except (TypeError, ValueError):
        status = 0
    target.append({
        "url": url[:500],
        "status": status,
        "method": str(_read_attr(request, "method") or "")[:40],
        "resource_type": resource_type[:80],
        "content_type": normalized_headers.get("content-type", "")[:160],
        "content_length": normalized_headers.get("content-length", "")[:40],
        "remote": bool(re.match(r"^https?://", url, flags=re.IGNORECASE)),
    })


def _resource_response_is_relevant(url: str, resource_type: str) -> bool:
    if resource_type in {"document", "script", "stylesheet", "fetch", "xhr"}:
        return True
    lower = str(url or "").lower().split("?", 1)[0]
    return lower.endswith((".html", ".htm", ".js", ".mjs", ".css", ".json", ".wasm"))


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


def _build_preview_diagnostics(
    *,
    source_type: str,
    served_via: str,
    console_errors: list[dict[str, str]],
    page_errors: list[str],
    page_error_details: list[dict[str, str]],
    failed_requests: list[dict[str, str]],
    blocking_failed_requests: list[dict[str, str]],
    resource_responses: list[dict[str, Any]],
    dom_snapshot: dict[str, Any],
    assertion_failures: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for item in console_errors[:5]:
        text = str(item.get("text") or "").strip()
        diagnostics.append({
            "code": "browser_console_error",
            "severity": "error",
            "message": text[:500] or "Browser console error",
            "source": "console",
            "type": item.get("type") or "error",
        })
    for index, message in enumerate(page_errors[:5]):
        detail = page_error_details[index] if index < len(page_error_details) else {}
        diagnostics.append({
            "code": "browser_page_error",
            "severity": "error",
            "message": str(message or "Browser page error")[:500],
            "source": "pageerror",
            "name": detail.get("name") or "",
            "stack_preview": str(detail.get("stack") or "")[:800],
        })
    blocking_ids = {id(item) for item in blocking_failed_requests}
    for item in failed_requests[:10]:
        blocking = id(item) in blocking_ids or _failed_request_is_blocking(item)
        diagnostics.append({
            "code": "browser_request_failed" if blocking else "browser_request_failed_nonblocking",
            "severity": "error" if blocking else "info",
            "message": _failed_request_message(item, blocking=blocking),
            "source": "requestfailed",
            "url": item.get("url") or "",
            "method": item.get("method") or "",
            "resource_type": item.get("resource_type") or "",
            "error": item.get("error") or "",
            "blocking": blocking,
        })
    for item in resource_responses[:20]:
        status = _safe_int(item.get("status"))
        if status >= 400:
            diagnostics.append({
                "code": "browser_resource_http_error",
                "severity": "error",
                "message": f"Resource responded HTTP {status}: {_resource_tail(item)}",
                "source": "response",
                "url": item.get("url") or "",
                "status": status,
                "resource_type": item.get("resource_type") or "",
                "content_type": item.get("content_type") or "",
            })
            continue
        if _script_response_content_type_suspicious(item):
            diagnostics.append({
                "code": "browser_script_response_type_suspicious",
                "severity": "warning",
                "message": f"Script-like resource has suspicious content-type: {_resource_tail(item)}",
                "source": "response",
                "url": item.get("url") or "",
                "status": status,
                "resource_type": item.get("resource_type") or "",
                "content_type": item.get("content_type") or "",
            })
    if _has_unexpected_end_of_input(page_errors):
        script_candidates = _script_response_candidates(resource_responses)
        if script_candidates:
            diagnostics.append({
                "code": "script_parse_error_resource_candidates",
                "severity": "info",
                "message": "A JavaScript parse error was observed; these script/module responses were loaded near the failure.",
                "source": "response",
                "resources": script_candidates[:10],
            })
    for item in (assertion_failures or [])[:10]:
        diagnostics.append({
            "code": "preview_assertion_failed",
            "severity": "error",
            "message": str(item.get("message") or item.get("error") or "Preview assertion failed")[:500],
            "source": "interaction",
            "action_index": item.get("index"),
            "action": item.get("action"),
        })
    if dom_snapshot.get("loading_visible"):
        diagnostics.append({
            "code": "page_loading_state_visible",
            "severity": "warning",
            "message": "Page still shows visible loading/progress UI after capture.",
            "source": "dom_snapshot",
            "loading_texts": dom_snapshot.get("loading_texts") or [],
        })
    ready_state = str(dom_snapshot.get("ready_state") or "").strip()
    if ready_state and ready_state != "complete":
        diagnostics.append({
            "code": "document_not_complete",
            "severity": "warning",
            "message": f"document.readyState is {ready_state}.",
            "source": "dom_snapshot",
            "ready_state": ready_state,
        })
    if _safe_int(dom_snapshot.get("body_text_chars")) == 0:
        diagnostics.append({
            "code": "empty_body_text",
            "severity": "warning",
            "message": "Document body text is empty or not readable after capture.",
            "source": "dom_snapshot",
        })
    if source_type == "local_html" and served_via in {"localhost", "file"}:
        hosts = dom_snapshot.get("external_resource_hosts") or []
        if hosts:
            diagnostics.append({
                "code": "local_html_remote_dependencies",
                "severity": "info",
                "message": "Local HTML depends on remote scripts or import maps; preview may fail when network/CDN responses are unavailable or invalid.",
                "source": "dom_snapshot",
                "hosts": hosts[:10],
            })
    return diagnostics[:20]


def _resource_tail(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "")
    return url.rsplit("/", 1)[-1][:160] if url else "resource"


def _script_response_content_type_suspicious(item: dict[str, Any]) -> bool:
    resource_type = str(item.get("resource_type") or "").strip().lower()
    url = str(item.get("url") or "").strip().lower().split("?", 1)[0]
    if resource_type != "script" and not url.endswith((".js", ".mjs")):
        return False
    content_type = str(item.get("content_type") or "").strip().lower()
    if not content_type:
        return False
    allowed = (
        "javascript",
        "ecmascript",
        "text/plain",
        "application/octet-stream",
    )
    return not any(part in content_type for part in allowed)


def _has_unexpected_end_of_input(page_errors: list[str]) -> bool:
    return any("unexpected end of input" in str(item or "").lower() for item in page_errors)


def _script_response_candidates(resource_responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in resource_responses:
        resource_type = str(item.get("resource_type") or "").strip().lower()
        url = str(item.get("url") or "").strip().lower().split("?", 1)[0]
        if resource_type != "script" and not url.endswith((".js", ".mjs")):
            continue
        result.append({
            "url": item.get("url") or "",
            "status": item.get("status"),
            "content_type": item.get("content_type") or "",
            "content_length": item.get("content_length") or "",
            "remote": bool(item.get("remote")),
        })
    return result[:20]


def _failed_request_message(item: dict[str, str], *, blocking: bool) -> str:
    url = str(item.get("url") or "")
    tail = url.rsplit("/", 1)[-1] if url else "request"
    error = str(item.get("error") or "").strip()
    label = "Blocking request failed" if blocking else "Non-blocking request failed"
    return f"{label}: {tail}{f' ({error})' if error else ''}"[:500]


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text[:item_limit])
        if len(result) >= limit:
            break
    return result


def _script_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        result.append({
            "src": str(item.get("src") or "")[:500],
            "type": str(item.get("type") or "")[:80],
            "inline_chars": _safe_int(item.get("inline_chars")),
        })
        if len(result) >= 30:
            break
    return result


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
    resource_type = str(item.get("resource_type") or "").strip().lower()
    if resource_type in {"media", "video", "audio"} and error == "net::err_aborted":
        return False
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
            readiness_probe=playwright_chromium_readiness,
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
            readiness_probe=playwright_chromium_readiness,
        ),
        capture_local_html,
    )
    registry.register(
        ToolSpec(
            id="preview.capture_file",
            name="文件视觉预览",
            description=(
                "对工作区内文件生成或登记统一视觉观察证据。HTML 复用浏览器预览，图片登记为 "
                "visual_evidence，PDF 在 PyMuPDF 可用时渲染指定页截图；不支持或缺依赖时返回结构化诊断。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "工作区内要预览的文件路径"},
                    "page": {"type": "integer", "default": 1, "description": "PDF 页码，1 开始"},
                    "output_path": {"type": "string", "description": "可选输出路径；默认写入 task_temp/preview"},
                    "output_dir": {"type": "string", "description": "可选输出目录；传 task_temp 使用任务临时目录"},
                    "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                    "scale": {"type": "number", "default": 2.0, "description": "PDF 渲染缩放，0.5 到 4.0"},
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
            capability="preview.visual_debug",
            artifacts=["screenshot", "image", "visual_evidence", "pdf_page_render"],
            effects=["artifact_write", "artifact_reference"],
            roles=["verification"],
            verification_strength="standard",
            retry_safe=True,
            readiness_probe=playwright_optional_html_readiness,
        ),
        capture_file,
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
            readiness_probe=playwright_chromium_readiness,
        ),
        interact_page,
    )
