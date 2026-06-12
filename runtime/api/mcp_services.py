from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import tornado.web

from .base import ApiHandler


class McpServicesHandler(ApiHandler):
    def get(self) -> None:
        services = [
            _with_linked_capabilities(service, self.runtime.registry.list_specs())
            for service in self.runtime.mcp_services.list_public()
        ]
        self.finish_json({"success": True, "data": services})

    def post(self) -> None:
        require_local_mcp_control_request(self)
        try:
            service = self.runtime.mcp_services.upsert(self.parse_json_body())
        except (ValueError, RuntimeError) as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.set_status(201)
        self.finish_json({"success": True, "data": service})


class McpServiceDetailHandler(ApiHandler):
    def get(self, service_id: str) -> None:
        try:
            service = self.runtime.mcp_services.get_public(service_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc)) from exc
        self.finish_json({
            "success": True,
            "data": _with_linked_capabilities(service, self.runtime.registry.list_specs()),
        })

    def put(self, service_id: str) -> None:
        require_local_mcp_control_request(self)
        try:
            self.runtime.mcp_services.get_config(service_id)
            service = self.runtime.mcp_services.upsert(self.parse_json_body(), service_id=service_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.finish_json({"success": True, "data": service})

    def delete(self, service_id: str) -> None:
        require_local_mcp_control_request(self)
        try:
            self.runtime.mcp_services.delete(service_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc)) from exc
        except RuntimeError as exc:
            raise tornado.web.HTTPError(409, reason=str(exc)) from exc
        self.finish_json({"success": True})


class McpServiceActionHandler(ApiHandler):
    async def post(self, service_id: str) -> None:
        require_local_mcp_control_request(self)
        action = str(self.parse_json_body().get("action") or "").strip()
        try:
            service = await self.runtime.mcp_services.action(service_id, action)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.finish_json({
            "success": True,
            "data": _with_linked_capabilities(service, self.runtime.registry.list_specs()),
        })


def _with_linked_capabilities(service: dict[str, Any], specs: list[dict[str, Any]]) -> dict[str, Any]:
    service_id = str(service.get("id") or "")
    linked_tools = [
        spec for spec in specs
        if spec.get("source_type") == "mcp" and spec.get("source_id") == service_id
    ]
    return {
        **service,
        "linked_capabilities": linked_tools,
        "linked_capability_count": len(linked_tools),
    }


def require_local_mcp_control_request(handler: ApiHandler) -> None:
    try:
        if not ipaddress.ip_address(str(handler.request.remote_ip or "")).is_loopback:
            raise tornado.web.HTTPError(403, reason="MCP service changes require a local Runtime request")
    except ValueError as exc:
        raise tornado.web.HTTPError(403, reason="MCP service changes require a local Runtime request") from exc
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
        raise tornado.web.HTTPError(403, reason="MCP service changes require a same-origin local request")
