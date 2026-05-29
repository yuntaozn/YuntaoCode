"""Backend i18n module for YuntaoCode.

Loads locale JSON files from runtime/locales/ and provides translation
functions for API handlers and system prompts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_LOCALES: dict[str, dict[str, str]] = {}
_DEFAULT_LANG = "zh-CN"
_LOCALES_DIR = Path(__file__).parent / "locales"


def load_locales() -> None:
    """Load all JSON translation files from the locales directory."""
    global _LOCALES
    _LOCALES = {}
    if not _LOCALES_DIR.is_dir():
        return
    for fp in _LOCALES_DIR.glob("*.json"):
        lang = fp.stem  # e.g. "zh-CN", "en"
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _LOCALES[lang] = data
        except (json.JSONDecodeError, OSError):
            continue


def get_lang(request: Any) -> str:
    """Extract language from request: ?lang= param or Accept-Language header."""
    # 1. Query param takes priority
    if hasattr(request, "get_argument"):
        try:
            lang = request.get_argument("lang", None)
            if lang and lang in _LOCALES:
                return lang
        except Exception:
            pass

    # 2. Accept-Language header
    if hasattr(request, "headers"):
        accept = request.headers.get("Accept-Language", "")
        if accept:
            # Parse first language tag
            match = re.match(r"([a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?)", accept)
            if match:
                tag = match.group(1)
                if tag in _LOCALES:
                    return tag
                # Try base language match (e.g. "en-US" -> "en")
                base = tag.split("-")[0]
                for available in _LOCALES:
                    if available.startswith(base):
                        return available

    return _DEFAULT_LANG


def t(key: str, lang: str = "", **kwargs: Any) -> str:
    """Translate a key. Supports {var} interpolation."""
    if not lang:
        lang = _DEFAULT_LANG
    locale = _LOCALES.get(lang, _LOCALES.get(_DEFAULT_LANG, {}))
    text = locale.get(key)
    if text is None:
        # Fallback to default locale
        text = _LOCALES.get(_DEFAULT_LANG, {}).get(key, key)
    if kwargs:
        for k, v in kwargs.items():
            text = text.replace("{" + k + "}", str(v))
    return text


# Auto-load on import
load_locales()
