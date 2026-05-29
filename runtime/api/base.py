from __future__ import annotations

import json
from typing import Any

import tornado.web

from .. import i18n


class ApiHandler(tornado.web.RequestHandler):
    def initialize(self, runtime: Any) -> None:
        self.runtime = runtime

    def get_lang(self) -> str:
        """Return the preferred language for this request."""
        return i18n.get_lang(self.request)

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate *key* using the request language."""
        return i18n.t(key, self.get_lang(), **kwargs)

    def set_default_headers(self) -> None:
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def options(self, *args: Any, **kwargs: Any) -> None:
        self.set_status(204)
        self.finish()

    def prepare(self) -> None:
        if self.request.method == "OPTIONS":
            return

    def parse_json_body(self) -> dict[str, Any]:
        if not self.request.body:
            return {}
        try:
            value = json.loads(self.request.body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise tornado.web.HTTPError(400, reason=f"invalid json body: {exc}") from exc
        if not isinstance(value, dict):
            raise tornado.web.HTTPError(400, reason="json body must be an object")
        return value

    def finish_json(self, payload: dict[str, Any]) -> None:
        self.finish(json.dumps(payload, ensure_ascii=False))

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        reason = self._reason or "request failed"
        exc_info = kwargs.get("exc_info")
        if exc_info and len(exc_info) >= 2 and getattr(exc_info[1], "reason", None):
            reason = exc_info[1].reason
        self.finish_json({"success": False, "error": reason})
