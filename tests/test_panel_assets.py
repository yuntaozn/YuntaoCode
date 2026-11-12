"""页面资源版本由文件内容生成，避免固定版本号缓存旧前端。"""

from pathlib import Path
import re

import tornado.testing
import tornado.web

from runtime.api.panel import PanelHandler


class TestPanelAssets(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        panel = Path(__file__).resolve().parents[1] / "runtime" / "panel"
        return tornado.web.Application(
            [(r"/(index|settings|automation|mcp-services|plugins)", AssetPage)],
            template_path=str(panel / "templates"), static_path=str(panel / "static"),
        )

    def test_all_pages_use_content_versions_and_uncached_html(self):
        for page in ["index", "settings", "automation", "mcp-services", "plugins"]:
            response = self.fetch("/" + page)
            assert response.code == 200
            assert response.headers["Cache-Control"] == "no-store"
            html = response.body.decode("utf-8")
            assert "{{ static_url" not in html
            assets = re.findall(r'(?:src|href)="(/static/[^"?]+)\?v=([^"&]+)"', html)
            assert len(assets) >= 3
            for path, version in assets:
                expected = tornado.web.StaticFileHandler.get_version(self._app.settings, path.removeprefix("/static/"))
                assert version == expected
                assert len(version) >= 32


class AssetPage(PanelHandler):
    def get(self, page):
        self.template_name = page + ".html"
        super().get()
