from __future__ import annotations

import re
from pathlib import Path


TEXT_ENCODING_CANDIDATES = ("utf-8", "gb18030", "gbk")
WEB_TEXT_EXTENSIONS = {".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".svg"}

_HTML_CHARSET_RE = re.compile(r"<meta\s+[^>]*charset\s*=", re.IGNORECASE)
_UTF8_MOJIBAKE_RE = re.compile(
    r"(?:"
    r"[\u0080-\u009f]|"
    r"Ã[\u0080-\u00ff]|"
    r"Â[\u0080-\u00ff]|"
    r"â[\u0080-\u00ff]|"
    r"[æåèçä][\u0080-\u00ff]"
    r")"
)


def detect_text_encoding(raw: bytes) -> str:
    """Detect a local text file encoding by validating the whole byte payload."""
    if not raw:
        return "utf-8"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in TEXT_ENCODING_CANDIDATES:
        try:
            raw.decode(encoding)
            return encoding
        except (UnicodeDecodeError, ValueError):
            continue
    return "latin-1"


def read_text_with_encoding(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    encoding = detect_text_encoding(raw)
    return raw.decode(encoding, errors="replace"), encoding


def write_text_with_encoding(path: Path, text: str, encoding: str) -> str:
    target_encoding = encoding or "utf-8"
    try:
        path.write_text(text, encoding=target_encoding)
        return target_encoding
    except (LookupError, UnicodeEncodeError):
        path.write_text(text, encoding="utf-8")
        return "utf-8"


def looks_like_utf8_mojibake(text: str) -> bool:
    return bool(_UTF8_MOJIBAKE_RE.search(str(text or "")))


def text_encoding_risks(path: Path, text: str, encoding: str = "") -> list[dict[str, str]]:
    value = str(text or "")
    risks: list[dict[str, str]] = []
    if looks_like_utf8_mojibake(value):
        risks.append({
            "code": "utf8_mojibake_suspected",
            "message": "文本中出现疑似 UTF-8 被按 ANSI/Latin-1 解码后的乱码片段。",
        })

    suffix = path.suffix.lower()
    has_non_ascii = any(ord(char) > 127 for char in value)
    if suffix in {".html", ".htm"} and has_non_ascii:
        head = value[:4096]
        if not _HTML_CHARSET_RE.search(head):
            risks.append({
                "code": "html_charset_missing",
                "message": "HTML 包含非 ASCII 文本但前部未声明 charset，浏览器可能按错误编码解析。",
            })
    if suffix in WEB_TEXT_EXTENSIONS - {".html", ".htm"} and has_non_ascii:
        risks.append({
            "code": "web_text_asset_non_ascii",
            "message": "网页脚本/样式资源包含非 ASCII 文本，运行验证应确认页面以 UTF-8 解析。",
        })
    if (encoding or "").lower() == "latin-1" and has_non_ascii:
        risks.append({
            "code": "latin1_fallback_encoding",
            "message": "文件只能按 Latin-1 兜底解码，后续编辑前应确认真实编码。",
        })
    return risks
