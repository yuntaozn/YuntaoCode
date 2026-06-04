from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import tornado.httpclient
import tornado.web

from runtime.settings_store import SettingsStore

async def generate_chat_completion(
    *,
    settings: SettingsStore,
    model: str,
    messages: list[dict[str, Any]],
    enable_thinking: bool = True,
    reasoning_effort: str = "medium",
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
) -> tuple[str, dict[str, Any]]:
    model_config, provider, provider_id = settings.resolve_model(model)
    api_model = model_config.get("api_model") or model
    api_key = provider.get("api_key") or ""
    base_url = (provider.get("base_url") or "").rstrip("/")
    if not api_key and provider.get("api_key_required", True):
        raise tornado.web.HTTPError(
            400,
            reason=f"请先在设置中填写 {provider.get('name', provider_id)} 的 API Key",
        )
    if not base_url:
        raise tornado.web.HTTPError(400, reason=f"{provider_id} base_url is empty")

    body = build_request_body(
        provider_id=provider_id,
        provider=provider,
        model_config=model_config,
        model=api_model,
        messages=messages,
        stream=False,
        enable_thinking=enable_thinking,
        reasoning_effort=reasoning_effort,
        tools=tools,
        tool_choice=tool_choice,
    )

    request = tornado.httpclient.HTTPRequest(
        url=chat_completion_url(provider),
        method="POST",
        headers=request_headers(api_key),
        body=json.dumps(body, ensure_ascii=False),
        request_timeout=300,
    )
    try:
        response = await tornado.httpclient.AsyncHTTPClient().fetch(request, raise_error=False)
    except OSError as exc:
        raise tornado.web.HTTPError(502, reason=f"无法连接模型服务：{base_url}") from exc

    data = decode_json_response(response.body)
    if response.code >= 400:
        message = format_provider_error(data, response.code, base_url)
        raise tornado.web.HTTPError(response.code, reason=message)

    answer, reasoning = extract_message_parts(data)
    metadata: dict[str, Any] = {
        "mode": "local-model",
        "provider": provider_id,
        "provider_name": provider.get("name", provider_id),
        "model": model,
        "api_model": api_model,
        "usage": data.get("usage"),
    }
    if reasoning:
        metadata["reasoning"] = reasoning
    return answer, metadata


