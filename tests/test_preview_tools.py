from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.security import PathGuard
from runtime.skills.preview import (
    _build_preview_diagnostics,
    _failed_request_is_blocking,
    capture_file,
    capture_local_html,
    capture_url,
    interact_page,
    register_preview_tools,
)
from runtime.tool_registry import ToolRegistry


GOTO_URLS: list[str] = []
EMIT_CONSOLE_ERROR = True
FAIL_CLICK_SELECTORS: set[str] = set()


@dataclass
class _Context:
    path_guard: PathGuard
    temp_dir: Path

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        return None


class _FakePage:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.actions: list[tuple[str, str, str]] = []
        self.body_text = "Demo Page\n开始学习\n答题完成后显示反馈"
        self.keyboard = _FakeKeyboard(self)

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler

    async def goto(self, url: str, **kwargs):
        GOTO_URLS.append(url)
        response_handler = self.handlers.get("response")
        if callable(response_handler):
            response_handler(_FakeResponse(url, "document", "text/html; charset=utf-8"))
            response_handler(_FakeResponse(
                "https://cdn.jsdelivr.net/npm/three@0.166.0/build/three.module.js",
                "script",
                "application/javascript; charset=utf-8",
                content_length="12345",
            ))
        handler = self.handlers.get("console")
        if EMIT_CONSOLE_ERROR and callable(handler):
            handler(SimpleNamespace(type="error", text="ReferenceError: demo is not defined"))
        return SimpleNamespace(status=200)

    async def title(self) -> str:
        return "Demo Page"

    async def screenshot(self, *, path: str, full_page: bool, type: str) -> None:
        Path(path).write_bytes(b"fake screenshot")

    def locator(self, selector: str):
        return _FakeLocator(self, selector)

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.actions.append(("wait", "", str(milliseconds)))

    async def wait_for_selector(self, selector: str, **kwargs) -> None:
        self.actions.append(("wait_for_selector", selector, ""))

    async def evaluate(self, script: str, *args) -> str | dict:
        if "YUNTAOCODE_PREVIEW_CLICK_FALLBACK" in script:
            selector = str(args[0] if args else "")
            self.actions.append(("click_fallback", selector, "button"))
            return {
                "clicked": True,
                "strategy": "dom_clickable_ancestor",
                "selector_kind": "text" if selector.lower().startswith("text=") else "css",
                "original_tag": "span",
                "target_tag": "button",
                "target_role": "",
                "target_text": "开始学习",
            }
        if "YUNTAOCODE_PREVIEW_RUNTIME_SNAPSHOT" in script:
            return {
                "ready_state": "complete",
                "title": "Demo Page",
                "body_text": self.body_text,
                "body_text_chars": len(self.body_text),
                "loading_visible": True,
                "loading_texts": ["正在初始化场景..."],
                "headings": ["Demo Page"],
                "buttons": ["开始学习"],
                "scripts": [
                    {
                        "src": "https://cdn.jsdelivr.net/npm/three@0.166.0/build/three.module.js",
                        "type": "module",
                        "inline_chars": 0,
                    }
                ],
                "external_resource_hosts": ["cdn.jsdelivr.net"],
                "importmap_hosts": ["cdn.jsdelivr.net"],
            }
        return self.body_text


class _FakeKeyboard:
    def __init__(self, page: _FakePage) -> None:
        self.page = page

    async def press(self, key: str) -> None:
        self.page.actions.append(("press", "", key))


