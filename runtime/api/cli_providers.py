from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import tornado.web

from .base import ApiHandler


class CliProvidersHandler(ApiHandler):
    def get(self) -> None:
        self.finish_json({
            "success": True,
            "data": self.runtime.cli_providers.list_public(),
        })

    def post(self) -> None:
        require_local_cli_provider_request(self)
        try:
            provider = self.runtime.cli_providers.upsert(self.parse_json_body())
        except (ValueError, RuntimeError) as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.set_status(201)
        self.finish_json({"success": True, "data": _with_linked_tools(provider, self.runtime.registry.list_specs())})


class CliProviderDetailHandler(ApiHandler):
    def get(self, provider_id: str) -> None:
        try:
            provider = self.runtime.cli_providers.get_public(provider_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc)) from exc
        self.finish_json({
            "success": True,
            "data": _with_linked_tools(provider, self.runtime.registry.list_specs()),
        })

    def put(self, provider_id: str) -> None:
        require_local_cli_provider_request(self)
        try:
            self.runtime.cli_providers.get_config(provider_id)
            provider = self.runtime.cli_providers.upsert(self.parse_json_body(), provider_id=provider_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.finish_json({"success": True, "data": _with_linked_tools(provider, self.runtime.registry.list_specs())})

    def delete(self, provider_id: str) -> None:
        require_local_cli_provider_request(self)
        try:
            self.runtime.cli_providers.delete(provider_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc)) from exc
        self.finish_json({"success": True})


def _with_linked_tools(provider: dict[str, Any], specs: list[dict[str, Any]]) -> dict[str, Any]:
    provider_id = str(provider.get("id") or "")
    linked_tools = [
        spec for spec in specs
        if spec.get("source_type") == "cli" and spec.get("source_id") == provider_id
    ]
    return {
        **provider,
        "linked_capabilities": linked_tools,
        "linked_capability_count": len(linked_tools),
    }


def require_local_cli_provider_request(handler: ApiHandler) -> None:
    try:
        if not ipaddress.ip_address(str(handler.request.remote_ip or "")).is_loopback:
            raise tornado.web.HTTPError(403, reason="CLI provider changes require a local Runtime request")
    except ValueError as exc:
        raise tornado.web.HTTPError(403, reason="CLI provider changes require a local Runtime request") from exc
    origin = str(handler.request.headers.get("Origin") or "").strip()
    if not origin:
        return
    host = str(handler.request.headers.get("Host") or "").strip().lower()
    parsed = urlparse(origin)
    host_name = urlparse(f"//{host}").hostname or ""
    try:
        host_is_local = host_name == "localhost" or ipaddress.ip_address(host_name).is_loopback
    except ValueError:
        host_is_local = False
    if not host_is_local or parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host:
        raise tornado.web.HTTPError(403, reason="CLI provider changes require a same-origin local request")
