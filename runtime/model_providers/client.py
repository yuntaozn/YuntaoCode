from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator
from urllib.parse import urlparse, urlunparse

import tornado.httpclient
import tornado.web
import tiktoken

from runtime.model_request_options import sanitize_request_options
from runtime.settings_store import SettingsStore

LOCAL_CONTEXT_CACHE_TTL_SECONDS = 60.0
REQUEST_TOKEN_MARGIN = 256
_context_limit_cache: dict[str, tuple[float, int]] = {}
_encoding: tiktoken.Encoding | None = None


ESSENTIAL_TOOL_ORDER: tuple[str, ...] = (
    "filesystem__scan_folder",
    "filesystem__read_file",
    "filesystem__read_text_preview",
    "code__search_text",
    "code__list_project_files",
    "git__status",
    "git__diff",
    "filesystem__write_file",
    "filesystem__apply_changes",
    "code__apply_patch",
    "code__edit_file",
    "code__replace_text",
    "shell__run_command",
    "filesystem__create_text_draft",
    "filesystem__append_text_chunk",
    "filesystem__finalize_text_file",
    "web__fetch_url",
    "web__extract_text",
    "memory__recall",
)
ESSENTIAL_TOOL_RANK = {name: index for index, name in enumerate(ESSENTIAL_TOOL_ORDER)}


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
    context_limit = await resolve_provider_context_limit(
        provider=provider,
        model_config=model_config,
        api_model=api_model,
        api_key=api_key,
    )
    body, budget_info = fit_request_body_to_context(body, context_limit=context_limit)
    if budget_info.get("blocked"):
        raise tornado.web.HTTPError(400, reason=str(budget_info.get("message") or "model request exceeds context"))

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
    if budget_info:
        metadata["request_budget"] = budget_info
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
    if model_config.get("supports_stream", True) is False:
        try:
            answer, metadata = await generate_chat_completion(
                settings=settings,
                model=model,
                messages=messages,
                enable_thinking=enable_thinking,
                reasoning_effort=reasoning_effort,
                tools=tools,
                tool_choice=tool_choice,
            )
        except tornado.web.HTTPError as exc:
            yield {"error": exc.reason or str(exc), "status": exc.status_code}
            return
        if metadata.get("reasoning"):
            yield {"reasoning": metadata["reasoning"]}
        if answer:
            yield {"message": answer}
        if metadata.get("usage"):
            yield {"usage": metadata["usage"], "finish_reason": "stop"}
        else:
            yield {"finish_reason": "stop"}
        return

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
    context_limit = await resolve_provider_context_limit(
        provider=provider,
        model_config=model_config,
        api_model=api_model,
        api_key=api_key,
    )
    body, budget_info = fit_request_body_to_context(body, context_limit=context_limit)
    if budget_info.get("blocked"):
        yield {"error": str(budget_info.get("message") or "model request exceeds context"), "status": 400}
        return
    if budget_info:
        yield {"request_budget": budget_info}
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
                        "message": "正在等待模型响应",
                        "phase": "model_stream",
                        "connection_alive": True,
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
        body["enable_thinking"] = qwen_enable_thinking(
            model_config=model_config,
            provider=provider,
            requested=enable_thinking,
        )

    output_token_param = str(model_config.get("output_token_param") or "").strip()
    try:
        max_output_tokens = int(model_config.get("max_output_tokens") or 0)
    except (TypeError, ValueError):
        max_output_tokens = 0
    if (
        max_output_tokens > 0
        and output_token_param in {"max_tokens", "max_completion_tokens", "max_output_tokens"}
    ):
        body[output_token_param] = max_output_tokens

    request_options: dict[str, Any] = {}
    if isinstance(provider.get("request_options"), dict):
        request_options.update(sanitize_request_options(provider["request_options"]))
    if isinstance(model_config.get("request_options"), dict):
        request_options.update(sanitize_request_options(model_config["request_options"]))
    body.update(request_options)
    return body


async def resolve_provider_context_limit(
    *,
    provider: dict[str, Any],
    model_config: dict[str, Any],
    api_model: str,
    api_key: str,
) -> int:
    configured = _safe_positive_int(model_config.get("context_limit"))
    discovered = await discover_provider_context_limit(provider=provider, api_model=api_model, api_key=api_key)
    if configured and discovered:
        return min(configured, discovered)
    return configured or discovered or 0


async def discover_provider_context_limit(
    *,
    provider: dict[str, Any],
    api_model: str,
    api_key: str = "",
) -> int:
    base_url = str(provider.get("base_url") or "").rstrip("/")
    if not base_url or not _is_local_base_url(base_url):
        return 0
    cache_key = f"{base_url}|{api_model}"
    cached = _context_limit_cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] <= LOCAL_CONTEXT_CACHE_TTL_SECONDS:
        return cached[1]

    limit = await _fetch_llamacpp_props_context_limit(provider, api_key)
    if not limit:
        limit = await _fetch_models_context_limit(provider, api_model, api_key)
    _context_limit_cache[cache_key] = (now, limit)
    return limit


async def _fetch_llamacpp_props_context_limit(provider: dict[str, Any], api_key: str) -> int:
    root = provider_root_url(provider)
    if not root:
        return 0
    data = await _fetch_json(f"{root}/props", api_key=api_key, timeout=2.0)
    return context_limit_from_props(data)


async def _fetch_models_context_limit(provider: dict[str, Any], api_model: str, api_key: str) -> int:
    data = await _fetch_json(f"{str(provider.get('base_url') or '').rstrip('/')}/models", api_key=api_key, timeout=2.0)
    return context_limit_from_models(data, api_model)