async def stream_chat_completion(
    *,
    settings: SettingsStore,
    model: str,
    messages: list[dict[str, Any]],
    enable_thinking: bool = True,
    reasoning_effort: str = "medium",
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
    idle_timeout: float = 90.0,
    heartbeat_interval: float = 15.0,
    max_idle_timeout: float = 240.0,
) -> AsyncIterator[dict[str, Any]]:
    model_config, provider, provider_id = settings.resolve_model(model)
    api_model = model_config.get("api_model") or model
    api_key = provider.get("api_key") or ""
    base_url = (provider.get("base_url") or "").rstrip("/")
    if not api_key and provider.get("api_key_required", True):
        raise tornado.web.HTTPError(
            400,
            reason=f"请先在设置中填写 {provider.get('name', provider_id)} 的 API Key",
        )
    if not base_url:
        raise tornado.web.HTTPError(400, reason=f"{provider_id} base_url is empty")

    body = build_request_body(
        provider_id=provider_id,
        provider=provider,
        model_config=model_config,
        model=api_model,
        messages=messages,
        stream=True,
        enable_thinking=enable_thinking,
        reasoning_effort=reasoning_effort,
        tools=tools,
        tool_choice=tool_choice,
    )
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    parser = StreamingParser(queue)
    request = tornado.httpclient.HTTPRequest(
        url=chat_completion_url(provider),
        method="POST",
        headers=request_headers(api_key),
        body=json.dumps(body, ensure_ascii=False),
        request_timeout=300,
        streaming_callback=parser.feed,
    )

    async def run_fetch() -> None:
        try:
            response = await tornado.httpclient.AsyncHTTPClient().fetch(request, raise_error=False)
            parser.flush()
            if response.code >= 400:
                data = decode_json_response(response.body)
                message = format_provider_error(data, response.code, base_url)
                queue.put_nowait({"error": message, "status": response.code})
        except OSError as exc:
            queue.put_nowait({"error": f"无法连接模型服务：{base_url}", "detail": str(exc)})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(run_fetch())
    loop = asyncio.get_running_loop()
    last_item_at = loop.time()
    hard_idle_timeout = max(idle_timeout, max_idle_timeout)
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                idle_seconds = loop.time() - last_item_at
                if idle_seconds < hard_idle_timeout:
                    yield {
                        "heartbeat": True,
                        "idle_seconds": int(idle_seconds),
                        "message": "模型仍在处理，请稍候",
                    }
                    continue
                # 空闲超时：连续 N 秒没有新数据，主动中断
                task.cancel()
                yield {
                    "error": f"模型服务响应超时：连续 {int(idle_timeout)} 秒未收到新数据，请重试",
                    "idle_timeout": True,
                }
                break
            if item is None:
                break
            last_item_at = loop.time()
            yield item
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def build_request_body(
    *,
    provider_id: str,
    provider: dict[str, Any],
    model_config: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    stream: bool,
    enable_thinking: bool,
    reasoning_effort: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    include_usage = bool(model_config.get("include_usage", provider.get("include_usage", True)))
    if stream and include_usage:
        body["stream_options"] = {"include_usage": True}
    if tools and model_config.get("supports_tools", True) is not False:
        body["tools"] = tools
        body["tool_choice"] = tool_choice or "auto"

    thinking_mode = str(model_config.get("thinking_mode") or provider.get("thinking_mode") or "").lower()
    if thinking_mode == "volcengine":
        if enable_thinking:
            body["thinking"] = {"type": "enabled"}
            if model_config.get("supports_reasoning_effort"):
                body["reasoning_effort"] = reasoning_effort
        else:
            body["thinking"] = {"type": "disabled"}
    elif thinking_mode == "qwen":
        if enable_thinking:
            body["enable_thinking"] = enable_thinking

    request_options: dict[str, Any] = {}
    if isinstance(provider.get("request_options"), dict):
        request_options.update(provider["request_options"])
    if isinstance(model_config.get("request_options"), dict):
        request_options.update(model_config["request_options"])
    body.update(request_options)
    return body


def chat_completion_url(provider: dict[str, Any]) -> str:
    base_url = str(provider.get("base_url") or "").rstrip("/")
    chat_path = str(provider.get("chat_path") or "/chat/completions").strip()
    if not chat_path:
        chat_path = "/chat/completions"
    if not chat_path.startswith("/"):
        chat_path = f"/{chat_path}"
    return f"{base_url}{chat_path}"


def request_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def decode_json_response(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"message": text}
    return value if isinstance(value, dict) else {"data": value}


def format_provider_error(data: dict[str, Any], status: int, base_url: str) -> str:
    if not data:
        return f"模型服务返回 HTTP {status}，但响应体为空（{base_url}）。可能是请求参数不被当前模型服务接受。"
    value: Any = data.get("message") or data.get("error") or data.get("detail")
    if isinstance(value, dict):
        value = value.get("message") or value.get("msg") or json.dumps(value, ensure_ascii=False)
    elif isinstance(value, list):
        value = json.dumps(value, ensure_ascii=False)
    elif not value:
        value = json.dumps(data, ensure_ascii=False)
    text = str(value)
    if text.strip() == "{}":
        return f"模型服务返回 HTTP {status}，错误体为空对象（{base_url}）。可能是工具调用参数或消息格式不兼容。"
    return text


class StreamingParser:
    def __init__(self, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        self.queue = queue
        self.buffer = ""

    def feed(self, chunk: bytes) -> None:
        self.buffer += chunk.decode("utf-8", errors="replace")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._handle_line(line.strip())

    def flush(self) -> None:
        if self.buffer.strip():
            self._handle_line(self.buffer.strip())
        self.buffer = ""

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return
        event = extract_stream_event(payload)
        if event:
            self.queue.put_nowait(event)


def extract_stream_event(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    usage = payload.get("usage")
    if not choices:
        event = extract_direct_stream_event(payload)
        if usage:
            event["usage"] = usage
        return event
    choice = choices[0] or {}
    delta = choice.get("delta") or choice.get("message") or {}
    message = normalize_text(delta.get("content") or delta.get("text") or "")
    reasoning = normalize_text(
        delta.get("reasoning_content")
        or delta.get("reasoning")
        or delta.get("reasoning_details")
        or delta.get("thinking")
        or ""
    )
    event: dict[str, Any] = {}
    if message:
        event["message"] = message
    if reasoning:
        event["reasoning"] = reasoning
    tool_calls = normalize_tool_call_chunks(delta.get("tool_calls") or delta.get("function_call") or [])
    if tool_calls:
        event["tool_calls"] = tool_calls
    if usage:
        event["usage"] = usage
    return event


def extract_direct_stream_event(payload: dict[str, Any]) -> dict[str, Any]:
    message = normalize_text(
        payload.get("message")
        or payload.get("content")
        or payload.get("text")
        or ""
    )
    reasoning = normalize_text(
        payload.get("reasoning")
        or payload.get("reasoning_content")
        or payload.get("reasoning_details")
        or payload.get("thinking")
        or ""
    )
    event: dict[str, Any] = {}
    if message:
        event["message"] = message
    if reasoning:
        event["reasoning"] = reasoning
    tool_calls = normalize_tool_call_chunks(payload.get("tool_calls") or payload.get("function_call") or [])
    if tool_calls:
        event["tool_calls"] = tool_calls
    return event


def normalize_tool_call_chunks(raw_tool_calls: Any) -> list[dict[str, Any]]:
    if not raw_tool_calls:
        return []
    if isinstance(raw_tool_calls, dict):
        raw_items = [raw_tool_calls]
    elif isinstance(raw_tool_calls, list):
        raw_items = raw_tool_calls
    else:
        return []

    chunks: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        if not function and ("name" in item or "arguments" in item):
            function = {
                "name": item.get("name") or "",
                "arguments": item.get("arguments") or "",
            }
        chunks.append({
            "index": item.get("index", fallback_index),
            "id": item.get("id"),
            "type": item.get("type") or "function",
            "function": {
                "name": function.get("name") or "",
                "arguments": function.get("arguments") or "",
            },
        })
    return chunks


def extract_message_parts(data: dict[str, Any]) -> tuple[str, str]:
    choices = data.get("choices") or []
    if not choices:
        return json.dumps(data, ensure_ascii=False), ""
    message = choices[0].get("message") or {}
    content = normalize_text(message.get("content") or "")
    reasoning = normalize_text(
        message.get("reasoning_content")
        or message.get("reasoning")
        or message.get("reasoning_details")
        or ""
    )
    if content:
        return content, reasoning
    if reasoning:
        return "模型返回了思考过程，但没有返回最终回答。", reasoning
    return json.dumps(message or data, ensure_ascii=False), ""


def normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if value:
        return json.dumps(value, ensure_ascii=False)
    return ""
