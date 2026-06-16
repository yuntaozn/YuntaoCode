from __future__ import annotations

from typing import Any

from runtime.agent_strategy import classifiers as _clf
from runtime.agent_strategy import task_contract as _tc


WRITE_NOTICE_REASONS = {
    "tool_contract_failed",
    "write_tool_failed",
    "partial_write_tool_failed",
    "no_successful_write_tool",
    "max_tool_rounds",
    "optional_write_not_verified",
}


def is_runtime_guidance_message(message: Any) -> bool:
    metadata = getattr(message, "metadata", {}) or {}
    return bool(metadata.get("guidance") and metadata.get("during_run"))


def previous_write_context(conversation: Any | None, current_content: str) -> bool:
    if conversation is None:
        return False
    current = current_content.strip()
    for message in reversed(getattr(conversation, "messages", [])[-16:]):
        if is_runtime_guidance_message(message):
            continue
        role = str(getattr(message, "role", "") or "")
        previous_content = str(getattr(message, "content", "") or "")
        if previous_content.strip() == current:
            continue
        metadata = getattr(message, "metadata", {}) or {}
        if role == "user":
            if _clf.has_no_write_instruction(previous_content):
                return False
            if _clf.looks_like_code_change_request(previous_content):
                return True
            continue
        if role != "assistant" or not isinstance(metadata, dict):
            continue
        contract = metadata.get("task_contract")
        if isinstance(contract, dict) and contract.get("requires_write"):
            return True
        if metadata.get("task_intent") in {"write_required", "document_export"}:
            return True
        if metadata.get("code_change_intent") is True:
            return True
        change_summary = metadata.get("change_summary")
        if isinstance(change_summary, dict) and int(change_summary.get("file_count") or 0) > 0:
            return True
        execution_notice = metadata.get("execution_notice")
        if isinstance(execution_notice, dict) and execution_notice.get("reason") in WRITE_NOTICE_REASONS:
            return True
        execution_plan = metadata.get("execution_plan")
        if _clf.plan_has_pending_write_step(execution_plan):
            return True
        content_hint = previous_content.lower()
        if "继续" in content_hint and any(
            term in content_hint
            for term in ("优化", "修改", "写入", "创建", "未完成", "剩余", "页面", "seo")
        ):
            return True
    return False