async def _fetch_json(url: str, *, api_key: str, timeout: float) -> dict[str, Any]:
    try:
        response = await tornado.httpclient.AsyncHTTPClient().fetch(
            tornado.httpclient.HTTPRequest(
                url=url,
                method="GET",
                headers=request_headers(api_key),
                request_timeout=timeout,
            ),
            raise_error=False,
        )
    except Exception:
        return {}
    if response.code >= 400:
        return {}
    return decode_json_response(response.body)


def context_limit_from_props(data: dict[str, Any]) -> int:
    if not isinstance(data, dict):
        return 0
    candidates = [
        data.get("n_ctx"),
        (data.get("default_generation_settings") or {}).get("n_ctx")
        if isinstance(data.get("default_generation_settings"), dict)
        else None,
        ((data.get("default_generation_settings") or {}).get("params") or {}).get("n_ctx")
        if isinstance((data.get("default_generation_settings") or {}).get("params"), dict)
        else None,
    ]
    return _first_positive_int(candidates)


def context_limit_from_models(data: dict[str, Any], api_model: str = "") -> int:
    if not isinstance(data, dict):
        return 0
    items = data.get("data")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        items = [data]
    normalized_target = str(api_model or "").strip()
    ordered = sorted(
        [item for item in items if isinstance(item, dict)],
        key=lambda item: 0 if str(item.get("id") or "") == normalized_target else 1,
    )
    for item in ordered:
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        limit = _first_positive_int([
            item.get("n_ctx"),
            item.get("context_length"),
            item.get("context_limit"),
            meta.get("n_ctx"),
            meta.get("context_length"),
            meta.get("context_limit"),
        ])
        if limit:
            return limit
    return 0


def fit_request_body_to_context(
    body: dict[str, Any],
    *,
    context_limit: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if context_limit <= 0:
        return body, {}
    estimated = estimate_request_tokens(body)
    usable = max(context_limit - REQUEST_TOKEN_MARGIN, 1)
    if estimated <= usable:
        return body, {
            "context_limit": context_limit,
            "estimated_request_tokens": estimated,
            "tool_count": len(body.get("tools") or []),
        }

    tools = body.get("tools")
    if not isinstance(tools, list) or not tools:
        return body, {
            "context_limit": context_limit,
            "estimated_request_tokens": estimated,
            "blocked": True,
            "message": (
                f"模型请求约 {estimated} tokens，超过当前模型服务上下文 {context_limit} tokens。"
                "请调低模型上下文配置、清理对话历史，或用更大的 llama-server --ctx-size 启动。"
            ),
        }

    fitted = dict(body)
    ranked_tools = sorted(
        tools,
        key=lambda tool: _tool_rank(tool),
    )
    kept: list[dict[str, Any]] = []
    for tool in ranked_tools:
        trial = dict(fitted)
        trial["tools"] = [*kept, tool]
        trial["tool_choice"] = fitted.get("tool_choice") or "auto"
        if estimate_request_tokens(trial) <= usable:
            kept.append(tool)
    if kept:
        fitted["tools"] = kept
        fitted["tool_choice"] = fitted.get("tool_choice") or "auto"
    else:
        fitted.pop("tools", None)
        fitted.pop("tool_choice", None)

    fitted_estimate = estimate_request_tokens(fitted)
    info = {
        "context_limit": context_limit,
        "estimated_request_tokens": fitted_estimate,
        "original_estimated_request_tokens": estimated,
        "tool_count": len(kept),
        "original_tool_count": len(tools),
        "tools_pruned": max(0, len(tools) - len(kept)),
    }
    if fitted_estimate > usable:
        info.update({
            "blocked": True,
            "message": (
                f"模型请求约 {fitted_estimate} tokens，超过当前模型服务上下文 {context_limit} tokens；"
                "已尝试裁剪工具目录但仍不足。请清理对话历史或用更大的 --ctx-size 启动本地模型。"
            ),
        })
    return fitted, info


def estimate_request_tokens(body: dict[str, Any]) -> int:
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    try:
        return len(_get_encoding().encode(text))
    except Exception:
        return max(1, len(text) // 3)


def provider_root_url(provider: dict[str, Any]) -> str:
    base_url = str(provider.get("base_url") or "").rstrip("/")
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3] or ""
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")


def _is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _tool_rank(tool: dict[str, Any]) -> tuple[int, str]:
    fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    name = str(fn.get("name") or "")
    return (ESSENTIAL_TOOL_RANK.get(name, 10_000), name)


def _safe_positive_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _first_positive_int(values: list[Any]) -> int:
    for value in values:
        number = _safe_positive_int(value)
        if number:
            return number
    return 0


def _get_encoding() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def qwen_enable_thinking(
    *,
    model_config: dict[str, Any],
    provider: dict[str, Any],
    requested: bool,
) -> bool:
    if requested:
        return True
    if bool(model_config.get("allow_disable_thinking") or provider.get("allow_disable_thinking")):
        return False
    return True


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
    message = normalize_text(
        delta.get("content")
        or delta.get("text")
        or choice.get("content")
        or choice.get("text")
        or ""
    )
    reasoning = normalize_text(
        delta.get("reasoning_content")
        or delta.get("reasoning")
        or delta.get("reasoning_details")
        or delta.get("thinking")
        or delta.get("thinking_content")
        or choice.get("reasoning_content")
        or choice.get("reasoning")
        or choice.get("reasoning_details")
        or choice.get("thinking")
        or choice.get("thinking_content")
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
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None:
        event["finish_reason"] = finish_reason
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
    finish_reason = payload.get("finish_reason")
    if finish_reason is not None:
        event["finish_reason"] = finish_reason
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
