"""User-facing presentation for runtime result facts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.agent_strategy import tool_event_roles as _event_roles
from runtime.run_fact_summary import build_run_fact_summary


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
    "repeated_tool_failure": "同一类工具调用反复失败，需要换策略或检查环境。",
    "capability_preflight_blocked": "能力预检未通过，当前环境可能缺少完成任务所需的工具或服务。",
    "model_provider_error": "模型服务返回错误或中断。",
    "invalid_tool_call_protocol": "模型输出了无效工具调用格式，系统没有执行这次调用。",
    "invalid_final_answer": "模型最终回复与实际工具执行记录不一致。",
    "model_output_truncated": "模型输出被截断，结果可能不完整。",
    "recovered_tool_failure": "过程中有工具失败，但后续步骤曾尝试恢复。",
    "incidental_tool_failure": "存在非关键工具失败，请结合产物和验证结果判断影响。",
    "degraded_verification_failure": "验证工具失败，可能不影响已生成产物本身，但会降低完成可信度。",
    "required_verification_not_satisfied": "没有满足任务要求的验证强度。",
    "verification_evidence_weak": "验证证据偏弱，不能充分证明任务已完成。",
    "visual_verification_not_observed": "任务需要视觉效果验证，但没有观察到截图、渲染图或页面捕获等证据。",
    "verification_modality_missing": "已有验证证据，但验证形式不满足任务要求。",
    "document_output_coverage_low": "文档输出覆盖率过低：目标文件已生成，但内容明显少于源文档。",
    "document_output_too_short": "文档已导出，但实际内容字数少于用户要求。",
    "document_output_length_unknown": "无法确认文档输出长度，不能仅凭模型总结判断已完成。",
    "optional_write_not_verified": "可选写入结果没有验证。",
    "invalid_verification_method": "使用了无效的验证方式。",
    "runtime_verification_not_observed": "没有观察到可退出的运行时验证。",
    "artifact_integrity_invalid": "产物完整性检查未通过。",
    "shell_stderr_warning": "命令退出码为 0，但 stderr 出现异常或错误迹象，不能把它当作干净验证。",
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
    summary = build_run_fact_summary(
        workspace_path=workspace_path,
        tool_events=tool_events,
        run_result=run_result,
    )
    failures = summary.get("failures") if isinstance(summary.get("failures"), list) else []
    lines = [
        "未完成：本轮有阻断性失败，系统已按真实工具记录标记为失败。",
        "",
        "失败事实：",
    ]
    if failures:
        for item in failures[:8]:
            if not isinstance(item, dict):
                continue
            label = _label_with_path(item.get("tool"), item.get("path"))
            error = str(item.get("error") or item.get("reason") or "工具执行失败").strip()
            impact = str(item.get("impact") or "").strip()
            suffix = f"（影响：{impact}）" if impact else ""
            lines.append(f"- {label}{suffix}: {_short(error, 240)}")
    else:
        for event in tool_events:
            if not tool_event_failed(event):
                continue
            label = _label_with_path(
                event.get("tool"),
                tool_event_display_path(workspace_path, event),
            )
            lines.append(f"- {label}: {_short(tool_event_failure_message(event), 240)}")
    if len(lines) == 3:
        lines.append("- 工具返回失败，但没有提供详细错误信息。")
    _append_risks(lines, summary.get("risks"))
    lines.extend([
        "",
        "结论：不能把本轮视为目标已完成。请根据失败事实换策略、补参数、修正环境，或在确实无法继续时如实说明边界。",
    ])
    return "\n".join(lines)


def synthesize_partial_answer(
    workspace_path: str,
    tool_events: list[dict[str, Any]],
    run_result: dict[str, Any],
) -> str:
    summary = build_run_fact_summary(
        workspace_path=workspace_path,
        tool_events=tool_events,
        run_result=run_result,
    )
    lines = [
        "未完整完成：本轮已有部分进展，但运行事实不足以证明目标已全部完成。",
    ]
    _append_list(lines, "已观察到的产物/变更", summary.get("written_paths") or summary.get("changed_paths"))
    verification = summary.get("verification")
    if isinstance(verification, list) and verification:
        lines.append("")
        lines.append("已观察到的验证：")
        for item in verification[:8]:
            if not isinstance(item, dict):
                continue
            modalities = ", ".join(str(v) for v in item.get("modalities") or [] if v)
            suffix = f"（{modalities}）" if modalities else ""
            lines.append(f"- {item.get('tool') or 'unknown'}{suffix}")
    failures = summary.get("failures")
    if isinstance(failures, list) and failures:
        lines.append("")
        lines.append("失败事实：")
        for item in failures[:8]:
            if not isinstance(item, dict):
                continue
            label = _label_with_path(item.get("tool"), item.get("path"))
            error = str(item.get("error") or item.get("reason") or "工具执行失败").strip()
            impact = str(item.get("impact") or "").strip()
            suffix = f"（影响：{impact}）" if impact else ""
            lines.append(f"- {label}{suffix}: {_short(error, 240)}")
    _append_risks(lines, summary.get("risks"))
    lines.extend([
        "",
        "结论：不能把本轮视为目标已完成；下一轮应基于这些事实继续修正或补充验证，而不是复述模型原始总结。",
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
            failure_lines.append(f"{tool_id}: {_short(error or '失败', 160)}")

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


def append_changed_files_footer(
    content: str,
    run_result: dict[str, Any] | None,
    change_summary: dict[str, Any] | None = None,
    *,
    limit: int = 20,
) -> str:
    """Append a compact file list to a final answer when runtime facts have one."""
    text = str(content or "").rstrip()
    paths = _changed_file_footer_paths(run_result, change_summary)
    if not text or not paths or _has_file_footer(text):
        return str(content or "")

    zh = _looks_chinese(text)
    title = "本轮新增/变更文件：" if zh else "Files changed this turn:"
    omitted = len(paths) - max(0, limit)
    visible = paths[: max(0, limit)]
    lines = ["", "", title]
    lines.extend(f"- {path}" for path in visible)
    if omitted > 0:
        lines.append(f"- 另有 {omitted} 个文件未显示" if zh else f"- {omitted} more files omitted")
    return text + "\n".join(lines)


def _append_risks(lines: list[str], risks: Any) -> None:
    items = [risk_message_zh(item) for item in risks or [] if str(item or "").strip()]
    _append_list(lines, "仍需注意", items)


def _append_list(lines: list[str], title: str, values: Any) -> None:
    items = [str(item).strip() for item in values or [] if str(item or "").strip()]
    if not items:
        return
    lines.append("")
    lines.append(f"{title}：")
    lines.extend(f"- {_short(item, 260)}" for item in items[:12])


def _label_with_path(tool: Any, path: Any) -> str:
    tool_text = str(tool or "unknown").strip()
    path_text = str(path or "").strip()
    return f"{tool_text}（{path_text}）" if path_text else tool_text


def _changed_paths_from_summary(change_summary: dict[str, Any] | None) -> list[str]:
    if not isinstance(change_summary, dict):
        return []
    changed_paths: list[str] = []
    for item in change_summary.get("files") or []:
        if isinstance(item, dict) and item.get("path"):
            changed_paths.append(str(item["path"]))
    return changed_paths


def _changed_file_footer_paths(
    run_result: dict[str, Any] | None,
    change_summary: dict[str, Any] | None,
) -> list[str]:
    paths: list[str] = []
    paths.extend(_changed_paths_from_summary(change_summary))
    if isinstance(run_result, dict):
        for key in (
            "changed_paths",
            "target_written_paths",
            "observed_written_paths",
            "written_paths",
        ):
            value = run_result.get(key)
            if isinstance(value, list):
                paths.extend(str(item) for item in value if str(item or "").strip())
        artifacts = run_result.get("artifacts")
        if isinstance(artifacts, list):
            for item in artifacts:
                if isinstance(item, dict) and item.get("path"):
                    paths.append(str(item["path"]))
    return list(dict.fromkeys(path.strip() for path in paths if path and path.strip()))


def _has_file_footer(content: str) -> bool:
    markers = (
        "本轮新增/变更文件",
        "新增/变更文件",
        "已观察到的产物/变更",
        "Files changed this turn",
        "Changed files",
        "New/changed files",
    )
    return any(marker in content for marker in markers)


def _looks_chinese(content: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in content)


def _short(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"