def has_recent_task_context(conversation: Any | None, current_content: str) -> bool:
    """Return whether a short request belongs to an existing conversation task."""
    if conversation is None:
        return False
    current = current_content.strip()
    for message in reversed(getattr(conversation, "messages", [])[-12:]):
        if is_runtime_guidance_message(message):
            continue
        role = str(getattr(message, "role", "") or "")
        previous_content = str(getattr(message, "content", "") or "").strip()
        if role == "user" and previous_content and previous_content != current:
            return True
        if role != "assistant":
            continue
        metadata = getattr(message, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            continue
        contract = metadata.get("task_contract")
        if isinstance(contract, dict) and (
            contract.get("goal")
            or contract.get("intent") not in {None, "", "answer_only"}
        ):
            return True
    return False


def previous_task_contract_context(
    conversation: Any | None,
    current_content: str,
) -> dict[str, Any] | None:
    if conversation is None:
        return None
    current = current_content.strip()
    messages = list(getattr(conversation, "messages", [])[-20:])
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if is_runtime_guidance_message(message):
            continue
        role = str(getattr(message, "role", "") or "")
        previous_content = str(getattr(message, "content", "") or "").strip()
        if role == "user" and previous_content == current:
            continue
        if role != "assistant":
            continue
        metadata = getattr(message, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            continue
        contract = metadata.get("task_contract")
        if isinstance(contract, dict) and (
            contract.get("goal")
            or contract.get("intent") not in {None, "", "answer_only"}
        ):
            previous_user_content = ""
            for previous in reversed(messages[:index]):
                if is_runtime_guidance_message(previous):
                    continue
                if str(getattr(previous, "role", "") or "") != "user":
                    continue
                candidate = str(getattr(previous, "content", "") or "").strip()
                if candidate and candidate != current:
                    previous_user_content = candidate
                    break
            if (
                previous_user_content
                and _tc.looks_like_task_revision_followup(previous_user_content)
                and not contract.get("continuity_anchor")
                and contract.get("scope_relation_source") != "model"
            ):
                continue
            return contract
    return None


def previous_document_export_context(conversation: Any | None, current_content: str) -> bool:
    if conversation is None:
        return False
    current = current_content.strip()
    for message in reversed(getattr(conversation, "messages", [])[-16:]):
        if is_runtime_guidance_message(message):
            continue
        role = str(getattr(message, "role", "") or "")
        previous_content = str(getattr(message, "content", "") or "")
        if previous_content.strip() == current:
            continue
        metadata = getattr(message, "metadata", {}) or {}
        if role == "user":
            if _clf.has_no_write_instruction(previous_content):
                return False
            if _clf.looks_like_document_export_request(previous_content):
                return True
            continue
        if role != "assistant":
            continue
        if isinstance(metadata, dict):
            contract = metadata.get("task_contract")
            if isinstance(contract, dict) and contract.get("intent") == "document_export":
                return True
            if metadata.get("task_intent") == "document_export":
                return True
        content_hint = previous_content.lower()
        if "pdf" in content_hint and any(term in content_hint for term in ("word", "docx", "转存", "转换", "提取")):
            return True
    return False


def previous_full_document_output_context(conversation: Any | None, current_content: str) -> bool:
    if conversation is None:
        return False
    current = current_content.strip()
    for message in reversed(getattr(conversation, "messages", [])[-16:]):
        if is_runtime_guidance_message(message):
            continue
        role = str(getattr(message, "role", "") or "")
        previous_content = str(getattr(message, "content", "") or "")
        if previous_content.strip() == current:
            continue
        metadata = getattr(message, "metadata", {}) or {}
        if role == "user":
            if _clf.has_no_write_instruction(previous_content):
                return False
            if _clf.looks_like_full_document_output_request(previous_content):
                return True
            continue
        if role != "assistant" or not isinstance(metadata, dict):
            continue
        contract = metadata.get("task_contract")
        if isinstance(contract, dict) and contract.get("expected_document_coverage"):
            return True
    return False


def expects_full_document_output(content: str, conversation: Any | None = None) -> bool:
    if _clf.looks_like_full_document_output_request(content):
        return True
    text = content.strip().lower()
    if conversation is not None and len(text) < 80 and any(
        term in text
        for term in ("没看到", "没生成", "没成功", "上次", "再做", "再翻译", "继续")
    ):
        return previous_full_document_output_context(conversation, content)
    if _clf.looks_like_follow_up_execution(content):
        return previous_full_document_output_context(conversation, content)
    return False


def expected_min_output_chars(content: str, conversation: Any | None = None) -> int:
    direct = _clf.infer_requested_min_output_chars(content)
    if direct > 0:
        return direct
    if conversation is None:
        return 0
    text = content.strip().lower()
    if not (
        _clf.looks_like_follow_up_execution(content)
        or previous_document_export_context(conversation, content)
    ):
        return 0
    if len(text) >= 80 and not _clf.looks_like_follow_up_execution(content):
        return 0
    for message in reversed(getattr(conversation, "messages", [])[-16:]):
        if is_runtime_guidance_message(message):
            continue
        role = str(getattr(message, "role", "") or "")
        previous_content = str(getattr(message, "content", "") or "")
        if role == "user":
            inherited = _clf.infer_requested_min_output_chars(previous_content)
            if inherited > 0:
                return inherited
            continue
        metadata = getattr(message, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            continue
        contract = metadata.get("task_contract")
        if isinstance(contract, dict):
            try:
                inherited = int(contract.get("expected_min_output_chars") or 0)
            except (TypeError, ValueError):
                inherited = 0
            if inherited > 0:
                return inherited
    return 0


def classify_task_intent(
    content: str,
    mode: str | None,
    conversation: Any | None = None,
) -> str:
    if _clf.has_no_write_instruction(content):
        return "read_only_analysis"
    if _clf.looks_like_follow_up_execution(content) and previous_document_export_context(conversation, content):
        return "document_export"
    if _clf.looks_like_follow_up_execution(content) and previous_write_context(conversation, content):
        return "write_required"
    if _clf.user_requests_code_change(content, "coding"):
        return "write_required"
    if _clf.looks_like_document_export_request(content):
        return "document_export"
    if _clf.looks_like_paper_task(content):
        return "paper_workflow"
    if mode == "coding":
        if _clf.user_requests_code_change(content, mode):
            return "write_required"
        if _clf.looks_like_read_only_request(content):
            return "read_only_analysis"
        if _clf.looks_like_follow_up_execution(content) and conversation is not None:
            for message in reversed(getattr(conversation, "messages", [])[-8:]):
                if is_runtime_guidance_message(message):
                    continue
                if getattr(message, "role", "") != "user":
                    continue
                previous_content = str(getattr(message, "content", "") or "")
                if previous_content.strip() == content.strip():
                    continue
                if _clf.has_no_write_instruction(previous_content):
                    return "read_only_analysis"
                if _clf.user_requests_code_change(previous_content, "coding"):
                    return "write_required"
        return "answer_only"
    if _clf.looks_like_read_only_request(content):
        return "read_only_analysis"
    return "answer_only"


def effective_mode(
    requested_mode: str | None,
    content: str,
    conversation: Any | None = None,
) -> str:
    if requested_mode == "coding":
        return "coding"
    if requested_mode == "paper":
        return "paper"
    if _clf.looks_like_follow_up_execution(content) and previous_document_export_context(conversation, content):
        return "document"
    if _clf.looks_like_follow_up_execution(content) and previous_write_context(conversation, content):
        return "coding"
    if _clf.user_requests_code_change(content, "coding"):
        return "coding"
    if _clf.looks_like_paper_task(content):
        return "paper"
    if _clf.looks_like_follow_up_execution(content) and conversation is not None:
        for message in reversed(getattr(conversation, "messages", [])[-8:]):
            if is_runtime_guidance_message(message):
                continue
            if getattr(message, "role", "") != "user":
                continue
            previous_content = str(getattr(message, "content", "") or "")
            if previous_content.strip() == content.strip():
                continue
            if _clf.user_requests_code_change(previous_content, "coding"):
                return "coding"
            if _clf.looks_like_paper_task(previous_content):
                return "paper"
    if _clf.looks_like_document_export_request(content):
        return "document"
    return requested_mode or "terminal"


def code_change_intent(
    content: str,
    mode: str | None,
    conversation: Any | None = None,
) -> bool:
    if _clf.has_no_write_instruction(content):
        return False
    if _clf.user_requests_code_change(content, mode):
        return True
    if _clf.looks_like_follow_up_execution(content) and previous_write_context(conversation, content):
        return True
    if mode != "coding" or not _clf.looks_like_follow_up_execution(content):
        return False
    if conversation is None:
        return False
    for message in reversed(getattr(conversation, "messages", [])[-8:]):
        if is_runtime_guidance_message(message):
            continue
        if getattr(message, "role", "") != "user":
            continue
        previous_content = str(getattr(message, "content", "") or "")
        if previous_content.strip() == content.strip():
            continue
        if _clf.has_no_write_instruction(previous_content):
            return False
        if _clf.looks_like_code_change_request(previous_content) or _clf.user_requests_code_change(previous_content, "coding"):
            return True
    return False