class _FakeLocator:
    def __init__(self, page: _FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    async def click(self, **kwargs) -> None:
        if self.selector in FAIL_CLICK_SELECTORS:
            raise RuntimeError(
                "Locator.click: Timeout 5000ms exceeded.\n"
                f"  - waiting for locator(\"{self.selector}\")\n"
                "    - locator resolved to <span>开始学习</span>\n"
            )
        self.page.actions.append(("click", self.selector, ""))

    async def fill(self, value: str, **kwargs) -> None:
        self.page.actions.append(("fill", self.selector, value))

    async def press(self, key: str, **kwargs) -> None:
        self.page.actions.append(("press", self.selector, key))

    async def inner_text(self, **kwargs) -> str:
        return self.page.body_text


class _FakeResponse:
    def __init__(
        self,
        url: str,
        resource_type: str,
        content_type: str,
        *,
        status: int = 200,
        content_length: str = "",
    ) -> None:
        self.url = url
        self.status = status
        self.headers = {"content-type": content_type}
        if content_length:
            self.headers["content-length"] = content_length
        self.request = SimpleNamespace(
            url=url,
            method="GET",
            resource_type=resource_type,
        )


class _FakeBrowser:
    async def new_page(self, **kwargs):
        return _FakePage()

    async def close(self) -> None:
        return None


class _FakeChromium:
    async def launch(self, **kwargs):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakePlaywrightManager:
    async def __aenter__(self):
        return _FakePlaywright()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_capture_local_html_writes_screenshot_to_task_temp_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    temp_dir = tmp_path / "task-temp"
    workspace.mkdir()
    temp_dir.mkdir()
    (workspace / "viewer.html").write_text("<html><title>Demo</title></html>", encoding="utf-8")
    GOTO_URLS.clear()
    monkeypatch.setattr("runtime.skills.preview._async_playwright", lambda: _FakePlaywrightManager())

    result = await capture_local_html(
        {"path": "viewer.html", "width": 800, "height": 600},
        _Context(PathGuard([workspace]), temp_dir),
    )

    output_path = Path(result["path"])
    assert result["type"] == "preview_capture"
    assert result["source_type"] == "local_html"
    assert result["served_via"] == "localhost"
    assert result["served_root"] == str(workspace.resolve())
    assert result["url"].startswith("http://127.0.0.1:")
    assert result["url"].endswith("/viewer.html")
    assert GOTO_URLS == [result["url"]]
    assert result["artifact_kind"] == "screenshot"
    assert result["artifacts"] == ["screenshot", "visual_evidence"]
    assert result["effects"] == ["artifact_write"]
    assert result["roles"] == ["verification"]
    assert result["verification_strength"] == "standard"
    assert result["has_runtime_errors"] is True
    assert result["console_errors"][0]["text"].startswith("ReferenceError")
    assert result["visual_evidence"]["kind"] == "visual_evidence"
    assert result["visual_evidence"]["source"]["type"] == "local_html"
    assert result["visual_evidence"]["artifact"]["path"] == result["path"]
    assert result["visual_evidence"]["artifact"]["width"] == 800
    assert result["visual_evidence"]["artifact"]["height"] == 600
    assert result["visual_evidence"]["runtime"]["has_errors"] is True
    assert result["visual_evidence"]["model_context"]["eligible"] is True
    assert result["resource_responses"][0]["resource_type"] == "document"
    assert any(item["resource_type"] == "script" for item in result["resource_responses"])
    assert result["dom_snapshot"]["loading_visible"] is True
    assert result["dom_snapshot"]["external_resource_hosts"] == ["cdn.jsdelivr.net"]
    assert result["runtime_diagnostics"]
    assert any(item["code"] == "browser_console_error" for item in result["runtime_diagnostics"])
    assert any(item["code"] == "page_loading_state_visible" for item in result["runtime_diagnostics"])
    assert any(item["code"] == "local_html_remote_dependencies" for item in result["runtime_diagnostics"])
    assert result["debug_session"]["kind"] == "debug_session"
    assert result["debug_session"]["source"]["type"] == "preview.capture_page"
    assert result["debug_session"]["service"]["kind"] == "browser_preview"
    assert result["debug_session"]["service"]["served_via"] == "localhost"
    assert result["debug_session"]["process"]["exit_code"] == 1
    assert result["debug_session"]["diagnostics"]
    assert result["debug_session"]["health"]["status"] == "failed"
    assert output_path.exists()
    assert temp_dir.resolve() in output_path.resolve().parents


@pytest.mark.asyncio
async def test_capture_url_accepts_task_temp_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    temp_dir = tmp_path / "task-temp"
    workspace.mkdir()
    temp_dir.mkdir()
    monkeypatch.setattr("runtime.skills.preview._async_playwright", lambda: _FakePlaywrightManager())

    result = await capture_url(
        {"url": "http://127.0.0.1:8765", "output_path": "task_temp/checks/page.png"},
        _Context(PathGuard([workspace]), temp_dir),
    )

    assert Path(result["path"]) == (temp_dir / "checks" / "page.png").resolve()
    assert Path(result["path"]).exists()
    assert result["url"] == "http://127.0.0.1:8765"


@pytest.mark.asyncio
async def test_capture_file_records_image_visual_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    temp_dir = tmp_path / "task-temp"
    workspace.mkdir()
    temp_dir.mkdir()
    png_header = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\r"
        b"IHDR"
        + (320).to_bytes(4, "big")
        + (180).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    (workspace / "preview.png").write_bytes(png_header)

    result = await capture_file(
        {"path": "preview.png"},
        _Context(PathGuard([workspace]), temp_dir),
    )

    assert result["type"] == "file_preview"
    assert result["file_preview_type"] == "image"
    assert result["source_type"] == "image_file"
    assert result["source_path"] == str((workspace / "preview.png").resolve())
    assert result["path"] == result["source_path"]
    assert result["width"] == 320
    assert result["height"] == 180
    assert result["artifact_kind"] == "image"
    assert result["effects"] == ["artifact_reference"]
    assert result["roles"] == ["verification"]
    assert result["verification_strength"] == "standard"
    assert result["visual_evidence"]["source"]["type"] == "image_file"
    assert result["visual_evidence"]["artifact"]["path"] == result["path"]
    assert result["visual_evidence"]["model_context"]["eligible"] is True
    assert result["debug_session"]["source"]["type"] == "preview.capture_file"
    assert result["debug_session"]["service"]["file_type"] == "image"


@pytest.mark.asyncio
async def test_capture_file_dispatches_html_to_browser_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    temp_dir = tmp_path / "task-temp"
    workspace.mkdir()
    temp_dir.mkdir()
    (workspace / "viewer.html").write_text("<html><title>Demo</title></html>", encoding="utf-8")
    monkeypatch.setattr("runtime.skills.preview._async_playwright", lambda: _FakePlaywrightManager())

    result = await capture_file(
        {"path": "viewer.html"},
        _Context(PathGuard([workspace]), temp_dir),
    )

    assert result["type"] == "preview_capture"
    assert result["file_preview_type"] == "html"
    assert result["via_tool"] == "preview.capture_file"
    assert result["source_type"] == "local_html"
    assert result["visual_evidence"]["source"]["type"] == "local_html"
    assert Path(result["path"]).exists()


@pytest.mark.asyncio
async def test_capture_file_returns_structured_diagnostic_for_unsupported_file(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    temp_dir = tmp_path / "task-temp"
    workspace.mkdir()
    temp_dir.mkdir()
    (workspace / "deck.pptx").write_bytes(b"not a real deck")

    result = await capture_file(
        {"path": "deck.pptx"},
        _Context(PathGuard([workspace]), temp_dir),
    )

    assert result["type"] == "file_preview"
    assert result["status"] == "unsupported"
    assert result["error"] is True
    assert result["verification_strength"] == "none"
    assert result["runtime_diagnostics"][0]["code"] == "file_preview_unsupported_format"
    assert result["debug_session"]["health"]["status"] == "failed"


@pytest.mark.asyncio
async def test_interact_page_runs_actions_and_returns_behavioral_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global EMIT_CONSOLE_ERROR
    workspace = tmp_path / "workspace"
    temp_dir = tmp_path / "task-temp"
    workspace.mkdir()
    temp_dir.mkdir()
    (workspace / "viewer.html").write_text("<html><title>Demo</title><body>开始学习</body></html>", encoding="utf-8")
    GOTO_URLS.clear()
    monkeypatch.setattr("runtime.skills.preview._async_playwright", lambda: _FakePlaywrightManager())
    EMIT_CONSOLE_ERROR = False
    try:
        result = await interact_page(
            {
                "path": "viewer.html",
                "output_path": "task_temp/checks/after.png",
                "actions": [
                    {"action": "click", "selector": "text=开始学习"},
                    {"action": "assert_text", "text": "答题完成后显示反馈"},
                ],
            },
            _Context(PathGuard([workspace]), temp_dir),
        )
    finally:
        EMIT_CONSOLE_ERROR = True

    assert result["type"] == "preview_interaction"
    assert result["source_type"] == "local_html"
    assert result["artifacts"] == [
        "screenshot",
        "visual_evidence",
        "interaction_trace",
        "dom_text",
    ]
    assert result["interaction"]["action_count"] == 2
    assert result["interaction"]["assertion_failed_count"] == 0
    assert result["interaction"]["actions"][0]["action"] == "click"
    assert result["text_chars"] > 0
    assert "答题完成后显示反馈" in result["text"]
    assert result["has_runtime_errors"] is False
    assert result["verification_strength"] == "standard"
    assert result["debug_session"]["source"]["type"] == "preview.interact_page"
    assert result["debug_session"]["service"]["kind"] == "browser_interaction"
    assert result["visual_evidence"]["model_context"]["eligible"] is True
    assert Path(result["path"]).exists()


@pytest.mark.asyncio
async def test_interact_page_recovers_text_click_to_clickable_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global EMIT_CONSOLE_ERROR
    workspace = tmp_path / "workspace"
    temp_dir = tmp_path / "task-temp"
    workspace.mkdir()
    temp_dir.mkdir()
    (workspace / "viewer.html").write_text(
        "<html><title>Demo</title><body><button><span>开始学习</span></button></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr("runtime.skills.preview._async_playwright", lambda: _FakePlaywrightManager())
    FAIL_CLICK_SELECTORS.add("text=开始学习")
    EMIT_CONSOLE_ERROR = False
    try:
        result = await interact_page(
            {
                "path": "viewer.html",
                "actions": [
                    {"action": "click", "selector": "text=开始学习"},
                    {"action": "assert_text", "text": "答题完成后显示反馈"},
                ],
            },
            _Context(PathGuard([workspace]), temp_dir),
        )
    finally:
        FAIL_CLICK_SELECTORS.clear()
        EMIT_CONSOLE_ERROR = True

    first_action = result["interaction"]["actions"][0]
    assert first_action["ok"] is True
    assert first_action["click_strategy"] == "dom_clickable_ancestor"
    assert "Locator.click: Timeout" in first_action["recovered_from_error"]
    assert first_action["click_target"]["target_tag"] == "button"
    assert result["interaction"]["assertion_failed_count"] == 0
    assert result["verification_strength"] == "standard"


def test_register_preview_tools() -> None:
    registry = ToolRegistry()
    register_preview_tools(registry)

    ids = {item["id"] for item in registry.list_specs()}
    local_spec = registry.get_public_spec("preview.capture_local_html")

    assert ids == {
        "preview.capture_url",
        "preview.capture_local_html",
        "preview.capture_file",
        "preview.interact_page",
    }
    assert local_spec["capability"] == "preview.visual_debug"
    assert local_spec["artifacts"] == ["screenshot", "visual_evidence"]
    assert local_spec["effects"] == ["artifact_write"]
    assert local_spec["roles"] == ["verification"]
    assert local_spec["verification_strength"] == "standard"
    assert local_spec["requires_confirmation"] is False
    assert "serve_mode" in local_spec["input_schema"]["properties"]
    file_spec = registry.get_public_spec("preview.capture_file")
    assert file_spec["capability"] == "preview.visual_debug"
    assert file_spec["artifacts"] == [
        "screenshot",
        "image",
        "visual_evidence",
        "pdf_page_render",
    ]
    assert file_spec["effects"] == ["artifact_write", "artifact_reference"]
    assert file_spec["roles"] == ["verification"]
    assert file_spec["verification_strength"] == "standard"
    assert file_spec["requires_confirmation"] is False
    interaction_spec = registry.get_public_spec("preview.interact_page")
    assert interaction_spec["requires_confirmation"] is False
    assert interaction_spec["artifacts"] == [
        "screenshot",
        "visual_evidence",
        "interaction_trace",
        "dom_text",
    ]
    assert "actions" in interaction_spec["input_schema"]["properties"]


def test_media_preload_abort_is_not_blocking_preview_failure() -> None:
    assert not _failed_request_is_blocking({
        "url": "http://127.0.0.1:51234/assets/demo.mp4",
        "method": "GET",
        "error": "net::ERR_ABORTED",
    })
    assert _failed_request_is_blocking({
        "url": "http://127.0.0.1:51234/src/app.js",
        "method": "GET",
        "error": "net::ERR_FAILED",
    })


def test_preview_diagnostics_include_script_candidates_for_parse_error() -> None:
    diagnostics = _build_preview_diagnostics(
        source_type="local_html",
        served_via="localhost",
        console_errors=[],
        page_errors=["Unexpected end of input"],
        page_error_details=[{"name": "SyntaxError", "message": "Unexpected end of input"}],
        failed_requests=[],
        blocking_failed_requests=[],
        resource_responses=[
            {
                "url": "https://cdn.example/three.module.js",
                "status": 200,
                "resource_type": "script",
                "content_type": "application/javascript",
                "content_length": "12345",
                "remote": True,
            }
        ],
        dom_snapshot={
            "loading_visible": True,
            "loading_texts": ["正在初始化场景..."],
            "external_resource_hosts": ["cdn.example"],
        },
    )

    assert any(item["code"] == "browser_page_error" for item in diagnostics)
    candidates = [
        item for item in diagnostics
        if item["code"] == "script_parse_error_resource_candidates"
    ]
    assert candidates
    assert candidates[0]["resources"][0]["url"] == "https://cdn.example/three.module.js"
