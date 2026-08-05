from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from runtime.tool_aliases import normalize_tool_id


NO_ACTION = "none"
REPORT_REPETITION = "report_repetition"
ESCALATE_NO_PROGRESS = "escalate_no_progress"


@dataclass(frozen=True)
class ExecutionConvergenceDecision:
    """当前无进展窗口中观察到的收敛状态。

    这是执行形态证据，不是 Planner。Runtime 可根据 action 决定事实提示强度；
    其余内容作为事实交给模型选择其他路线。全局轮次上限仍是资源边界。"""

    action: str = NO_ACTION
    latest_tool: str = ""
    latest_reason: str = ""
    latest_boundary: str = ""
    route_attempt_count: int = 0
    consecutive_failure_count: int = 0
    distinct_failed_routes: int = 0
    no_progress_event_count: int = 0
    budget_limit_route_attempts: int = 0
    route_changed_without_progress: bool = False
    latest_missing_fields: tuple[str, ...] = field(default_factory=tuple)
    latest_signature: str = ""
    model_decision: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "latest_tool": self.latest_tool,
            "latest_reason": self.latest_reason,
            "latest_boundary": self.latest_boundary,
            "route_attempt_count": self.route_attempt_count,
            "consecutive_failure_count": self.consecutive_failure_count,
            "distinct_failed_routes": self.distinct_failed_routes,
            "no_progress_event_count": self.no_progress_event_count,
            "budget_limit_route_attempts": self.budget_limit_route_attempts,
            "route_changed_without_progress": self.route_changed_without_progress,
            "latest_missing_fields": list(self.latest_missing_fields),
            "latest_signature": self.latest_signature,
            "model_decision": list(self.model_decision),
        }


def build_execution_convergence_decision(
    tool_events: list[dict[str, Any]],
    *,
    base_budget_limit_route_attempts: int = 9,
    max_budget_limit_route_attempts: int = 15,
) -> ExecutionConvergenceDecision:
    """返回自最近一次进展后重复失败的收敛证据。

    预算由进展驱动：

    - 任一成功或部分成功的工具结果都会重置无进展窗口；
    - 改变路线视为自我纠偏证据，并扩大有界预算；
    - 局部预算饱和时提高证据提示强度，但不选择下一策略，也不裁定任务结果。"""

    events = [item for item in tool_events or [] if isinstance(item, dict)]
    latest = events[-1] if events else {}
    if latest.get("status") != "failure":
        return ExecutionConvergenceDecision()

    window = _events_since_last_progress(events)
    failure_events = [event for event in window if event.get("status") == "failure"]
    latest_signature = failure_route_signature(latest)
    latest_tool = normalize_tool_id(str(latest.get("tool") or ""))
    latest_output = latest.get("output") if isinstance(latest.get("output"), dict) else {}
    latest_observation = _tool_attempt_observation(latest)
    latest_reason = str(
        latest_output.get("reason")
        or latest_observation.get("reason")
        or ""
    ).strip()
    latest_boundary = str(latest_observation.get("boundary") or "").strip()
    missing_fields = tuple(_string_items(latest_observation.get("missing_fields"), limit=8))
    route_attempt_count = sum(
        1
        for event in failure_events
        if failure_route_signature(event) == latest_signature
    )
    consecutive_count = consecutive_repeated_failure_count(events)
    distinct_routes = _distinct_failure_route_count(failure_events)
    route_changed = distinct_routes > 1
    budget_limit = _budget_limit_attempts(
        base_budget_limit_route_attempts,
        max_budget_limit_route_attempts,
        distinct_routes,
    )
    if route_attempt_count < 2:
        action = NO_ACTION
    elif route_attempt_count >= budget_limit:
        action = ESCALATE_NO_PROGRESS
    else:
        action = REPORT_REPETITION
    return ExecutionConvergenceDecision(
        action=action,
        latest_tool=latest_tool,
        latest_reason=latest_reason,
        latest_boundary=latest_boundary,
        route_attempt_count=route_attempt_count,
        consecutive_failure_count=consecutive_count,
        distinct_failed_routes=distinct_routes,
        no_progress_event_count=len(window),
        budget_limit_route_attempts=budget_limit,
        route_changed_without_progress=route_changed,
        latest_missing_fields=missing_fields,
        latest_signature=latest_signature,
        model_decision=tuple(_model_decision(
            latest_tool=latest_tool,
            latest_reason=latest_reason,
            route_attempt_count=route_attempt_count,
            budget_limit_route_attempts=budget_limit,
            route_changed=route_changed,
            missing_fields=missing_fields,
        )),
    )


def repeated_failure_action(tool_events: list[dict[str, Any]]) -> str:
    return build_execution_convergence_decision(tool_events).action


def consecutive_repeated_failure_count(tool_events: list[dict[str, Any]]) -> int:
    signature = ""
    count = 0
    for event in reversed(tool_events or []):
        if not isinstance(event, dict) or event.get("status") != "failure":
            break
        event_signature = failure_route_signature(event)
        if not signature:
            signature = event_signature
        if event_signature != signature:
            break
        count += 1
    return count


