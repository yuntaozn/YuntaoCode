"""验证统一模型表单与原有 Settings API 的往返行为。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from tornado.httpserver import HTTPServer
from tornado.netutil import bind_sockets
from tornado.web import Application

from runtime.api.panel import PanelHandler
from runtime.api.settings import SettingsHandler
from runtime.settings_store import SettingsStore


async def test_model_form_creates_and_reuses_a_connection(tmp_path):
    playwright = pytest.importorskip("playwright.async_api")
    panel = Path(__file__).resolve().parents[1] / "runtime" / "panel"
    store = SettingsStore(tmp_path / "settings.json")
    app = Application([
        (r"/settings-page", PanelHandler, {"template_name": "settings.html"}),
        (r"/settings", SettingsHandler, {"runtime": SimpleNamespace(settings=store)}),
    ], template_path=str(panel / "templates"), static_path=str(panel / "static"))

    async with playwright.async_playwright() as driver:
        chromium = driver.chromium.executable_path
        if not Path(chromium).is_file():
            pytest.skip("Chromium is unavailable")
        browser = await driver.chromium.launch(executable_path=chromium)
        server = HTTPServer(app)
        sockets = bind_sockets(0, address="127.0.0.1")
        server.add_sockets(sockets)
        try:
            page = await browser.new_page()
            await page.goto(f"http://127.0.0.1:{sockets[0].getsockname()[1]}/settings-page")
            await page.locator(".model-item").first.wait_for()
            form = page.locator("#model-form")
            await page.locator("#add-model-btn").click()
            await form.locator("[name=api_model]").fill("test-model")
            await form.locator("[name=address]").fill("https://fixture.invalid/custom/responses")
            await form.locator("[name=api_key]").fill("test-only-key")
            await form.locator("[name=make_default]").check()
            await form.locator("[type=submit]").click()
            await form.wait_for(state="hidden")

            _, provider, provider_id = store.resolve_model("test-model")
            assert store.get_default_model() == "test-model"
            assert provider["base_url"] == "https://fixture.invalid/custom"
            assert provider["chat_path"] == "/responses"
            assert provider["wire_api"] == "responses"
            assert "api_key" not in store.public()["providers"][provider_id]

            await page.locator("#add-model-btn").click()
            await form.locator("[name=api_model]").fill("second")
            await form.locator("[name=provider]").select_option(provider_id)
            assert await form.locator("[name=api_key]").input_value() == ""
            await form.locator("[type=submit]").click()
            await form.wait_for(state="hidden")

            # 旧模型的协议参数没有对应的表单控件，编辑时也应保留。
            models = store.get_models()
            second = next(model for model in models if model["id"] == "second")
            second["text_tool_protocol"] = "tagged"
            store.update({"models": models})
            await page.reload()
            await page.locator('[data-edit-model="second"]').click()
            await form.locator("[name=api_model]").fill("renamed")
            await form.locator("[type=submit]").click()
            await form.wait_for(state="hidden")

            model, shared, connection = SettingsStore(store.settings_path).resolve_model("second")
            assert connection == provider_id
            assert shared["api_key"] == "test-only-key"
            assert model["api_model"] == "renamed"
            assert model["text_tool_protocol"] == "tagged"

            await page.locator("#provider-card > summary").click()
            connection_row = page.locator(f'[data-provider-id="{provider_id}"]')
            await connection_row.locator("summary").click()
            await connection_row.locator('[data-provider-field="chat_path"]').fill("/chat/completions")
            async with page.expect_response(lambda res: res.url.endswith("/settings") and res.request.method == "POST"):
                await page.locator("#save-settings-btn").click()
            assert store.get_provider(provider_id)["wire_api"] == "chat_completions"
        finally:
            await browser.close()
            server.stop()
            await server.close_all_connections()
