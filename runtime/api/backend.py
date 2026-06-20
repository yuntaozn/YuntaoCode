from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import tornado.httpclient
import tornado.web

from .base import ApiHandler


def normalize_backend_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise tornado.web.HTTPError(400, reason="backend_url must be an http(s) URL")
    host = parsed.hostname or ""
    if host.lower() == "localhost":
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://127.0.0.1{port}{path}"
    return value.rstrip("/")


class BackendLoginHandler(ApiHandler):
    async def post(self) -> None:
        payload = self.parse_json_body()
        backend_url = normalize_backend_url(payload.get("backend_url", ""))
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""
        if not username or not password:
            raise tornado.web.HTTPError(400, reason="username and password are required")

        request = tornado.httpclient.HTTPRequest(
            url=f"{backend_url}/api/login",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"username": username, "password": password}, ensure_ascii=False),
            request_timeout=20,
        )
        try:
            response = await tornado.httpclient.AsyncHTTPClient().fetch(request, raise_error=False)
        except OSError as exc:
            raise tornado.web.HTTPError(
                502,
                reason=f"无法连接后台服务：{backend_url}，请确认 YuntaoCode 后台服务已启动并可访问",
            ) from exc
        data = decode_json_response(response.body)
        if response.code >= 400:
            message = data.get("error") or data.get("message") or f"backend login failed: {response.code}"
            raise tornado.web.HTTPError(response.code, reason=message)

        self.finish_json({"success": True, "data": data})


def decode_json_response(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"message": text}
    if isinstance(value, dict):
        return value
    return {"data": value}