def failure_route_attempt_count_since_progress(tool_events: list[dict[str, Any]]) -> int:
    decision = build_execution_convergence_decision(tool_events)
    return decision.route_attempt_count


def failure_route_signature(event: dict[str, Any]) -> str:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    observation = _tool_attempt_observation(event)
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    reason = str(output.get("reason") or observation.get("reason") or "").strip().lower()
    error = _normalized_error(event.get("error") or output.get("message") or output.get("error"))
    signature = {
        "tool": normalize_tool_id(str(event.get("tool") or "")),
        "reason": reason,
        "boundary": str(observation.get("boundary") or "").strip().lower(),
        "error": error,
        "input": _input_signature(event_input),
    }
    return json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def format_convergence_decision(decision: ExecutionConvergenceDecision) -> str:
    if decision.action == NO_ACTION:
        return ""
    lines = [
        "Execution convergence facts:",
        f"- action: {decision.action}",
        f"- latest tool: {decision.latest_tool or 'unknown'}",
        f"- latest reason: {decision.latest_reason or 'unknown'}",
        f"- route attempts in no-progress window: {decision.route_attempt_count}/{decision.budget_limit_route_attempts}",
        f"- distinct failed routes in no-progress window: {decision.distinct_failed_routes}",
    ]
    if decision.latest_boundary:
        lines.append(f"- latest boundary: {decision.latest_boundary}")
    if decision.latest_missing_fields:
        lines.append("- latest missing fields: " + ", ".join(decision.latest_missing_fields))
    if decision.route_changed_without_progress:
        lines.append("- route changes were observed, but no successful or partial tool progress followed yet")
    if decision.model_decision:
        lines.append("- model decision:")
        lines.extend(f"  - {item}" for item in decision.model_decision)
    return "\n".join(lines)


def _events_since_last_progress(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    window: list[dict[str, Any]] = []
    for event in reversed(events):
        if _is_progress_event(event):
            break
        window.append(event)
    return list(reversed(window))


def _is_progress_event(event: dict[str, Any]) -> bool:
    return str(event.get("status") or "") in {"success", "partial"}


def _distinct_failure_route_count(events: list[dict[str, Any]]) -> int:
    return len({
        failure_route_signature(event)
        for event in events
        if isinstance(event, dict) and event.get("status") == "failure"
    })


def _budget_limit_attempts(base: int, maximum: int, distinct_routes: int) -> int:
    base_value = max(3, int(base or 0))
    max_value = max(base_value, int(maximum or base_value))
    extra = max(0, distinct_routes - 1) * 2
    return min(max_value, base_value + extra)


def _tool_attempt_observation(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("tool_attempt_observation")
    if isinstance(value, dict):
        return value
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    value = output.get("observation")
    return value if isinstance(value, dict) else {}


def _input_signature(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"keys": sorted(str(key) for key in value.keys())[:24]}
    for key in ("path", "output_path", "cwd", "root", "query", "command", "draft_id"):
        if value.get(key) not in (None, ""):
            result[key] = _short(value.get(key), 240)
    args = value.get("args")
    if isinstance(args, list):
        result["args"] = [_short(item, 160) for item in args[:12]]
        result["args_count"] = len(args)
    for key in ("content", "patch", "old_text", "new_text", "old_string", "new_string"):
        if isinstance(value.get(key), str):
            text = value[key]
            result[key] = {
                "chars": len(text),
                "hash": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16],
            }
    return result


def _normalized_error(value: Any) -> str:
    text = " ".join(str(value or "").lower().split())
    if not text:
        return ""
    return _short(text, 400)


def _model_decision(
    *,
    latest_tool: str,
    latest_reason: str,
    route_attempt_count: int,
    budget_limit_route_attempts: int,
    route_changed: bool,
    missing_fields: tuple[str, ...],
) -> list[str]:
    decisions = [
        "Use this as convergence evidence, not as a task route chosen by the runtime.",
    ]
    if missing_fields:
        decisions.append(
            "If retrying the same tool, supply the missing fields first: "
            + ", ".join(missing_fields)
            + "."
        )
    elif latest_reason in {"truncated_tool_call", "model_output_truncated"}:
        decisions.append(
            "If retrying a write-like route, use smaller complete chunks or an incremental edit path."
        )
    else:
        decisions.append(
            "Choose whether to change tool, change arguments, gather context, verify existing output, ask the user, or stop honestly."
        )
    if route_changed:
        decisions.append(
            "Different failed routes were observed; keep the next action materially tied to new evidence instead of cycling."
        )
    remaining = max(0, budget_limit_route_attempts - route_attempt_count)
    if remaining:
        decisions.append(f"Repeated latest-route budget remaining in this no-progress window: {remaining}.")
    else:
        decisions.append(
            "The latest-route repetition budget is saturated; this is evidence for a materially different repair, verification, or boundary decision."
        )
    if latest_tool:
        decisions.append(f"Latest route under observation: {latest_tool}.")
    return decisions


def _string_items(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _short(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"
