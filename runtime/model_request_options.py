from __future__ import annotations

from typing import Any


RUNTIME_OWNED_REQUEST_KEYS = frozenset({
    "model",
    "input",
    "instructions",
    "messages",
    "stream",
    "stream_options",
    "tools",
    "tool_choice",
    "thinking",
    "enable_thinking",
    "reasoning_effort",
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
})


def sanitize_request_options(value: Any) -> dict[str, Any]:
    """返回不包含 Runtime 自有字段的用户或 Provider 请求扩展参数。

    请求参数是 Provider 特有扩展的逃生口，但不得重新定义由 Runtime 管理的
    结构化 model、tool、thinking、streaming 或输出预算字段。"""

    if not isinstance(value, dict):
        return {}
    return {
        str(key): option
        for key, option in value.items()
        if str(key) not in RUNTIME_OWNED_REQUEST_KEYS
    }


def blocked_request_option_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        str(key)
        for key in value
        if str(key) in RUNTIME_OWNED_REQUEST_KEYS
    )
