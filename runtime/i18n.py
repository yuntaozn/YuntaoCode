"""YuntaoCode 后端国际化模块。

从 runtime/locales/ 加载语言 JSON 文件，并为 API 处理器和系统提示
提供翻译函数。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_LOCALES: dict[str, dict[str, str]] = {}
_DEFAULT_LANG = "zh-CN"
_LOCALES_DIR = Path(__file__).parent / "locales"


def load_locales() -> None:
    """从 locales 目录加载全部 JSON 翻译文件。"""
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
    """从请求的 ?lang 参数或 Accept-Language 请求头中提取语言。"""
    # 1. 查询参数优先
    if hasattr(request, "get_argument"):
        try:
            lang = request.get_argument("lang", None)
            if lang and lang in _LOCALES:
                return lang
        except Exception:
            pass

    # 2. Accept-Language 请求头
    if hasattr(request, "headers"):
        accept = request.headers.get("Accept-Language", "")
        if accept:
            # 解析第一个语言标签
            match = re.match(r"([a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?)", accept)
            if match:
                tag = match.group(1)
                if tag in _LOCALES:
                    return tag
                # 尝试匹配基础语言，例如 "en-US" -> "en"
                base = tag.split("-")[0]
                for available in _LOCALES:
                    if available.startswith(base):
                        return available

    return _DEFAULT_LANG


def t(key: str, lang: str = "", **kwargs: Any) -> str:
    """翻译键值，支持 {var} 插值。"""
    if not lang:
        lang = _DEFAULT_LANG
    locale = _LOCALES.get(lang, _LOCALES.get(_DEFAULT_LANG, {}))
    text = locale.get(key)
    if text is None:
        # 回退到默认语言
        text = _LOCALES.get(_DEFAULT_LANG, {}).get(key, key)
    if kwargs:
        for k, v in kwargs.items():
            text = text.replace("{" + k + "}", str(v))
    return text


# 导入模块时自动加载
load_locales()
