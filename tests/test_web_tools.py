from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.security import PathGuard
from runtime.skills.web import _validate_url
from runtime.skills.web import collect_site_assets


class _Headers(dict):
    def get_all(self) -> list[tuple[str, str]]:
        return list(self.items())


class _Response:
    def __init__(self, url: str, body: bytes, content_type: str = "text/html", code: int = 200) -> None:
        self.code = code
        self.reason = "OK"
        self.body = body
        self.headers = _Headers({"Content-Type": content_type, "Content-Length": str(len(body))})
        self.request = SimpleNamespace(url=url)


@dataclass
class _Context:
    path_guard: PathGuard

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        return None


def test_validate_url_accepts_http_and_https_urls() -> None:
    assert _validate_url("https://example.com/path") == "https://example.com/path"
    assert _validate_url("http://example.com") == "http://example.com"


def test_validate_url_normalizes_bare_public_host() -> None:
    assert _validate_url("www.syads.cn") == "https://www.syads.cn"
    assert _validate_url("example.com/path?q=1") == "https://example.com/path?q=1"


def test_validate_url_rejects_unsupported_schemes_and_non_urls() -> None:
    with pytest.raises(ValueError, match="only http and https"):
        _validate_url("file:///tmp/demo.txt")
    with pytest.raises(ValueError, match="only http and https"):
        _validate_url("not a url")


@pytest.mark.asyncio
async def test_collect_site_assets_writes_pages_assets_and_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    responses = {
        "http://example.com": _Response(
            "http://example.com",
            b"""
            <html><head><title>Home</title><link rel="stylesheet" href="/site.css"></head>
            <body><h1>Home</h1><a href="/about.html">About</a><img src="/logo.png"></body></html>
            """,
        ),
        "http://example.com/about.html": _Response(
            "http://example.com/about.html",
            b"<html><head><title>About</title></head><body>About text</body></html>",
        ),
        "http://example.com/site.css": _Response(
            "http://example.com/site.css",
            b"body { color: #111; }",
            "text/css",
        ),
        "http://example.com/logo.png": _Response(
            "http://example.com/logo.png",
            b"\x89PNG\r\n",
            "image/png",
        ),
    }

    async def fake_fetch(url: str, **kwargs):
        return responses[url]

    monkeypatch.setattr("runtime.skills.web._fetch", fake_fetch)

    result = await collect_site_assets(
        {
            "url": "http://example.com",
            "output_dir": str(workspace / "snapshot"),
            "max_pages": 2,
            "max_assets": 2,
        },
        _Context(PathGuard([workspace])),
    )

    output_dir = Path(result["output_dir"])
    index_path = Path(result["index_path"])
    assert result["counts"] == {"pages": 2, "assets": 2, "failures": 0}
    assert index_path.exists()
    assert (output_dir / "README.md").exists()
    assert len(list((output_dir / "pages").glob("*.html"))) == 2
    assert len(list((output_dir / "text").glob("*.txt"))) == 2
    assert len(list((output_dir / "assets").rglob("*.*"))) == 2


@pytest.mark.asyncio
async def test_collect_site_assets_falls_back_to_http_for_bare_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    called: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        called.append(url)
        if url.startswith("https://"):
            raise RuntimeError("certificate failed")
        return _Response(
            url,
            b"<html><head><title>Home</title></head><body>Home</body></html>",
        )

    monkeypatch.setattr("runtime.skills.web._fetch", fake_fetch)

    result = await collect_site_assets(
        {
            "url": "www.example.com",
            "output_dir": str(workspace / "snapshot"),
            "max_pages": 1,
            "max_assets": 0,
        },
        _Context(PathGuard([workspace])),
    )

    assert called == ["https://www.example.com", "http://www.example.com"]
    assert result["counts"]["pages"] == 1
    assert result["pages"][0]["final_url"] == "http://www.example.com"
