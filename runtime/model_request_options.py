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
    """Return user/provider request extras without runtime-owned fields.

    Request options are an escape hatch for provider-specific extras. They must
    not redefine the structured model, tool, thinking, streaming, or output
    budget fields owned by the runtime.
    """

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
