"""Runtime 结果的用户侧展示辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.agent_strategy import tool_event_roles as _event_roles
from runtime.agent_strategy.classifiers import strip_native_tool_call_blocks
from runtime.run_fact_summary import build_run_fact_summary


ToolEventPredicate = Callable[[dict[str, Any]], bool]
ToolEventMessage = Callable[[dict[str, Any]], str]
ToolEventPath = Callable[[str, dict[str, Any]], str]
ToolIdPredicate = Callable[[str], bool]
VerificationToolPredicate = Callable[[str, str | None], bool]
RelativePathFormatter = Callable[[str, Any], str]
AssistantClaimPredicate = Callable[[str], bool]


RISK_MESSAGES_ZH: dict[str, str] = {
    "expected_write_not_observed": "本轮没有观察到预期的写入结果。",
    "target_deliverable_not_observed": "没有观察到目标产物或目标外部状态变更。",
    "write_not_verified": "写入后没有观察到有效验证。",
    "deliverable_not_verified": "目标产物已出现，但还没有可靠验证。",
    "test_not_observed": "没有观察到测试、构建或语法检查成功。",
    "partial_write_failure": "同一轮既有写入成功，也有写入失败，产物可能不完整。",
    "partial_write_resumable": "部分写入失败，但已有成功产物可继续修正。",
    "deliverable_path_hint_changed": "最终产物路径与任务中的路径提示不一致，请确认是否符合预期。",
    "model_reported_goal_open": "模型在完成自审中明确报告目标仍未闭合。",
    "model_completion_assessment_inconsistent": "模型的完成自评同时声明目标已闭合和仍有剩余工作。",
    "execution_contract_failed": "本轮任务契约仍有证据缺口。",
    "max_rounds_exceeded": "当前执行预算已用完。",
    "repeated_tool_failure": "同一路线反复无新进展，需要换策略或检查环境。",
    "capability_preflight_advisory": "能力预检提示：当前环境可能缺少完成任务所需的工具或服务。",
    "model_provider_error": "模型服务返回错误或中断。",
    "invalid_tool_call_protocol": "模型输出了无效工具调用格式，这次无效调用没有进入执行。",
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
    "document_output_length_unknown": "无法确认文档输出长度，不应仅凭模型总结判断已完成。",
    "answer_output_too_short": "最终回答已生成，但实际长度少于任务契约中的目标。",
    "answer_output_length_unknown": "无法确认最终回答长度，回答型产物证据不完整。",
    "optional_write_not_verified": "可选写入结果没有验证。",
    "invalid_verification_method": "使用了无效的验证方式。",
    "runtime_verification_not_observed": "没有观察到可退出的运行时验证。",
    "artifact_integrity_invalid": "产物完整性检查未通过。",
    "shell_stderr_warning": "命令退出码为 0，但 stderr 出现异常或错误迹象，不能把它当作干净验证。",
    "capability_fallback_advisory": "工具选择偏离当前能力事实，需结合证据判断是否合理。",
    "document_contract_advisory": "文档任务存在覆盖率、进度或验证证据风险。",
    "verification_runtime_advisory": "验证方式证据偏弱，可能需要更明确的可退出验证。",
}


def risk_message_zh(risk: Any) -> str:
    code = str(risk or "").strip()
    return RISK_MESSAGES_ZH.get(code, code or "未知风险")


def run_status_from_result(run_result: dict[str, Any]) -> str:
    status = str(run_result.get("status") or "")
    if status == "stopped":
        return "stopped"
    if status == "failure":
        return "failure"
    if status == "partial":
        return "partial"
    return "success"


def answer_only_final_answer_error(
    content: str,
    tool_events: list[dict[str, Any]],
    task_contract: dict[str, Any] | None = None,
) -> str:
    """如有观察到，仅返回展示层的答案收尾缺口。"""

    if tool_events or not isinstance(task_contract, dict):
        return ""
    if str(task_contract.get("intent") or "") != "answer_only":
        return ""
    text = (content or "").strip()
    if not text or text == "模型没有返回内容。":
        return "model did not return a final answer"
    if strip_native_tool_call_blocks(text) != text:
        return "model returned unresolved tool call markup instead of a final answer"
    return ""


def needs_synthesized_final_answer(
    content: str,
    tool_events: list[dict[str, Any]],
    task_contract: dict[str, Any] | None = None,
) -> bool:
    """返回最终面向用户的答案是否需要运行时合成。"""

    text = (content or "").strip()
    if not tool_events:
        return bool(answer_only_final_answer_error(content, tool_events, task_contract))
    if not text or text == "模型没有返回内容。":
        return True
    if strip_native_tool_call_blocks(text) != text:
        return True
    return False


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
        "运行事实摘要：本轮观察到关键失败，当前结果应按失败事实处理。",
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
        "可继续依据：以上失败事实、风险记录和工具输出。",
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
        "运行事实摘要：本轮已有部分进展，但运行事实不足以证明目标已全部完成。",
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
        "可继续依据：已观察产物、验证事实、失败事实和风险记录。",
    ])
    return "\n".join(lines)


def build_max_rounds_after_write_message(
    max_rounds: int,
    tool_events: list[dict[str, Any]],
    *,
    is_write_tool: ToolIdPredicate,
) -> str:
    """已发生写入时构建中性的最大轮次提示。"""

    paths: list[str] = []
    for event in tool_events:
        if not is_write_tool(str(event.get("tool") or "")) or event.get("status") != "success":
            continue
        event_input = event.get("input")
        if isinstance(event_input, dict):
            path = event_input.get("path")
            if path:
                paths.append(str(path))
    unique_paths = list(dict.fromkeys(paths))
    lines = [
        f"运行事实摘要：本轮已有写入工具成功执行，当前工具执行预算已用完（{max_rounds} 轮）。",
        "完整性状态：本轮变更是否完整仍以工具记录、变更清单和验证证据为准。",
    ]
    if unique_paths:
        lines.append("")
        lines.append("已观察到的写入路径：")
        lines.extend(f"- {path}" for path in unique_paths[-8:])
    lines.append("")
    lines.append("可继续依据：上述写入路径、工具记录和后续验证事实。")
    return "\n".join(lines)


def build_execution_notice(
    mode: str | None,
    assistant_content: str,
    tool_events: list[dict[str, Any]],
    *,
    requires_code_write: bool = False,
    contract_failed: bool = False,
    max_rounds_exceeded: bool = False,
    run_result: dict[str, Any] | None = None,
    is_write_tool: ToolIdPredicate,
    is_invalid_verification_method_event: ToolEventPredicate,
    assistant_claims_code_changed: AssistantClaimPredicate,
) -> dict[str, Any] | None:
    """根据已观察运行时事实构建面向用户的执行提示。

    该提示属于展示证据，不判断任务意图、继续或停止策略，也不决定模型能否
    尝试其他路线。"""

    if mode not in {"coding", "terminal"}:
        return None

    write_successes = [
        event for event in tool_events
        if is_write_tool(str(event.get("tool") or "")) and event.get("status") == "success"
    ]
    write_failures = [
        event for event in tool_events
        if is_write_tool(str(event.get("tool") or "")) and event.get("status") == "failure"
    ]
    invalid_verification_failures = [
        event for event in tool_events
        if is_invalid_verification_method_event(event)
    ]
    claims_change = assistant_claims_code_changed(assistant_content)
    if write_successes and invalid_verification_failures:
        failed_tools = _notice_failed_tools(invalid_verification_failures)
        return {
            "reason": "invalid_verification_method",
            "message": "运行事实提示：本轮已观察到文件写入，同时观察到长驻服务命令被用作验证且未形成可退出验证结果。",
            "facts": [
                "write_observed",
                "invalid_verification_method_observed",
                "verification_result_not_observed",
            ],
            "failed_tools": failed_tools[:8],
            "tool_event_count": len(tool_events),
        }
    if write_successes and write_failures:
        failed_tools = _notice_failed_tools(write_failures)
        return {
            "reason": "partial_write_tool_failed",
            "message": "运行事实提示：本轮既有写入成功，也有写入失败；完整性需要结合变更清单和工具记录确认。",
            "facts": [
                "write_success_observed",
                "write_failure_observed",
            ],
            "failed_tools": failed_tools[:8],
            "tool_event_count": len(tool_events),
        }

    result_risks = run_result.get("risks") if isinstance(run_result, dict) else []
    if isinstance(result_risks, list) and "optional_write_not_verified" in result_risks:
        written_paths = run_result.get("observed_written_paths") if isinstance(run_result, dict) else []
        if not isinstance(written_paths, list):
            written_paths = []
        return {
            "reason": "optional_write_not_verified",
            "message": "运行事实提示：本轮已观察到本地文件写入，但没有观察到后续运行、预览或读取验证；当前状态为已修改、未验证。",
            "facts": [
                "write_observed",
                "verification_not_observed",
            ],
            "written_paths": [str(path) for path in written_paths[:8]],
            "tool_event_count": len(tool_events),
        }

    if write_successes:
        return None

    if not claims_change and not write_failures and not requires_code_write:
        return None

    failed_tools = _notice_failed_tools(write_failures)
    facts: list[str] = []
    if max_rounds_exceeded:
        message = "运行事实提示：本轮工具执行预算已用完，诊断信息已保存；实际变更仍以工具调用和变更清单为准。"
        reason = "max_tool_rounds"
        facts.append("tool_round_budget_exhausted")
    elif contract_failed:
        message = "运行事实提示：本轮未观察到成功的本地写入工具记录；实际文件是否变更仍以工具调用、变更清单和后续验证为准。"
        reason = "tool_contract_gap"
        facts.append("required_write_not_observed")
    elif write_failures:
        message = "运行事实提示：本轮代码写入工具执行失败，实际文件可能没有变更；失败原因见工具调用记录。"
        reason = "write_tool_failed"
        facts.append("write_failure_observed")
    elif tool_events:
        message = "运行事实提示：本轮没有成功执行任何代码写入工具，因此没有观察到本地文件变更证据。"
        reason = "no_successful_write_tool"
        facts.append("successful_write_not_observed")
    else:
        message = "运行事实提示：本轮没有任何本地工具调用记录，因此没有观察到本地文件变更证据。"
        reason = "no_tool_calls"
        facts.append("tool_call_not_observed")

    return {
        "reason": reason,
        "message": message,
        "facts": facts,
        "failed_tools": failed_tools[:8],
        "tool_event_count": len(tool_events),
    }


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
        _event_roles.task_verification_events(
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

    lines = ["运行事实摘要：模型最终回复停在待执行语句，已按真实工具记录收束本轮结果。"]
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
    """当运行时事实包含文件列表时，将其紧凑附加到最终答案。"""
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


def _notice_failed_tools(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tool": event.get("tool") or "",
            "name": event.get("name") or event.get("tool") or "",
            "path": ((event.get("input") or {}).get("path") if isinstance(event.get("input"), dict) else "") or "",
            "error": event.get("error") or "",
            "task_id": event.get("task_id") or "",
        }
        for event in events
    ]


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
