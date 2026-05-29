"""Website access tools for the local intelligent terminal."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import tornado.httpclient

from runtime.tool_registry import ToolRegistry, ToolSpec


DEFAULT_TIMEOUT = 20
MAX_TIMEOUT = 60
MAX_BODY_BYTES = 2_000_000
MAX_TEXT_CHARS = 80_000
MAX_HTML_CHARS = 120_000
MAX_LINKS = 120
USER_AGENT = (
    "YuntaoCode/0.1 "
    "(website access tool; +https://localhost.local)"
)


class _TextExtractor(HTMLParser):
    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._skip_depth = 0
        self._in_title = False
        self._current_link: dict[str, str] | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = attrs_dict.get("href", "").strip()
            self._current_link = {
                "url": urljoin(self.base_url, href) if href else "",
                "text": "",
            }
            self._current_link_text = []
        if tag in {"p", "div", "section", "article", "header", "footer", "li", "tr", "br", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._current_link is not None:
            text = _normalize_space(" ".join(self._current_link_text))
            self._current_link["text"] = text
            if self._current_link["url"] or text:
                self.links.append(self._current_link)
            self._current_link = None
            self._current_link_text = []
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = unescape(data)
        if self._in_title:
            self.title_parts.append(text)
        if self._current_link is not None:
            self._current_link_text.append(text)
        self.text_parts.append(text)

    def result(self) -> dict[str, Any]:
        title = _normalize_space(" ".join(self.title_parts))
        text = _normalize_text("\n".join(self.text_parts))
        links: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in self.links:
            url = item.get("url", "").strip()
            label = _normalize_space(item.get("text", ""))
            if not url and not label:
                continue
            key = (url, label)
            if key in seen:
                continue
            seen.add(key)
            links.append({"url": url, "text": label})
            if len(links) >= MAX_LINKS:
                break
        return {"title": title, "text": text, "links": links}


def _validate_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        raise ValueError("url is required")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are supported")
    if not parsed.netloc:
        raise ValueError("url must include a host")
    return url


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_text(value: str) -> str:
    lines = [_normalize_space(line) for line in (value or "").splitlines()]
    compacted: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if not blank and compacted:
                compacted.append("")
            blank = True
            continue
        compacted.append(line)
        blank = False
    return "\n".join(compacted).strip()


def _decode_body(body: bytes, content_type: str = "", encoding: str | None = None) -> tuple[str, str]:
    if encoding:
        try:
            return body.decode(encoding, errors="replace"), encoding
        except LookupError:
            pass
    match = re.search(r"charset=([\w.\-]+)", content_type or "", re.IGNORECASE)
    encodings = []
    if match:
        encodings.append(match.group(1))
    encodings.extend(["utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"])
    seen: set[str] = set()
    for enc in encodings:
        key = enc.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return body.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace"), "utf-8"


async def _fetch(url: str, *, timeout: int, headers: dict[str, str] | None = None) -> tornado.httpclient.HTTPResponse:
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    request_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,application/json;q=0.9,*/*;q=0.5",
        **(headers or {}),
    }
    request = tornado.httpclient.HTTPRequest(
        url=url,
        method="GET",
        headers=request_headers,
        request_timeout=timeout,
        connect_timeout=min(timeout, 15),
        follow_redirects=True,
        max_redirects=5,
        user_agent=USER_AGENT,
        decompress_response=True,
    )
    return await tornado.httpclient.AsyncHTTPClient().fetch(request, raise_error=False)


def _response_base(response: tornado.httpclient.HTTPResponse, url: str) -> dict[str, Any]:
    headers = {key: value for key, value in response.headers.get_all()}
    final_url = getattr(response.request, "url", url)
    return {
        "url": url,
        "final_url": final_url,
        "status_code": response.code,
        "reason": response.reason,
        "headers": {
            "content-type": response.headers.get("Content-Type", ""),
            "content-length": response.headers.get("Content-Length", ""),
            "last-modified": response.headers.get("Last-Modified", ""),
        },
        "raw_header_count": len(headers),
    }


async def fetch_url(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    url = _validate_url(input_data.get("url"))
    timeout = int(input_data.get("timeout") or DEFAULT_TIMEOUT)
    max_chars = max(1000, min(int(input_data.get("max_chars") or MAX_TEXT_CHARS), MAX_TEXT_CHARS))
    encoding = input_data.get("encoding")
    response = await _fetch(url, timeout=timeout)
    body = response.body or b""
    if len(body) > MAX_BODY_BYTES:
        body = body[:MAX_BODY_BYTES]
    content_type = response.headers.get("Content-Type", "")
    text, detected_encoding = _decode_body(body, content_type, encoding)
    context.log("info", "website fetched", {"url": url, "status_code": response.code})
    return {
        **_response_base(response, url),
        "encoding": detected_encoding,
        "content_type": content_type,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars or len(response.body or b"") > MAX_BODY_BYTES,
        "byte_count": len(response.body or b""),
    }


async def extract_text(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    url = _validate_url(input_data.get("url"))
    timeout = int(input_data.get("timeout") or DEFAULT_TIMEOUT)
    max_chars = max(1000, min(int(input_data.get("max_chars") or MAX_TEXT_CHARS), MAX_TEXT_CHARS))
    response = await _fetch(url, timeout=timeout)
    body = response.body or b""
    if len(body) > MAX_BODY_BYTES:
        body = body[:MAX_BODY_BYTES]
    content_type = response.headers.get("Content-Type", "")
    html, encoding = _decode_body(body, content_type, input_data.get("encoding"))
    parsed = _extract_from_html(html, base_url=url)
    context.log("info", "website text extracted", {"url": url, "status_code": response.code})
    return {
        **_response_base(response, url),
        "encoding": encoding,
        "title": parsed["title"],
        "text": parsed["text"][:max_chars],
        "links": parsed["links"],
        "truncated": len(parsed["text"]) > max_chars or len(response.body or b"") > MAX_BODY_BYTES,
    }


async def render_page(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    url = _validate_url(input_data.get("url"))
    timeout = max(1, min(int(input_data.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    wait_until = str(input_data.get("wait_until") or "networkidle").strip()
    if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
        wait_until = "networkidle"
    selector = str(input_data.get("selector") or "").strip()
    max_chars = max(1000, min(int(input_data.get("max_chars") or MAX_TEXT_CHARS), MAX_TEXT_CHARS))

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise ValueError("playwright is required for web.render_page") from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 1000},
        )
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
            if selector:
                try:
                    await page.wait_for_selector(selector, timeout=min(timeout * 1000, 10_000))
                except Exception:
                    pass
                html = await page.locator(selector).first.inner_html(timeout=3000)
                text = await page.locator(selector).first.inner_text(timeout=3000)
            else:
                html = await page.content()
                text = await page.locator("body").inner_text(timeout=5000)
            title = await page.title()
            parsed = _extract_from_html(html, base_url=url)
            status_code = response.status if response else 0
        finally:
            await browser.close()

    text = _normalize_text(text or parsed["text"])
    context.log("info", "website rendered", {"url": url, "status_code": status_code})
    return {
        "url": url,
        "status_code": status_code,
        "title": title or parsed["title"],
        "selector": selector,
        "text": text[:max_chars],
        "html_preview": html[:MAX_HTML_CHARS],
        "links": parsed["links"],
        "truncated": len(text) > max_chars or len(html) > MAX_HTML_CHARS,
    }


def _extract_from_html(html: str, *, base_url: str = "") -> dict[str, Any]:
    parser = _TextExtractor(base_url=base_url)
    parser.feed(html or "")
    parser.close()
    return parser.result()


def register_web_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="web.fetch_url",
            name="访问网站 URL",
            description="通过 HTTP GET 访问网页或公开接口，返回状态码、响应头摘要和文本内容预览。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要访问的 http/https URL"},
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "max_chars": {"type": "integer", "default": MAX_TEXT_CHARS},
                    "encoding": {"type": "string", "description": "可选文本编码，如 utf-8、gbk"},
                },
                "required": ["url"],
            },
            local_only=False,
        ),
        fetch_url,
    )
    registry.register(
        ToolSpec(
            id="web.extract_text",
            name="提取网页正文",
            description="访问网页并抽取标题、正文文本和页面链接，适合让模型阅读普通资讯、文档和公告页面。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要访问的 http/https URL"},
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "max_chars": {"type": "integer", "default": MAX_TEXT_CHARS},
                    "encoding": {"type": "string", "description": "可选文本编码，如 utf-8、gbk"},
                },
                "required": ["url"],
            },
            local_only=False,
        ),
        extract_text,
    )
    registry.register(
        ToolSpec(
            id="web.render_page",
            name="渲染动态网页",
            description="使用 Playwright 打开网页，等待 JS 渲染后抽取正文、HTML 预览和链接。适合普通 HTTP 抽取拿不到内容的页面。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要渲染的 http/https URL"},
                    "selector": {"type": "string", "description": "可选 CSS 选择器，只抽取指定区域"},
                    "wait_until": {
                        "type": "string",
                        "default": "networkidle",
                        "description": "load、domcontentloaded、networkidle 或 commit",
                    },
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "max_chars": {"type": "integer", "default": MAX_TEXT_CHARS},
                },
                "required": ["url"],
            },
            local_only=False,
            optional_dependencies=["playwright"],
        ),
        render_page,
    )
