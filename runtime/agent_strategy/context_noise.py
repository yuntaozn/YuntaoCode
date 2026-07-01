"""Classification and summaries for historical model-context noise."""

from __future__ import annotations

from dataclasses import dataclass


TOOL_MARKUP_TERMS: tuple[str, ...] = (
    "<toolcall",
    "</toolcall",
    "<|functioncall",
    "<|functioncallbegin",
    "functioncallbegin",
    "filesystem__",
    "code__",
    "document__",
    "shell__",
)

FAILED_RUN_TERMS: tuple[str, ...] = (
    "the run failed because",
    "failure records:",
    "required arguments are missing",
    "invalid tool calls will not enter confirmation",
    "no successful file write observed",
    "no successful verification tool call observed",
    "tool call failed",
    "tool execution failed",
    "\u672a\u5b8c\u6210",  # not completed
    "\u5931\u8d25\u8bb0\u5f55",  # failure records
    "\u5931\u8d25\u539f\u56e0",  # failure reason
    "\u5de5\u5177\u8c03\u7528\u7f3a\u5c11\u5fc5\u586b\u53c2\u6570",
    "\u65e0\u6548\u8c03\u7528",
    "\u672a\u89c2\u5bdf\u5230\u6210\u529f\u5199\u5165",
    "\u672a\u89c2\u5bdf\u5230\u6210\u529f\u9a8c\u8bc1",
)

PROCESS_LOG_TERMS: tuple[str, ...] = (
    "process log",
    "thinking process",
    "called tools",
    "tool call failed",
    "\u8fc7\u7a0b\u8bb0\u5f55",
    "\u601d\u8003\u8fc7\u7a0b",
    "\u5df2\u8c03\u7528",
    "\u8c03\u7528\u5931\u8d25",
)


@dataclass(frozen=True)
class ContextNoise:
    has_tool_markup: bool = False
    has_failed_run: bool = False
    has_process_log: bool = False


def classify_context_noise(text: str) -> ContextNoise:
    """Classify historical message noise without deciding current intent."""

    return ContextNoise(
        has_tool_markup=_contains_any(text, TOOL_MARKUP_TERMS),
        has_failed_run=_contains_any(text, FAILED_RUN_TERMS),
        has_process_log=_contains_any(text, PROCESS_LOG_TERMS),
    )


def historical_failure_summary(content: str, noise: ContextNoise) -> str:
    """Return a compact model-facing summary for historical failure noise."""

    facts: list[str] = [
        "[Historical run summary]",
        "An earlier run or assistant message contained failed execution details.",
    ]
    if noise.has_tool_markup:
        facts.append(
            "It included textual tool-call markup. Treat that markup as an "
            "invalid failure example, not as a tool-call format to imitate."
        )
    if noise.has_failed_run:
        facts.append(
            "If tools are needed in this turn, send one complete structured "
            "runtime tool call with all required arguments."
        )
    paths = _extract_path_lines(content)
    if paths:
        facts.append("Historical paths involved: " + "; ".join(paths[:4]))
    return "\n".join(facts)


def historical_process_summary() -> str:
    """Return a compact model-facing summary for a historical process log."""

    return (
        "[Historical process summary]\n"
        "An earlier message contained a long process log. Use only verified "
        "facts from the current Context Pack and current tool results."
    )


def historical_user_feedback_summary() -> str:
    """Return a compact summary for user-quoted historical process output."""

    return (
        "[Historical user feedback summary]\n"
        "An earlier user message quoted failed tool-call/process output. "
        "Do not reuse that historical format."
    )


def strip_tool_markup_like_text(text: str, max_chars: int) -> str:
    """Replace historical textual tool-call fragments before truncating."""

    cleaned = text
    for term in TOOL_MARKUP_TERMS:
        cleaned = cleaned.replace(term, "[historical tool markup]")
        cleaned = cleaned.replace(term.upper(), "[historical tool markup]")
    return truncate(cleaned, max_chars)


def truncate(text: str, max_chars: int) -> str:
    """Truncate a historical message to a bounded model-facing length."""

    max_chars = max(200, int(max_chars or 0))
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... historical message truncated ..."


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _extract_path_lines(text: str) -> list[str]:
    paths: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-* ").strip()
        if not line:
            continue
        if _contains_any(line, TOOL_MARKUP_TERMS):
            continue
        if "\\" in line or "/" in line or line.endswith((".html", ".py", ".js", ".md", ".docx")):
            if len(line) <= 220:
                paths.append(line)
    return paths
