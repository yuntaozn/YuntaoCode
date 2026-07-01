from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.security import PathGuard
from runtime.skills.preview import (
    _failed_request_is_blocking,
    capture_local_html,
    capture_url,
    interact_page,
    register_preview_tools,
)
from runtime.tool_registry import ToolRegistry


GOTO_URLS: list[str] = []
EMIT_CONSOLE_ERROR = True


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

    async def evaluate(self, script: str) -> str:
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
        self.page.actions.append(("click", self.selector, ""))

    async def fill(self, value: str, **kwargs) -> None:
        self.page.actions.append(("fill", self.selector, value))

    async def press(self, key: str, **kwargs) -> None:
        self.page.actions.append(("press", self.selector, key))

    async def inner_text(self, **kwargs) -> str:
        return self.page.body_text


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
    assert result["debug_session"]["kind"] == "debug_session"
    assert result["debug_session"]["source"]["type"] == "preview.capture_page"
    assert result["debug_session"]["service"]["kind"] == "browser_preview"
    assert result["debug_session"]["service"]["served_via"] == "localhost"
    assert result["debug_session"]["process"]["exit_code"] == 1
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


def test_register_preview_tools() -> None:
    registry = ToolRegistry()
    register_preview_tools(registry)

    ids = {item["id"] for item in registry.list_specs()}
    local_spec = registry.get_public_spec("preview.capture_local_html")

    assert ids == {
        "preview.capture_url",
        "preview.capture_local_html",
        "preview.interact_page",
    }
    assert local_spec["capability"] == "preview.visual_debug"
    assert local_spec["artifacts"] == ["screenshot", "visual_evidence"]
    assert local_spec["effects"] == ["artifact_write"]
    assert local_spec["roles"] == ["verification"]
    assert local_spec["verification_strength"] == "standard"
    assert local_spec["requires_confirmation"] is False
    assert "serve_mode" in local_spec["input_schema"]["properties"]
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
