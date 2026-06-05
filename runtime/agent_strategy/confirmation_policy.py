"""Pure confirmation-policy decisions for state-changing tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .classifiers import canonical_tool_id, is_state_changing_tool, is_write_tool


ConfirmationPolicy = Literal["conservative", "auto", "aggressive"]
ConfirmationDecisionValue = Literal["allow", "confirm"]
ToolRisk = Literal["read_only", "workspace_write", "privileged", "declared_state_change"]

VALID_CONFIRMATION_POLICIES: frozenset[str] = frozenset({
    "conservative",
    "auto",
    "aggressive",
})

PRIVILEGED_TOOL_IDS: frozenset[str] = frozenset({
    "shell.run_command",
    "git.commit",
})


@dataclass(frozen=True)
class ConfirmationDecision:
    decision: ConfirmationDecisionValue
    policy: str
    risk: ToolRisk
    reason: str

    @property
    def requires_confirmation(self) -> bool:
        return self.decision == "confirm"

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "decision": self.decision,
            "requires_confirmation": self.requires_confirmation,
            "policy": self.policy,
            "risk": self.risk,
            "reason": self.reason,
        }


def normalize_confirmation_policy(value: object, default: str = "auto") -> str:
    policy = str(value or "").strip().lower()
    if policy in VALID_CONFIRMATION_POLICIES:
        return policy
    fallback = str(default or "auto").strip().lower()
    return fallback if fallback in VALID_CONFIRMATION_POLICIES else "auto"


def classify_tool_risk(tool_id: str, *, declared_confirmation: bool = False) -> ToolRisk:
    canonical_id = canonical_tool_id(tool_id)
    if canonical_id in PRIVILEGED_TOOL_IDS:
        return "privileged"
    if is_write_tool(canonical_id):
        return "workspace_write"
    if declared_confirmation or is_state_changing_tool(canonical_id):
        return "declared_state_change"
    return "read_only"


def decide_tool_confirmation(
    policy: str,
    tool_id: str,
    *,
    declared_confirmation: bool = False,
) -> ConfirmationDecision:
    normalized = normalize_confirmation_policy(policy)
    risk = classify_tool_risk(tool_id, declared_confirmation=declared_confirmation)

    if risk == "read_only":
        return ConfirmationDecision("allow", normalized, risk, "read_only_tool")
    if normalized == "aggressive":
        return ConfirmationDecision("allow", normalized, risk, "aggressive_policy_allows_authorized_change")
    if normalized == "conservative":
        return ConfirmationDecision("confirm", normalized, risk, "conservative_policy_confirms_state_change")
    if risk == "workspace_write":
        return ConfirmationDecision("allow", normalized, risk, "auto_policy_allows_workspace_write")
    return ConfirmationDecision("confirm", normalized, risk, "auto_policy_confirms_privileged_or_unknown_change")
