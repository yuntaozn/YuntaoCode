from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable


MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_PROTOCOL_FALLBACK_VERSIONS = ("2024-11-05",)
MCP_CLIENT_INFO = {"name": "YuntaoCode", "version": "0.1.0"}


class McpProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpToolDefinition:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any]


class McpStdioSession:
    """Minimal MCP client session over an already-started stdio process."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        log: Callable[[str, str], None] | None = None,
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise ValueError("MCP stdio process requires stdin and stdout pipes")
        self.process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._log = log or (lambda _level, _message: None)
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self.protocol_version = ""
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}
        self.instructions = ""
        self.tools: list[McpToolDefinition] = []

    async def connect(self) -> list[McpToolDefinition]:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._read_messages())
        result: dict[str, Any] | None = None
        last_error: Exception | None = None
        for protocol_version in (MCP_PROTOCOL_VERSION, *MCP_PROTOCOL_FALLBACK_VERSIONS):
            try:
                result = await self.request(
                    "initialize",
                    {
                        "protocolVersion": protocol_version,
                        "capabilities": {},
                        "clientInfo": MCP_CLIENT_INFO,
                    },
                )
                break
            except McpProtocolError as exc:
                last_error = exc
                self._log("warning", f"MCP initialize failed for {protocol_version}: {exc}")
        if result is None:
            raise McpProtocolError(f"MCP initialize failed: {last_error}")
        self.protocol_version = str(result.get("protocolVersion") or "")
        self.server_info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
        self.server_capabilities = (
            result.get("capabilities") if isinstance(result.get("capabilities"), dict) else {}
        )
        self.instructions = str(result.get("instructions") or "")
        await self.notify("notifications/initialized")
        self.tools = await self.list_tools()
        return list(self.tools)

    async def list_tools(self) -> list[McpToolDefinition]:
        tools: list[McpToolDefinition] = []
        cursor = ""
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = await self.request("tools/list", params)
            for item in result.get("tools") or []:
                if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                    continue
                tools.append(
                    McpToolDefinition(
                        name=str(item["name"]).strip(),
                        title=str(item.get("title") or item["name"]).strip(),
                        description=str(item.get("description") or "").strip(),
                        input_schema=(
                            item.get("inputSchema")
                            if isinstance(item.get("inputSchema"), dict)
                            else {"type": "object", "properties": {}}
                        ),
                        annotations=(
                            item.get("annotations")
                            if isinstance(item.get("annotations"), dict)
                            else {}
                        ),
                    )
                )
            cursor = str(result.get("nextCursor") or "").strip()
            if not cursor:
                return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        })
        try:
            message = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise McpProtocolError(f"MCP request timed out after {timeout:g}s: {method}") from exc
        error = message.get("error")
        if isinstance(error, dict):
            raise McpProtocolError(str(error.get("message") or f"MCP request failed: {method}"))
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        })

    async def close(self) -> None:
        reader = self._reader_task
        self._reader_task = None
        if reader and not reader.done():
            reader.cancel()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpProtocolError("MCP session closed"))
        self._pending.clear()

    async def _send(self, message: dict[str, Any]) -> None:
        if self.process.returncode is not None:
            raise McpProtocolError(f"MCP process exited with code {self.process.returncode}")
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._stdin.write(encoded + b"\n")
        await self._stdin.drain()

    async def _read_messages(self) -> None:
        try:
            while True:
                line = await self._stdout.readline()
                if not line:
                    raise McpProtocolError("MCP stdio stream closed")
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._log("warning", "ignored non-JSON MCP stdout line")
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if request_id is not None and ("result" in message or "error" in message):
                    future = self._pending.pop(request_id, None)
                    if future and not future.done():
                        future.set_result(message)
                    continue
                if request_id is not None and message.get("method"):
                    await self._send({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": "Client method not supported"},
                    })
                    continue
                method = str(message.get("method") or "")
                if method:
                    self._log("info", f"MCP notification: {method}")
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._log("error", str(exc))
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)
            self._pending.clear()


def normalize_mcp_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    content_items = result.get("content") if isinstance(result.get("content"), list) else []
    text_parts = [
        str(item.get("text") or "")
        for item in content_items
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    text = "\n".join(part for part in text_parts if part).strip()
    output: dict[str, Any] = {
        "content": text or json.dumps(content_items, ensure_ascii=False),
        "mcp_content": content_items,
    }
    if isinstance(result.get("structuredContent"), dict):
        output["structured_content"] = result["structuredContent"]
    if result.get("isError") is True or _mcp_result_reports_error(text, output.get("structured_content")):
        output["error"] = True
        output["message"] = text or "MCP tool reported an error"
    return output


def _mcp_result_reports_error(text: str, structured_content: Any) -> bool:
    """Return True when a transport-successful MCP result is still a tool error.

    Some MCP servers return a normal JSON-RPC response while embedding the real
    execution failure in text or structured content.  Normalize that into the
    same ``output.error`` contract used by built-in tools so task status,
    retries, and audit facts stay honest.
    """
    if isinstance(structured_content, dict):
        if structured_content.get("error") or structured_content.get("is_error") is True:
            return True
        for key in ("ok", "success"):
            if structured_content.get(key) is False:
                return True
        status = str(structured_content.get("status") or "").strip().lower()
        if status in {"error", "failed", "failure"}:
            return True

    first_line = (text or "").strip().splitlines()[0:1]
    if not first_line:
        return False
    lowered = first_line[0].strip().lower()
    return lowered.startswith((
        "error executing",
        "error executing code",
        "error executing tool",
        "tool execution failed",
        "execution failed",
        "traceback ",
        "traceback:",
    ))
