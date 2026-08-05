"""YuntaoCode 内置的受控网页读取工具。"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import tornado.httpclient

from runtime.browser_runtime import playwright_chromium_readiness
from runtime.tool_registry import ToolRegistry, ToolSpec


DEFAULT_TIMEOUT = 20
MAX_TIMEOUT = 60
MAX_BODY_BYTES = 2_000_000
MAX_TEXT_CHARS = 80_000
MAX_HTML_CHARS = 120_000
MAX_LINKS = 120
MAX_COLLECT_PAGES = 50
MAX_COLLECT_ASSETS = 200
USER_AGENT = (
    "YuntaoCode/0.1 "
    "(website access tool; +https://localhost.local)"
)
_BARE_HOST_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?::\d{1,5})?(?:/[^\s]*)?$"
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


class _HtmlResourceExtractor(HTMLParser):
    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[str] = []
        self.assets: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag == "a":
            self._add_link(attrs_dict.get("href", ""))
        elif tag == "img":
            self._add_asset(attrs_dict.get("src", ""), "image")
            self._add_asset(attrs_dict.get("data-src", ""), "image")
            self._add_asset(attrs_dict.get("srcset", ""), "image_srcset")
        elif tag == "script":
            self._add_asset(attrs_dict.get("src", ""), "script")
        elif tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href", "")
            if any(kind in rel for kind in ("stylesheet", "icon", "preload", "apple-touch-icon")):
                self._add_asset(href, f"link:{rel or 'resource'}")
        elif tag in {"source", "video", "audio"}:
            self._add_asset(attrs_dict.get("src", ""), tag)
            self._add_asset(attrs_dict.get("poster", ""), "poster")

    def _add_link(self, value: str) -> None:
        url = _absolute_http_url(self.base_url, value)
        if url and url not in self.links:
            self.links.append(url)

    def _add_asset(self, value: str, kind: str) -> None:
        for item in _resource_values(value):
            url = _absolute_http_url(self.base_url, item)
            if not url:
                continue
            if any(existing["url"] == url for existing in self.assets):
                continue
            self.assets.append({"url": url, "kind": kind})


def _validate_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        raise ValueError("url is required")
    if "://" not in url and _BARE_HOST_RE.match(url):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are supported")
    if not parsed.netloc:
        raise ValueError("url must include a host")
    return url


def _absolute_http_url(base_url: str, value: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return ""
    url = urljoin(base_url, raw)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _resource_values(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if "," not in text:
        return [text]
    result: list[str] = []
    for part in text.split(","):
        first = part.strip().split(" ", 1)[0].strip()
        if first:
            result.append(first)
    return result


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


async def _fetch(
    url: str,
    *,
    timeout: int,
    headers: dict[str, str] | None = None,
    validate_cert: bool = True,
) -> tornado.httpclient.HTTPResponse:
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
        validate_cert=validate_cert,
    )
    return await tornado.httpclient.AsyncHTTPClient().fetch(request, raise_error=False)


async def _fetch_with_http_fallback(
    url: str,
    *,
    timeout: int,
    validate_cert: bool,
) -> tuple[tornado.httpclient.HTTPResponse, str]:
    try:
        return await _fetch(url, timeout=timeout, validate_cert=validate_cert), url
    except Exception:
        fallback_url = _http_fallback_url(url)
        if not fallback_url:
            raise
        return await _fetch(fallback_url, timeout=timeout, validate_cert=validate_cert), fallback_url


def _http_fallback_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        return ""
    return parsed._replace(scheme="http").geturl()


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


async def collect_site_assets(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    url = _validate_url(input_data.get("url"))
    output_dir = _resolve_output_dir(input_data.get("output_dir"), context)
    timeout = int(input_data.get("timeout") or DEFAULT_TIMEOUT)
    max_pages = max(1, min(int(input_data.get("max_pages") or 8), MAX_COLLECT_PAGES))
    max_assets = max(0, min(int(input_data.get("max_assets") or 60), MAX_COLLECT_ASSETS))
    same_origin = input_data.get("same_origin", True) is not False
    include_assets = input_data.get("include_assets", True) is not False
    include_pages = input_data.get("include_pages", True) is not False
    validate_cert = input_data.get("validate_cert", True) is not False

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pages").mkdir(exist_ok=True)
    (output_dir / "text").mkdir(exist_ok=True)
    (output_dir / "assets").mkdir(exist_ok=True)

    root_origin = _url_origin(url)
    allowed_origins = {root_origin}
    page_queue: list[str] = [url]
    seen_pages: set[str] = set()
    seen_assets: set[str] = set()
    pages: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    while page_queue and len(pages) < max_pages:
        page_url = page_queue.pop(0)
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        try:
            response, effective_page_url = await _fetch_with_http_fallback(
                page_url,
                timeout=timeout,
                validate_cert=validate_cert,
            )
            allowed_origins.add(_url_origin(effective_page_url))
            body = response.body or b""
            if len(body) > MAX_BODY_BYTES:
                body = body[:MAX_BODY_BYTES]
            content_type = response.headers.get("Content-Type", "")
            html, encoding = _decode_body(body, content_type)
            page_name = _safe_url_file_name(effective_page_url, default="index", suffix=".html")
            page_path = output_dir / "pages" / page_name
            text_path = output_dir / "text" / f"{Path(page_name).stem}.txt"
            parsed = _extract_from_html(html, base_url=effective_page_url)
            resources = _extract_resources_from_html(html, base_url=effective_page_url)
            _write_text_artifact(page_path, html, context)
            _write_text_artifact(text_path, parsed["text"], context)
            page_record = {
                "url": page_url,
                "final_url": effective_page_url,
                "status_code": response.code,
                "content_type": content_type,
                "encoding": encoding,
                "title": parsed["title"],
                "html_path": str(page_path),
                "text_path": str(text_path),
                "html_relative_path": _relative_to(page_path, output_dir),
                "text_relative_path": _relative_to(text_path, output_dir),
                "link_count": len(resources["links"]),
                "asset_reference_count": len(resources["assets"]),
                "byte_count": len(response.body or b""),
                "truncated": len(response.body or b"") > MAX_BODY_BYTES,
            }
            pages.append(page_record)
            context.log("info", "site page collected", {"url": page_url, "status_code": response.code})

            if include_pages:
                for link in resources["links"]:
                    if len(page_queue) + len(seen_pages) >= max_pages:
                        break
                    if same_origin and _url_origin(link) not in allowed_origins:
                        continue
                    if link not in seen_pages and link not in page_queue:
                        page_queue.append(link)

            if include_assets:
                for asset in resources["assets"]:
                    if len(assets) >= max_assets:
                        break
                    asset_url = asset["url"]
                    if same_origin and _url_origin(asset_url) not in allowed_origins:
                        continue
                    if asset_url in seen_assets:
                        continue
                    seen_assets.add(asset_url)
                    asset_record = await _download_site_asset(
                        asset_url,
                        asset.get("kind", "asset"),
                        output_dir,
                        timeout=timeout,
                        validate_cert=validate_cert,
                        context=context,
                    )
                    assets.append(asset_record)
        except Exception as exc:
            failures.append({"url": page_url, "error": str(exc)[:500]})
            context.log("warning", "site page collection failed", {"url": page_url, "error": str(exc)[:300]})

    index = {
        "schema_version": "web_site_assets.v1",
        "url": url,
        "origin": root_origin,
        "collected_at": int(time.time()),
        "output_dir": str(output_dir),
        "settings": {
            "max_pages": max_pages,
            "max_assets": max_assets,
            "same_origin": same_origin,
            "include_pages": include_pages,
            "include_assets": include_assets,
        },
        "pages": pages,
        "assets": assets,
        "failures": failures,
        "counts": {
            "pages": len(pages),
            "assets": len(assets),
            "failures": len(failures),
        },
    }
    index_path = output_dir / "site-index.json"
    readme_path = output_dir / "README.md"
    _write_text_artifact(index_path, json.dumps(index, ensure_ascii=False, indent=2), context)
    _write_text_artifact(readme_path, _site_assets_readme(index), context)
    return {
        "type": "web_site_assets",
        "url": url,
        "output_dir": str(output_dir),
        "index_path": str(index_path),
        "readme_path": str(readme_path),
        "counts": index["counts"],
        "pages": pages[:12],
        "assets": assets[:20],
        "failures": failures[:10],
        "artifact_kind": "site_assets",
        "error": not pages,
        "message": "no pages collected" if not pages else "",
    }


async def capture_page(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    url = _validate_url(input_data.get("url"))
    output_path = _resolve_capture_output_path(input_data, context)
    capture_format = _capture_format(input_data.get("format"), output_path)
    timeout = max(1, min(int(input_data.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    wait_until = str(input_data.get("wait_until") or "networkidle").strip()
    if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
        wait_until = "networkidle"
    full_page = input_data.get("full_page", True) is not False
    ignore_https_errors = input_data.get("ignore_https_errors", True) is not False

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise ValueError("playwright is required for web.capture_page") from exc

    if callable(getattr(context, "backup_file", None)) and output_path.exists():
        context.backup_file(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=USER_AGENT,
            viewport={
                "width": int(input_data.get("width") or 1440),
                "height": int(input_data.get("height") or 1000),
            },
            ignore_https_errors=ignore_https_errors,
        )
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
            title = await page.title()
            if capture_format == "pdf":
                await page.pdf(
                    path=str(output_path),
                    format=str(input_data.get("paper_format") or "A4"),
                    print_background=input_data.get("print_background", True) is not False,
                )
            elif capture_format in {"png", "jpeg"}:
                await page.screenshot(path=str(output_path), full_page=full_page, type=capture_format)
            else:
                raise ValueError(f"unsupported capture format: {capture_format}")
            status_code = response.status if response else 0
        finally:
            await browser.close()

    context.log("info", "web page captured", {"url": url, "path": str(output_path)})
    return {
        "type": "web_page_capture",
        "url": url,
        "status_code": status_code,
        "title": title,
        "path": str(output_path),
        "format": capture_format,
        "size": output_path.stat().st_size,
        "artifact_kind": "pdf" if capture_format == "pdf" else "screenshot",
    }


def _extract_from_html(html: str, *, base_url: str = "") -> dict[str, Any]:
    parser = _TextExtractor(base_url=base_url)
    parser.feed(html or "")
    parser.close()
    return parser.result()


def _extract_resources_from_html(html: str, *, base_url: str = "") -> dict[str, Any]:
    parser = _HtmlResourceExtractor(base_url=base_url)
    parser.feed(html or "")
    parser.close()
    return {"links": parser.links, "assets": parser.assets}


async def _download_site_asset(
    url: str,
    kind: str,
    output_dir: Path,
    *,
    timeout: int,
    validate_cert: bool,
    context: Any,
) -> dict[str, Any]:
    try:
        response, effective_url = await _fetch_with_http_fallback(
            url,
            timeout=timeout,
            validate_cert=validate_cert,
        )
        body = response.body or b""
        if len(body) > MAX_BODY_BYTES:
            body = body[:MAX_BODY_BYTES]
        content_type = response.headers.get("Content-Type", "")
        filename = _safe_url_file_name(effective_url, default="asset", suffix=_suffix_for_asset(effective_url, content_type))
        asset_dir = output_dir / "assets" / _asset_group(kind, content_type)
        asset_path = asset_dir / filename
        _write_bytes_artifact(asset_path, body, context)
        context.log("info", "site asset collected", {"url": url, "status_code": response.code})
        return {
            "url": url,
            "final_url": effective_url,
            "kind": kind,
            "status_code": response.code,
            "content_type": content_type,
            "path": str(asset_path),
            "relative_path": _relative_to(asset_path, output_dir),
            "size": len(body),
            "truncated": len(response.body or b"") > MAX_BODY_BYTES,
        }
    except Exception as exc:
        context.log("warning", "site asset collection failed", {"url": url, "error": str(exc)[:300]})
        return {"url": url, "kind": kind, "status": "failure", "error": str(exc)[:500]}


def _resolve_output_dir(value: Any, context: Any) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("output_dir is required")
    path = context.path_guard.resolve(raw)
    return path


def _resolve_capture_output_path(input_data: dict[str, Any], context: Any) -> Path:
    output_path = str(input_data.get("output_path") or "").strip()
    if output_path:
        return context.path_guard.resolve(output_path)
    output_dir = str(input_data.get("output_dir") or "").strip()
    if not output_dir:
        raise ValueError("output_path or output_dir is required")
    directory = context.path_guard.resolve(output_dir)
    fmt = str(input_data.get("format") or "pdf").strip().lower() or "pdf"
    if fmt not in {"pdf", "png", "jpeg", "jpg"}:
        fmt = "pdf"
    suffix = ".jpg" if fmt == "jpg" else f".{fmt}"
    return directory / _safe_url_file_name(_validate_url(input_data.get("url")), default="page", suffix=suffix)


def _capture_format(value: Any, output_path: Path) -> str:
    fmt = str(value or "").strip().lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if not fmt:
        suffix = output_path.suffix.lower()
        fmt = {
            ".pdf": "pdf",
            ".png": "png",
            ".jpg": "jpeg",
            ".jpeg": "jpeg",
        }.get(suffix, "pdf")
    if fmt not in {"pdf", "png", "jpeg"}:
        raise ValueError("format must be pdf, png, or jpeg")
    return fmt


def _write_text_artifact(path: Path, content: str, context: Any) -> None:
    if callable(getattr(context, "backup_file", None)) and path.exists():
        context.backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes_artifact(path: Path, content: bytes, context: Any) -> None:
    if callable(getattr(context, "backup_file", None)) and path.exists():
        context.backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _safe_url_file_name(url: str, *, default: str, suffix: str = "") -> str:
    parsed = urlparse(url)
    stem = Path(parsed.path or "").name or default
    if "." in stem:
        base = Path(stem).stem
        existing_suffix = Path(stem).suffix
    else:
        base = stem
        existing_suffix = ""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-_") or default
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    final_suffix = suffix or existing_suffix or ".html"
    if final_suffix and not final_suffix.startswith("."):
        final_suffix = f".{final_suffix}"
    return f"{base}-{digest}{final_suffix}"


def _suffix_for_asset(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix
    if suffix:
        return suffix[:16]
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    guessed = mimetypes.guess_extension(mime) if mime else ""
    return guessed or ".bin"


def _asset_group(kind: str, content_type: str) -> str:
    text = f"{kind} {content_type}".lower()
    if "image" in text:
        return "images"
    if "css" in text or "stylesheet" in text:
        return "css"
    if "javascript" in text or "script" in text:
        return "js"
    if "font" in text:
        return "fonts"
    return "other"


def _url_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _site_assets_readme(index: dict[str, Any]) -> str:
    counts = index.get("counts") or {}
    lines = [
        "# Site Assets Snapshot",
        "",
        f"- Source URL: {index.get('url')}",
        f"- Pages: {counts.get('pages', 0)}",
        f"- Assets: {counts.get('assets', 0)}",
        f"- Failures: {counts.get('failures', 0)}",
        "",
        "## Pages",
    ]
    for page in index.get("pages") or []:
        title = str(page.get("title") or "(untitled)").strip()
        lines.append(f"- {title}: {page.get('url')} -> {page.get('html_relative_path')}")
    lines.extend(["", "## Assets"])
    for asset in index.get("assets") or []:
        if asset.get("status") == "failure":
            lines.append(f"- failed: {asset.get('url')} ({asset.get('error')})")
        else:
            lines.append(f"- {asset.get('kind')}: {asset.get('url')} -> {asset.get('relative_path')}")
    failures = index.get("failures") or []
    if failures:
        lines.extend(["", "## Failures"])
        for item in failures:
            lines.append(f"- {item.get('url')}: {item.get('error')}")
    return "\n".join(lines) + "\n"


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
            readiness_probe=playwright_chromium_readiness,
        ),
        render_page,
    )
    registry.register(
        ToolSpec(
            id="web.collect_site_assets",
            name="收集网站素材",
            description=(
                "受控抓取公开网站页面和静态资源，保存 HTML、正文、图片、CSS、JS 和 site-index.json。"
                "适合官网重设计、素材留档和页面内容归档；不要让模型用 filesystem.write_file 拼接大文件替代此工具。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "起始网站 URL，可传 www.example.com"},
                    "output_dir": {"type": "string", "description": "输出目录，必须在当前工作区内"},
                    "max_pages": {"type": "integer", "default": 8, "description": "最多抓取页面数，最大 50"},
                    "max_assets": {"type": "integer", "default": 60, "description": "最多下载素材数，最大 200"},
                    "same_origin": {"type": "boolean", "default": True, "description": "是否只收集同源链接和素材"},
                    "include_pages": {"type": "boolean", "default": True},
                    "include_assets": {"type": "boolean", "default": True},
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "validate_cert": {"type": "boolean", "default": True},
                },
                "required": ["url", "output_dir"],
            },
            requires_confirmation=True,
            local_only=False,
            capability="web.site_assets",
            artifacts=["site_assets", "html", "text", "image", "css", "js"],
            long_running=True,
            retry_safe=True,
        ),
        collect_site_assets,
    )
    registry.register(
        ToolSpec(
            id="web.capture_page",
            name="网页截图或 PDF",
            description=(
                "使用 Playwright 打开网页并导出 PDF、PNG 或 JPEG。适合保存网页快照、网页截图和设计参考文档。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要打开的网页 URL，可传 www.example.com"},
                    "output_path": {"type": "string", "description": "输出文件路径，扩展名可为 .pdf/.png/.jpg"},
                    "output_dir": {"type": "string", "description": "未传 output_path 时使用的输出目录"},
                    "format": {"type": "string", "enum": ["pdf", "png", "jpeg"], "default": "pdf"},
                    "wait_until": {"type": "string", "default": "networkidle"},
                    "timeout": {"type": "integer", "default": DEFAULT_TIMEOUT},
                    "width": {"type": "integer", "default": 1440},
                    "height": {"type": "integer", "default": 1000},
                    "full_page": {"type": "boolean", "default": True},
                    "ignore_https_errors": {"type": "boolean", "default": True},
                    "paper_format": {"type": "string", "default": "A4"},
                    "print_background": {"type": "boolean", "default": True},
                },
                "required": ["url"],
            },
            requires_confirmation=True,
            local_only=False,
            optional_dependencies=["playwright"],
            capability="web.page_capture",
            artifacts=["pdf", "screenshot"],
            long_running=True,
            retry_safe=True,
            readiness_probe=playwright_chromium_readiness,
        ),
        capture_page,
    )
