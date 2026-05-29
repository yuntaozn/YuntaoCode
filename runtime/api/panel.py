from __future__ import annotations

from pathlib import Path

import tornado.web


class PanelHandler(tornado.web.RequestHandler):
    def initialize(self, template_name: str = "index.html", **kwargs: object) -> None:
        self.template_name = template_name

    def get(self) -> None:
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.set_header("Cache-Control", "no-store")
        template_path = Path(__file__).parents[1] / "panel" / "templates" / self.template_name
        self.write(template_path.read_text(encoding="utf-8"))
