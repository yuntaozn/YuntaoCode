"""User-facing presentation for runtime result facts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.agent_strategy import tool_event_roles as _event_roles


ToolEventPredicate = Callable[[dict[str, Any]], bool]
ToolEventMessage = Callable[[dict[str, Any]], str]
ToolEventPath = Callable[[str, dict[str, Any]], str]
ToolIdPredicate = Callable[[str], bool]
VerificationToolPredicate = Callable[[str, str | None], bool]
RelativePathFormatter = Callable[[str, Any], str]


RISK_MESSAGES_ZH: dict[str, str] = {
    "expected_write_not_observed": "本轮没有观察到预期的写入结果。",
    "target_deliverable_not_observed": "没有观察到目标产物或目标外部状态变更。",
    "write_not_verified": "写入后没有观察到有效验证。",
    "deliverable_not_verified": "目标产物已出现，但还没有可靠验证。",
    "test_not_observed": "没有观察到测试、构建或语法检查成功。",
    "partial_write_failure": "同一轮既有写入成功，也有写入失败，产物可能不完整。",
    "partial_write_resumable": "部分写入失败，但已有成功产物可继续修正。",
    "deliverable_path_hint_changed": "最终产物路径与任务中的路径提示不一致，请确认是否符合预期。",
    "execution_contract_failed": "执行结果没有满足本轮任务契约。",
    "max_rounds_exceeded": "执行达到轮次上限。",
    "repeated_tool_failure": "同一类工具调用反复失败，需要换策略或人工检查环境。",
    "capability_preflight_blocked": "能力预检未通过，当前环境可能缺少完成任务所需的工具或服务。",
    "model_provider_error": "模型服务返回错误或中断。",
    "invalid_tool_call_protocol": "模型输出了无效工具调用格式，系统没有执行这次调用。",
    "invalid_final_answer": "模型最终回复与实际工具执行记录不一致。",
    "model_output_truncated": "模型输出被截断，结果可能不完整。",
    "recovered_tool_failure": "过程中有工具失败，但后续步骤曾尝试恢复。",
    "incidental_tool_failure": "存在非关键工具失败，请结合产物和验证结果判断影响。",
    "degraded_verification_failure": "验证工具失败，但可能不影响已生成产物本身。",
    "required_verification_not_satisfied": "没有满足任务要求的验证强度。",
    "verification_evidence_weak": "验证证据偏弱，不能充分证明任务已完成。",
    "visual_verification_not_observed": "任务需要视觉效果验证，但没有观察到截图、渲染图或页面捕获等视觉证据。",
    "verification_modality_missing": "已有验证证据，但验证形态不满足任务要求。",
    "document_output_coverage_low": "文档输出覆盖率过低：目标文件已生成，但内容明显少于源文档。",
    "document_output_too_short": "文档已导出，但实际内容字数少于用户要求。",
    "document_output_length_unknown": "无法确认文档输出长度，不能仅凭模型总结判断已完成。",
    "optional_write_not_verified": "可选写入结果没有验证。",
    "invalid_verification_method": "使用了无效的验证方式。",
    "runtime_verification_not_observed": "没有观察到可退出的运行时验证。",
    "artifact_integrity_invalid": "产物完整性检查未通过。",
}


def risk_message_zh(risk: Any) -> str:
    code = str(risk or "").strip()
    return RISK_MESSAGES_ZH.get(code, code or "未知风险")


def synthesize_failure_answer(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    run_result: dict[str, Any],
    *,
    tool_event_failed: ToolEventPredicate,
    tool_event_failure_message: ToolEventMessage,
    tool_event_display_path: ToolEventPath,
) -> str:
    failures = run_result.get("failures") if isinstance(run_result, dict) else []
    lines = [
        "未完成：本轮有工具执行失败，系统已按实际执行结果标记为失败。",
        "",
        "失败记录：",
    ]
    if isinstance(failures, list) and failures:
        for item in failures[:6]:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "unknown")
            path = str(item.get("path") or "").strip()
            error = str(item.get("error") or "工具执行失败").strip()
            label = f"{tool}（{path}）" if path else tool
            lines.append(f"- {label}: {error[:240]}")
    else:
        for event in tool_events:
            if not tool_event_failed(event):
                continue
            tool = str(event.get("tool") or "unknown")
            error = tool_event_failure_message(event)
            path = tool_event_display_path(workspace_path, event)
            label = f"{tool}（{path}）" if path else tool
            lines.append(f"- {label}: {error[:240]}")
    if len(lines) == 3:
        lines.append("- 工具返回失败，但没有提供详细错误信息。")

    risks = run_result.get("risks") if isinstance(run_result, dict) else []
    if isinstance(risks, list) and risks:
        lines.extend(["", "未满足条件/风险："])
        lines.extend(f"- {risk_message_zh(risk)}" for risk in risks[:8])
    lines.extend([
        "",
        "请根据上面的失败原因继续修正后再执行；不要以模型原始总结作为完成依据。",
    ])
    return "\n".join(lines)


def synthesize_partial_answer(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    run_result: dict[str, Any],
) -> str:
    del workspace_path, tool_events
    changed_paths = run_result.get("changed_paths") if isinstance(run_result, dict) else []
    failures = run_result.get("failures") if isinstance(run_result, dict) else []
    risks = run_result.get("risks") if isinstance(run_result, dict) else []
    counts = run_result.get("counts") if isinstance(run_result, dict) else {}
    lines = [
        "未完整完成：本轮已有部分操作成功，但系统检测到失败项或缺少可靠验证。",
    ]
    if isinstance(changed_paths, list) and changed_paths:
        lines.extend(["", "已变更文件："])
        lines.extend(f"- {path}" for path in changed_paths[:12])
    if isinstance(failures, list) and failures:
        lines.extend(["", "失败记录："])
        for item in failures[:6]:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "unknown")
            path = str(item.get("path") or "").strip()
            error = str(item.get("error") or "工具执行失败").strip()
            label = f"{tool}（{path}）" if path else tool
            lines.append(f"- {label}: {error[:240]}")
    if isinstance(risks, list) and risks:
        lines.extend(["", "仍需处理："])
        lines.extend(f"- {risk_message_zh(risk)}" for risk in risks[:8])
    if isinstance(counts, dict) and int(counts.get("test_successes") or 0) == 0:
        lines.extend([
            "",
            "结论：不能把本轮视为目标已完成；请基于现有变更继续修复并执行实际验证。",
        ])
    return "\n".join(lines)


def synthesize_final_answer(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    change_summary: dict[str, Any] | None,
    mode: str | None,
    task_contract: dict[str, Any] | None = None,
    *,
    is_write_tool: ToolIdPredicate,
    is_verification_tool: VerificationToolPredicate,
    relative_workspace_path: RelativePathFormatter,
    tool_event_failed: ToolEventPredicate,
    tool_event_failure_message: ToolEventMessage,
) -> str:
    write_paths: list[str] = []
    verify_lines: list[str] = []
    failure_lines: list[str] = []
    target_deliverables = (
        _event_roles.successful_deliverable_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        if isinstance(task_contract, dict)
        else []
    )
    target_verifications = (
        _event_roles.deliverable_verification_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        if isinstance(task_contract, dict)
        else []
    )
    external_deliverable_lines: list[str] = []
    for event in tool_events:
        tool_id = str(event.get("tool") or "")
        status = str(event.get("status") or "")
        event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        path = (
            output.get("path")
            or output.get("output_path")
            or event_input.get("output_path")
            or event_input.get("path")
            or ""
        )
        rel_path = relative_workspace_path(workspace_path, path) if path else ""
        display_path = rel_path or str(path or "")
        if is_write_tool(tool_id) and status == "success" and display_path:
            write_paths.append(display_path)
        if (
            is_verification_tool(tool_id, mode)
            or event in target_verifications
        ) and status == "success":
            detail = tool_id
            query = event_input.get("query")
            if query:
                detail += f"（搜索：{query}）"
            elif display_path:
                detail += f"（{display_path}）"
            verify_lines.append(detail)
        if event in target_deliverables and not display_path and status == "success":
            external_deliverable_lines.append(tool_id)
        if tool_event_failed(event):
            error = tool_event_failure_message(event)
            failure_lines.append(f"{tool_id}: {error[:160] if error else '失败'}")

    changed_paths = _changed_paths_from_summary(change_summary)
    if not changed_paths:
        changed_paths = list(dict.fromkeys(write_paths))
    write_paths = list(dict.fromkeys(write_paths))
    verify_lines = list(dict.fromkeys(verify_lines))
    external_deliverable_lines = list(dict.fromkeys(external_deliverable_lines))

    lines = ["系统检测到模型最终回复停在待执行语句，已按真实工具记录收束本轮结果。"]
    if changed_paths:
        lines.append("")
        lines.append("新增/变更文件：")
        lines.extend(f"- {path}" for path in changed_paths[:12])
    elif write_paths:
        lines.append("")
        lines.append("成功写入文件：")
        lines.extend(f"- {path}" for path in write_paths[:12])
    elif external_deliverable_lines:
        lines.append("")
        lines.append("已观察到目标外部状态变更：")
        lines.extend(f"- {item}" for item in external_deliverable_lines[:12])
    else:
        lines.append("")
        if isinstance(task_contract, dict) and task_contract.get("requires_state_change"):
            lines.append("本轮没有观察到成功完成目标外部状态变更。")
        else:
            lines.append("本轮没有观察到成功写入文件。")

    lines.append("")
    if verify_lines:
        lines.append("已执行验证：")
        lines.extend(f"- {item}" for item in verify_lines[:8])
    else:
        lines.append("未观察到成功验证工具调用。")

    if failure_lines:
        lines.append("")
        lines.append("失败或风险：")
        lines.extend(f"- {item}" for item in failure_lines[:6])
    return "\n".join(lines)


def _changed_paths_from_summary(change_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(change_summary, dict):
        return []
    changed_paths: list[str] = []
    for item in change_summary.get("files") or []:
        if isinstance(item, dict) and item.get("path"):
            changed_paths.append(str(item["path"]))
    return changed_paths
