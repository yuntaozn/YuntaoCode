"""Fake tool runner for behaviour-driven testing.

Simulates tool execution without touching the real filesystem or shell.
Each tool can be configured to return success, failure, or a custom
callable result.
"""

from __future__ import annotations

from typing import Any, Callable


class FakeToolRunner:
    """Simulate tool execution with configurable outcomes.

    Parameters
    ----------
    outcomes : dict[str, str | Callable]
        Pre-configured outcomes keyed by tool ID.  Values can be:
        - ``"success"`` (default for unknown tools)
        - ``"failure"``
        - A callable ``(tool_id, arguments) -> dict`` for dynamic results.
    """

    def __init__(self, outcomes: dict[str, str | Callable] | None = None) -> None:
        self._outcomes: dict[str, str | Callable] = outcomes or {}
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def set_outcome(self, tool_id: str, status: str | Callable) -> None:
        self._outcomes[tool_id] = status

    async def run(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call and return a simulated result."""
        self.executed.append((tool_id, arguments))
        outcome = self._outcomes.get(tool_id, "success")
        if callable(outcome):
            return outcome(tool_id, arguments)
        if outcome == "failure":
            return {"status": "failure", "error": "simulated failure"}
        return {
            "status": "success",
            "output": {"path": arguments.get("path", "")},
        }

    @property
    def call_count(self) -> int:
        return len(self.executed)

    def calls_for(self, tool_id: str) -> list[dict[str, Any]]:
        """Return all argument dicts for calls to *tool_id*."""
        return [args for tid, args in self.executed if tid == tool_id]
