from __future__ import annotations

from typing import Any


def assess_tool_result_risks(
    tool_id: str,
    status: str,
    output: Any,
) -> list[dict[str, Any]]:
    """Return advisory risks discovered in a completed tool result.

    Risks are model-facing evidence and audit facts. They do not choose the
    model's next action and do not block later tool calls.
    """
    if status != "success" or not isinstance(output, dict):
        return []

    risks: list[dict[str, Any]] = []
    integrity = output.get("integrity")
    if isinstance(integrity, dict) and integrity.get("checked") is True and integrity.get("valid") is not True:
        issues = [
            str(issue).strip()
            for issue in integrity.get("issues") or []
            if str(issue).strip()
        ]
        risks.append({
            "code": "artifact_integrity_invalid",
            "severity": "warning",
            "source": tool_id,
            "path": str(output.get("path") or ""),
            "issues": issues,
            "action": "assess_before_state_change",
            "suggested_tools": ["filesystem.transform_text"],
            "blocking": False,
            "message": (
                "The inspected artifact has an integrity warning. Before changing local state, "
                "assess this evidence and choose whether to repair the artifact, continue with "
                "an explicit assumption, or stop and report the risk. Prefer a bounded local "
                "transformation over retransmitting the complete artifact."
            ),
        })
    return risks


def attach_tool_result_risks(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a payload copy with model-facing runtime risk evidence."""
    risks = assess_tool_result_risks(
        str(payload.get("tool") or ""),
        str(payload.get("status") or ""),
        payload.get("output"),
    )
    if not risks:
        return dict(payload)
    # Keep risks before potentially large output so compact transport cannot
    # truncate the advisory before the model sees it.
    return {"runtime_risks": risks, **payload}
