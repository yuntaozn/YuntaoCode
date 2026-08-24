"""感知任务契约的工具事件角色。

工具 ID 告诉 Runtime 某项操作是否可能改变本地状态，但不能单独说明它是否满足用户目标。
本模块结合模型声明的任务契约，以及路径和输出等运行时事实，将工具事件映射为任务角色。"""

from __future__ import annotations

import json
from typing import Any

from .classifiers import (
    canonical_tool_id,
    is_meaningful_verification_event,
    is_structural_verification_event,
    is_test_verification_event,
    is_write_tool,
)
from .tool_result_risks import (
    SHELL_STDERR_WARNING_CODE,
    shell_success_has_stderr_warning,
)


DELIVERABLE = "deliverable"
EVIDENCE = "evidence"
DRAFT = "draft"
TEMPORARY = "temporary"
VERIFICATION = "verification"
STATE_CHANGE = "state_change"
UNKNOWN = "unknown"
EXTERNAL_STATE_CHANGE = "external_state_change"
VERIFICATION_STRENGTHS: tuple[str, ...] = ("none", "weak", "standard", "strong")
VERIFICATION_MODALITIES: tuple[str, ...] = ("structural", "visual", "behavioral", "content")
VISUAL_ARTIFACT_KINDS: frozenset[str] = frozenset({
    "screenshot",
    "image",
    "render",
    "rendered_image",
    "viewport_screenshot",
    "visual_capture",
    "pdf",
})
ARTIFACT_DELIVERABLE_KINDS: frozenset[str] = frozenset({
    "artifact",
    "image",
    "screenshot",
    "render",
    "rendered_image",
    "viewport_screenshot",
    "visual_capture",
    "preview",
    "pdf",
})
ARTIFACT_EFFECTS: frozenset[str] = frozenset({
    "artifact_write",
    "artifact_create",
    "artifact_update",
})


LEGACY_TOOL_ROLE_HINTS: dict[str, frozenset[str]] = {
    "filesystem.create_text_draft": frozenset({DRAFT}),
    "filesystem.append_text_chunk": frozenset({DRAFT}),
    "filesystem.inspect_text_draft": frozenset({DRAFT, EVIDENCE}),
    "document.create_draft": frozenset({DRAFT}),
    "document.append_draft_section": frozenset({DRAFT}),
    "document.add_draft_citation": frozenset({DRAFT}),
    "document.inspect_draft": frozenset({DRAFT, EVIDENCE}),
    "filesystem.write_temp_file": frozenset({TEMPORARY}),
    "attachment.extract_text": frozenset({EVIDENCE}),
    "code.list_project_files": frozenset({EVIDENCE}),
    "code.search_text": frozenset({EVIDENCE}),
    "filesystem.scan_folder": frozenset({EVIDENCE}),
    "filesystem.read_file": frozenset({EVIDENCE}),
    "filesystem.read_text_preview": frozenset({EVIDENCE}),
    "document.extract_docx_outline": frozenset({EVIDENCE}),
    "document.extract_pdf_text_preview": frozenset({EVIDENCE}),
    "spreadsheet.inspect_workbook": frozenset({EVIDENCE}),
    "web.extract_text": frozenset({EVIDENCE}),
    "web.render_page": frozenset({EVIDENCE}),
    "web.collect_site_assets": frozenset({EVIDENCE}),
}


def classify_tool_event_role(
    event: dict[str, Any],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
    deliverable_paths: set[str] | None = None,
) -> str:
    """返回该事件在当前任务中承担的角色。"""
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    paths = event_path_hints(event)
    contract_paths = deliverable_paths or contract_deliverable_paths(task_contract)
    effects = event_effects(event)
    intended_roles = event_intended_roles(event)
    deliverable_kinds = contract_deliverable_kinds(task_contract)

    if DRAFT in intended_roles:
        return DRAFT
    if TEMPORARY in intended_roles:
        return TEMPORARY

    if paths and contract_paths and any(_path_matches_any(path, contract_paths) for path in paths):
        if (
            _status_is_success_or_partial(event)
            and _can_be_deliverable_for_contract(event, task_contract)
        ):
            return DELIVERABLE
        if _is_verification_event(event, mode, written_paths=contract_paths):
            return VERIFICATION

    if (
        _status_is_success_or_partial(event)
        and EXTERNAL_STATE_CHANGE in effects
        and (
            "external_state" in deliverable_kinds
            or (
                isinstance(task_contract, dict)
                and task_contract.get("requires_state_change")
                and not task_contract.get("requires_write")
            )
        )
    ):
        return DELIVERABLE

    if (
        _status_is_success_or_partial(event)
        and _contract_expects_artifact(task_contract)
        and _can_be_deliverable_for_contract(event, task_contract)
        and (not contract_paths or _contract_allows_alternative_path(event, task_contract))
    ):
        return DELIVERABLE
    if VERIFICATION in event_observed_roles(event) and _status_is_success_or_partial(event):
        return VERIFICATION
    if EVIDENCE in intended_roles:
        return EVIDENCE

    if _status_is_success_or_partial(event) and _can_be_deliverable_for_contract(event, task_contract):
        if not contract_paths or _contract_allows_alternative_path(event, task_contract):
            return DELIVERABLE
        return STATE_CHANGE
    if _is_verification_event(event, mode, written_paths=contract_paths):
        return VERIFICATION
    return UNKNOWN


def successful_deliverable_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    contract_paths = contract_deliverable_paths(task_contract)
    return [
        event
        for event in tool_events
        if str(event.get("status") or "") in {"success", "partial"}
        and classify_tool_event_role(
            event,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
            deliverable_paths=contract_paths,
        ) == DELIVERABLE
    ]


def failed_deliverable_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    contract_paths = contract_deliverable_paths(task_contract)
    result: list[dict[str, Any]] = []
    for event in tool_events:
        if str(event.get("status") or "") != "failure":
            continue
        if not _can_be_intended_deliverable_for_contract(event, task_contract):
            continue
        paths = event_path_hints(event)
        if (
            not contract_paths
            or _contract_allows_alternative_path(event, task_contract)
            or (paths and any(_path_matches_any(path, contract_paths) for path in paths))
        ):
            result.append(event)
    return result


def deliverable_verification_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    deliverables = successful_deliverable_events(
        tool_events,
        task_contract=task_contract,
        workspace_path=workspace_path,
        mode=mode,
    )
    if not deliverables:
        return []

    deliverable_ids = {id(event) for event in deliverables}
    deliverable_indexes = [
        index for index, event in enumerate(tool_events)
        if id(event) in deliverable_ids
    ]
    latest_index = max(deliverable_indexes)
    deliverable_paths = contract_deliverable_paths(task_contract)
    for event in deliverables:
        deliverable_paths.update(event_path_hints(event))

    latest_deliverables = _latest_deliverables_by_path(tool_events, deliverable_ids)
    candidates = [*latest_deliverables, *tool_events[latest_index:]]
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for event in candidates:
        event_id = id(event)
        if event_id in seen:
            continue
        seen.add(event_id)
        if _is_verification_event(event, mode, written_paths=deliverable_paths):
            result.append(event)
    return result


def _latest_deliverables_by_path(
    tool_events: list[dict[str, Any]],
    deliverable_ids: set[int],
) -> list[dict[str, Any]]:
    """为每个已观察产物路径保留最新交付事件。"""

    latest: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, event in enumerate(tool_events):
        if id(event) not in deliverable_ids:
            continue
        paths = event_path_hints(event)
        keys = paths or {"__pathless_deliverable__"}
        for path in keys:
            latest[path] = (index, event)
    unique = {id(event): (index, event) for index, event in latest.values()}
    return [event for index, event in sorted(unique.values(), key=lambda item: item[0])]


def sufficient_deliverable_verification_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    required = required_verification_strength(task_contract)
    candidates = [
        event
        for event in deliverable_verification_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        if verification_strength_meets(
            verification_evidence_strength(
                event,
                mode=mode,
                task_contract=task_contract,
            ),
            required,
        )
    ]
    required_modalities = required_verification_modalities(task_contract)
    if not required_modalities:
        return candidates
    observed_modalities: set[str] = set()
    for event in candidates:
        observed_modalities.update(
            verification_evidence_modalities(
                event,
                mode=mode,
                task_contract=task_contract,
            )
        )
    if set(required_modalities).issubset(observed_modalities):
        return candidates
    return []


def task_verification_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """返回任务契约的验证证据。

    写入或状态变更任务在交付物出现后验证已观察目标。仅验证任务（例如“检查上一改动
    是否有效”）在验证前没有新交付物，此时直接对照当前任务契约评估证据工具。"""

    deliverable_events = deliverable_verification_events(
        tool_events,
        task_contract=task_contract,
        workspace_path=workspace_path,
        mode=mode,
    )
    if deliverable_events or not _is_verification_only_contract(task_contract):
        return deliverable_events
    if _is_answer_evidence_contract(task_contract):
        return [
            event
            for event in tool_events
            if _is_answer_evidence_event(event, mode, task_contract=task_contract)
        ]
    return [
        event
        for event in tool_events
        if _is_verification_event(event, mode, written_paths=event_path_hints(event))
    ]


def verification_attempt_events(
    tool_events: list[dict[str, Any]],
    *,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """返回已尝试的验证动作，包括未成功证据。

    尝试历史只属于诊断证据，不得用作任务已经验证的证明。"""

    result: list[dict[str, Any]] = []
    for event in tool_events:
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        if (
            VERIFICATION in event_intended_roles(event)
            or _event_has_visual_artifact(event)
            or bool(output.get("runtime_diagnostics"))
            or is_test_verification_event(event)
            or is_structural_verification_event(event)
        ):
            result.append(event)
    return result


def sufficient_task_verification_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    required = required_verification_strength(task_contract)
    candidates = [
        event
        for event in task_verification_events(
            tool_events,
            task_contract=task_contract,
            workspace_path=workspace_path,
            mode=mode,
        )
        if verification_strength_meets(
            verification_evidence_strength(
                event,
                mode=mode,
                task_contract=task_contract,
            ),
            required,
        )
    ]
    required_modalities = required_verification_modalities(task_contract)
    if not required_modalities:
        return candidates
    observed_modalities: set[str] = set()
    for event in candidates:
        observed_modalities.update(
            verification_evidence_modalities(
                event,
                mode=mode,
                task_contract=task_contract,
            )
        )
    if set(required_modalities).issubset(observed_modalities):
        return candidates
    return []


def successful_task_evidence_events(
    tool_events: list[dict[str, Any]],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """返回为当前任务提供证据的成功事件。

    任务证据事件比目标交付物范围更广。对写入或外部状态任务，它包括已观察目标交付物
    及其验证证据；对只读和答案证据任务，即使没有产物路径可标为交付物，也包括成功的
    证据收集工具。"""

    result: list[dict[str, Any]] = []
    seen: set[int] = set()

    for event in successful_deliverable_events(
        tool_events,
        task_contract=task_contract,
        workspace_path=workspace_path,
        mode=mode,
    ):
        seen.add(id(event))
        result.append(event)

    for event in task_verification_events(
        tool_events,
        task_contract=task_contract,
        workspace_path=workspace_path,
        mode=mode,
    ):
        event_id = id(event)
        if event_id in seen:
            continue
        seen.add(event_id)
        result.append(event)

    if _is_answer_evidence_contract(task_contract):
        for event in tool_events:
            event_id = id(event)
            if event_id in seen:
                continue
            if _is_answer_evidence_event(event, mode, task_contract=task_contract):
                seen.add(event_id)
                result.append(event)

    return result


def required_verification_strength(task_contract: dict[str, Any] | None) -> str:
    if not isinstance(task_contract, dict) or not task_contract.get("requires_verification"):
        return "none"
    value = str(task_contract.get("required_verification_strength") or "standard").strip().lower()
    return value if value in VERIFICATION_STRENGTHS else "standard"


def required_verification_modalities(task_contract: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(task_contract, dict) or not task_contract.get("requires_verification"):
        return ()
    values = task_contract.get("required_verification_modalities")
    if not isinstance(values, list):
        return ()
    result: list[str] = []
    for item in values:
        text = str(item or "").strip().lower()
        if text in VERIFICATION_MODALITIES and text not in result:
            result.append(text)
    return tuple(result)


def verification_evidence_strength(
    event: dict[str, Any],
    *,
    mode: str | None = None,
    task_contract: dict[str, Any] | None = None,
) -> str:
    """返回成功事件验证任务目标的证据强度。

    Provider 可以明确声明强度。未声明时，真实测试或构建检查为强证据，其他有意义验证
    为标准证据。仅声明 verification 角色时为兼容按标准强度处理；粗略检查应声明 ``weak``。"""
    if not _status_is_success_or_partial(event):
        return "none"
    if _event_has_degraded_shell_stderr(event):
        return "none"
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if _event_has_runtime_errors(event):
        return "none"
    explicit = str(
        event.get("verification_strength")
        or event.get("declared_verification_strength")
        or output.get("verification_strength")
        or ""
    ).strip().lower()
    if explicit in VERIFICATION_STRENGTHS:
        if (
            explicit == "weak"
            and _is_structured_external_state_verification(
                event,
                task_contract=task_contract,
            )
        ):
            return "standard"
        return explicit
    if is_structural_verification_event(event):
        return "standard"
    if is_test_verification_event(event):
        return "strong"
    if _event_has_visual_artifact(event):
        return "standard"
    if _is_answer_evidence_event(event, mode, task_contract=task_contract):
        return "standard"
    if VERIFICATION in event_observed_roles(event):
        return "standard"
    if is_meaningful_verification_event(event, mode, written_paths=event_path_hints(event)):
        return "standard"
    return "none"


def verification_evidence_modalities(
    event: dict[str, Any],
    *,
    mode: str | None = None,
    task_contract: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    if verification_evidence_strength(event, mode=mode, task_contract=task_contract) == "none":
        return ()
    modalities: list[str] = []
    if _event_has_visual_artifact(event):
        modalities.append("visual")
    if is_test_verification_event(event):
        modalities.append("behavioral")
    elif _event_has_behavioral_interaction(event):
        modalities.append("behavioral")
    elif is_structural_verification_event(event):
        modalities.append("structural")
    elif _event_has_structural_artifact_evidence(event):
        modalities.append("structural")
    if _is_structured_external_state_verification(event, task_contract=task_contract):
        modalities.append("structural")
    if _event_has_content_artifact(event):
        modalities.append("content")
    if not modalities:
        modalities.append("structural")
    return tuple(dict.fromkeys(modalities))


def missing_required_verification_modalities(
    events: list[dict[str, Any]],
    task_contract: dict[str, Any] | None,
    *,
    mode: str | None = None,
) -> tuple[str, ...]:
    required = required_verification_modalities(task_contract)
    if not required:
        return ()
    observed: set[str] = set()
    for event in events:
        observed.update(
            verification_evidence_modalities(
                event,
                mode=mode,
                task_contract=task_contract,
            )
        )
    return tuple(item for item in required if item not in observed)


def _is_structured_external_state_verification(
    event: dict[str, Any],
    *,
    task_contract: dict[str, Any] | None,
) -> bool:
    if "external_state" not in contract_deliverable_kinds(task_contract):
        return False
    if VERIFICATION not in event_intended_roles(event):
        return False
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if not output:
        return False
    for key in ("structured_content", "structuredContent", "data", "state", "scene", "objects"):
        if _value_contains_state_fact(output.get(key)):
            return True
    content = output.get("content")
    if _value_contains_state_fact(content):
        return True
    mcp_content = output.get("mcp_content")
    if _value_contains_state_fact(mcp_content):
        return True
    return _mapping_has_state_fact(output)


def _event_has_visual_artifact(event: dict[str, Any]) -> bool:
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    artifact_values = [
        event.get("artifact_kind"),
        output.get("artifact_kind"),
        output.get("format"),
    ]
    visual_artifact_path = ""
    visual_evidence = output.get("visual_evidence")
    if isinstance(visual_evidence, dict):
        artifact = visual_evidence.get("artifact")
        if isinstance(artifact, dict):
            visual_artifact_path = str(artifact.get("path") or "")
            artifact_values.extend([
                artifact.get("kind"),
                artifact.get("format"),
            ])
    for values in (event.get("artifacts"), output.get("artifacts")):
        if isinstance(values, list):
            artifact_values.extend(values)
    normalized = {str(item or "").strip().lower() for item in artifact_values if str(item or "").strip()}
    if normalized & VISUAL_ARTIFACT_KINDS:
        return True
    if _path_looks_visual_artifact(visual_artifact_path):
        return True
    if any(_path_looks_visual_artifact(path) for path in event_path_hints(event)):
        return True
    visual_tool_terms = (
        "screenshot",
        "capture_page",
        "capture_screenshot",
        "viewport_screenshot",
        "render_image",
        "render_view",
    )
    return any(term in tool_id for term in visual_tool_terms)


def _event_has_artifact(event: dict[str, Any]) -> bool:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    artifact_values = [
        event.get("artifact_kind"),
        output.get("artifact_kind"),
    ]
    for values in (event.get("artifacts"), output.get("artifacts")):
        if isinstance(values, list):
            artifact_values.extend(values)
    normalized = {
        str(item or "").strip().lower()
        for item in artifact_values
        if str(item or "").strip()
    }
    if normalized & (ARTIFACT_DELIVERABLE_KINDS | {"visual_evidence", "pdf_page_render"}):
        return bool(event_path_hints(event) or _event_has_visual_artifact(event))
    visual_evidence = output.get("visual_evidence")
    if isinstance(visual_evidence, dict) and visual_evidence.get("kind") == "visual_evidence":
        return True
    if ARTIFACT_EFFECTS & event_effects(event):
        return bool(event_path_hints(event))
    return _event_has_visual_artifact(event)


def _contract_expects_artifact(task_contract: dict[str, Any] | None) -> bool:
    return bool(contract_deliverable_kinds(task_contract) & ARTIFACT_DELIVERABLE_KINDS)


def _event_has_runtime_errors(event: dict[str, Any]) -> bool:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    visual_evidence = output.get("visual_evidence")
    if isinstance(visual_evidence, dict):
        runtime = visual_evidence.get("runtime")
        if isinstance(runtime, dict) and runtime.get("has_errors") is True:
            return True
    return output.get("has_runtime_errors") is True


def _event_has_behavioral_interaction(event: dict[str, Any]) -> bool:
    if canonical_tool_id(str(event.get("tool") or "")) != "preview.interact_page":
        return False
    if _event_has_runtime_errors(event):
        return False
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    interaction = output.get("interaction")
    if not isinstance(interaction, dict):
        return False
    try:
        action_count = int(interaction.get("action_count") or 0)
        failed_count = int(interaction.get("assertion_failed_count") or 0)
    except (TypeError, ValueError):
        return False
    return action_count > 0 and failed_count == 0


def _path_looks_visual_artifact(path: str) -> bool:
    lower = str(path or "").strip().lower()
    return lower.endswith((
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".pdf",
    ))


def _event_has_content_artifact(event: dict[str, Any]) -> bool:
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if tool_id in {
        "code.search_text",
        "filesystem.read_file",
        "filesystem.read_text_preview",
        "spreadsheet.inspect_workbook",
    }:
        return True
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if str(output.get("type") or "").strip().lower() == "spreadsheet_preview":
        return True
    if _event_has_content_measure(output):
        return True
    artifact_values = [output.get("artifact_kind")]
    if isinstance(output.get("artifacts"), list):
        artifact_values.extend(output.get("artifacts") or [])
    normalized = {str(item or "").strip().lower() for item in artifact_values if str(item or "").strip()}
    if normalized & {
        "text",
        "text_file",
        "document_text",
        "dom_text",
        "html",
        "markdown",
        "page_text",
    }:
        return True
    if _shell_command_inspects_text_content(event):
        return True
    return tool_id == "preview.interact_page" and bool(str(output.get("text") or "").strip())


def _event_has_structural_artifact_evidence(event: dict[str, Any]) -> bool:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    validation = output.get("validation") if isinstance(output.get("validation"), dict) else {}
    if validation.get("valid") is True:
        return True
    integrity = output.get("integrity") if isinstance(output.get("integrity"), dict) else {}
    if integrity.get("checked") is True and integrity.get("valid") is True:
        return True
    if _event_has_runtime_structure_evidence(event):
        return True
    return _shell_command_inspects_text_content(event)


def _event_has_runtime_structure_evidence(event: dict[str, Any]) -> bool:
    if _event_has_runtime_errors(event):
        return False
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if _successful_http_status(output.get("status_code")):
        return True
    resources = output.get("resource_responses")
    if isinstance(resources, list) and any(
        isinstance(item, dict) and _successful_http_status(item.get("status"))
        for item in resources
    ):
        return True
    dom_snapshot = output.get("dom_snapshot")
    if isinstance(dom_snapshot, dict):
        ready_state = str(dom_snapshot.get("ready_state") or "").strip().lower()
        if ready_state in {"interactive", "complete"}:
            return True
        for key in ("title", "body_text", "headings", "buttons", "body_text_chars"):
            if dom_snapshot.get(key) not in (None, "", [], {}, 0):
                return True
    debug_session = output.get("debug_session")
    if isinstance(debug_session, dict):
        if str(debug_session.get("status") or "").strip().lower() == "success":
            return True
        service = debug_session.get("service")
        if isinstance(service, dict) and _successful_http_status(service.get("status_code")):
            return True
        try:
            if int(debug_session.get("exit_code", 1) or 1) == 0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _successful_http_status(value: Any) -> bool:
    try:
        status = int(value or 0)
    except (TypeError, ValueError):
        return False
    return 200 <= status < 400


def _event_has_content_measure(output: dict[str, Any]) -> bool:
    validation = output.get("validation") if isinstance(output.get("validation"), dict) else {}
    draft_stats = output.get("draft_stats") if isinstance(output.get("draft_stats"), dict) else {}
    for source in (output, validation, draft_stats):
        for key in (
            "content_chars",
            "text_chars",
            "character_count",
            "char_count",
            "word_count",
            "line_count",
            "paragraph_count",
            "nonempty_paragraph_count",
        ):
            if _positive_int(source.get(key)):
                return True
    return False


def _shell_command_inspects_text_content(event: dict[str, Any]) -> bool:
    if canonical_tool_id(str(event.get("tool") or "")) != "shell.run_command":
        return False
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if output.get("timed_out") is True or shell_success_has_stderr_warning(output):
        return False
    try:
        if int(output.get("exit_code", 0) or 0) != 0:
            return False
    except (TypeError, ValueError):
        return False
    stdout = str(output.get("stdout") or "").strip()
    if not stdout:
        return False
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    command = str(event_input.get("command") or "").strip().lower()
    args = event_input.get("args") if isinstance(event_input.get("args"), list) else []
    combined = f"{command} {' '.join(str(item).lower() for item in args)}"
    content_markers = (
        "get-content",
        "read-text",
        "read_text",
        "readfile",
        "read_file",
        "readfilesync",
        "open(",
        ".read(",
        "cat ",
        "type ",
        "wc ",
        "measure-object",
        ".length",
        "len(",
        "content.length",
        "text.length",
    )
    if not any(marker in combined for marker in content_markers):
        return False
    return _command_mentions_text_like_target(combined)


def _command_mentions_text_like_target(command: str) -> bool:
    text_suffixes = (
        ".txt",
        ".md",
        ".markdown",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".py",
        ".json",
        ".yaml",
        ".yml",
        ".csv",
        ".xml",
        ".docx",
        ".pdf",
    )
    return any(suffix in command for suffix in text_suffixes)


def _positive_int(value: Any) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False


_STATE_FACT_META_KEYS: frozenset[str] = frozenset({
    "call_timeout",
    "content",
    "artifact_kind",
    "artifacts",
    "effects",
    "error",
    "format",
    "message",
    "mcp_content",
    "path",
    "paths",
    "roles",
    "status",
    "structured_content",
    "structuredContent",
    "verification_strength",
})


def _mapping_has_state_fact(value: dict[str, Any]) -> bool:
    for key, item in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key or normalized_key in _STATE_FACT_META_KEYS:
            continue
        if _value_contains_state_fact(item):
            return True
        if item not in (None, "", [], {}):
            return True
    return False


def _value_contains_state_fact(value: Any) -> bool:
    if isinstance(value, dict):
        return _mapping_has_state_fact(value)
    if isinstance(value, list):
        return any(_value_contains_state_fact(item) for item in value)
    if not isinstance(value, str):
        return value not in (None, "")
    text = value.strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"ok", "done", "success", "successful", "completed"}:
        return False
    if text.startswith("{") or text.startswith("["):
        try:
            return _value_contains_state_fact(json.loads(text))
        except json.JSONDecodeError:
            return False
    state_terms = (
        "object",
        "scene",
        "mesh",
        "material",
        "camera",
        "light",
        "count",
        "state",
        "status",
        "location",
        "rotation",
        "dimension",
        "collection",
    )
    return (
        any(term in lowered for term in state_terms)
        and (
            any(separator in text for separator in (":", "=", "\n"))
            or any(char.isdigit() for char in text)
        )
    )


def verification_strength_meets(actual: str, required: str) -> bool:
    try:
        return VERIFICATION_STRENGTHS.index(actual) >= VERIFICATION_STRENGTHS.index(required)
    except ValueError:
        return False


def failed_tool_event_role(
    event: dict[str, Any],
    *,
    task_contract: dict[str, Any] | None,
    workspace_path: str,
    mode: str | None = None,
) -> str:
    """分类失败工具事件原本承担的任务角色。"""
    if str(event.get("status") or "") != "failure":
        return UNKNOWN
    intended_roles = event_intended_roles(event)
    if _can_be_intended_deliverable_for_contract(event, task_contract):
        return DELIVERABLE
    if VERIFICATION in intended_roles:
        return VERIFICATION
    if EVIDENCE in intended_roles:
        return EVIDENCE
    return UNKNOWN


def contract_deliverable_paths(task_contract: dict[str, Any] | None) -> set[str]:
    return {path for path, _policy in _contract_deliverable_path_specs(task_contract)}


def _contract_deliverable_path_specs(
    task_contract: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    if not isinstance(task_contract, dict):
        return []
    result: list[tuple[str, str]] = []
    for item in task_contract.get("deliverables") or []:
        if not isinstance(item, dict):
            continue
        policy = str(item.get("path_policy") or "hint").strip().lower()
        if policy not in {"exact", "hint"}:
            policy = "hint"
        for key in ("path_hint", "path", "output_path"):
            path = _normalize_path_hint(item.get(key))
            if path:
                result.append((path, policy))
    return result


def contract_deliverable_kinds(task_contract: dict[str, Any] | None) -> set[str]:
    if not isinstance(task_contract, dict):
        return set()
    return {
        str(item.get("kind") or "").strip().lower()
        for item in task_contract.get("deliverables") or []
        if isinstance(item, dict) and str(item.get("kind") or "").strip()
    }


def _is_verification_only_contract(task_contract: dict[str, Any] | None) -> bool:
    if not isinstance(task_contract, dict):
        return False
    if not task_contract.get("requires_verification"):
        return False
    if task_contract.get("requires_write") or task_contract.get("requires_state_change"):
        return False
    kinds = contract_deliverable_kinds(task_contract)
    return not kinds or kinds.issubset({"answer"})


def _is_answer_evidence_contract(task_contract: dict[str, Any] | None) -> bool:
    if not isinstance(task_contract, dict):
        return False
    if task_contract.get("requires_write") or task_contract.get("requires_state_change"):
        return False
    kinds = contract_deliverable_kinds(task_contract)
    return not kinds or kinds.issubset({"answer"})


def _is_answer_evidence_event(
    event: dict[str, Any],
    mode: str | None,
    *,
    task_contract: dict[str, Any] | None,
) -> bool:
    if not _is_answer_evidence_contract(task_contract):
        return False
    if not _status_is_success_or_partial(event):
        return False
    if _event_has_degraded_shell_stderr(event):
        return False
    if EVIDENCE in event_intended_roles(event):
        return True
    return _is_verification_event(event, mode, written_paths=event_path_hints(event))


def deliverable_path_deviations(
    events: list[dict[str, Any]],
    task_contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """返回使用了不同提示路径的成功交付物。"""
    hinted_specs = _contract_deliverable_path_specs(task_contract)
    if not hinted_specs:
        return []
    deviations: list[dict[str, Any]] = []
    for event in events:
        paths = event_path_hints(event)
        if not paths or any(_path_matches_any_deliverable_hint(path, hinted_specs) for path in paths):
            continue
        deviations.append({
            "tool": canonical_tool_id(str(event.get("tool") or "")),
            "expected_path_hints": sorted({path for path, _policy in hinted_specs}),
            "actual_paths": sorted(paths),
        })
    return deviations


def _normalized_string_list(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def event_observed_effects(event: dict[str, Any]) -> set[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    return {
        *_normalized_string_list(event.get("effects")),
        *_normalized_string_list(output.get("effects")),
    }


def event_declared_roles(event: dict[str, Any]) -> set[str]:
    if "declared_roles" in event:
        return _normalized_string_list(event.get("declared_roles"))
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    return set(LEGACY_TOOL_ROLE_HINTS.get(tool_id, ()))


def event_observed_roles(event: dict[str, Any]) -> set[str]:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    return {
        *_normalized_string_list(event.get("roles")),
        *_normalized_string_list(output.get("roles")),
    }


def event_roles(event: dict[str, Any]) -> set[str]:
    return {*event_declared_roles(event), *event_observed_roles(event)}


def event_intended_roles(event: dict[str, Any]) -> set[str]:
    return event_roles(event)


def event_declared_effects(event: dict[str, Any]) -> set[str]:
    return _normalized_string_list(event.get("declared_effects"))


def event_effects(event: dict[str, Any]) -> set[str]:
    return event_observed_effects(event)


def event_intended_effects(event: dict[str, Any]) -> set[str]:
    return {*event_declared_effects(event), *event_observed_effects(event)}


def event_path_hints(event: dict[str, Any]) -> set[str]:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values = output.get("paths") if isinstance(output.get("paths"), list) else []
    paths = {
        _normalize_path_hint(value)
        for value in values
        if _normalize_path_hint(value)
    }
    for key in ("path", "output_path", "index_path", "manifest_path"):
        path = _normalize_path_hint(output.get(key) or event_input.get(key))
        if path:
            paths.add(path)
    visual_evidence = output.get("visual_evidence")
    if isinstance(visual_evidence, dict):
        artifact = visual_evidence.get("artifact")
        if isinstance(artifact, dict):
            path = _normalize_path_hint(artifact.get("path"))
            if path:
                paths.add(path)
    return paths


def _can_be_deliverable_event(event: dict[str, Any]) -> bool:
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    roles = event_intended_roles(event)
    if DRAFT in roles or TEMPORARY in roles:
        return False
    return (
        is_write_tool(tool_id)
        or EXTERNAL_STATE_CHANGE in event_effects(event)
        or DELIVERABLE in roles
    )


def _can_be_deliverable_for_contract(
    event: dict[str, Any],
    task_contract: dict[str, Any] | None,
) -> bool:
    deliverable_kinds = contract_deliverable_kinds(task_contract)
    if _contract_expects_artifact(task_contract) and _event_has_artifact(event):
        return True
    if not _can_be_deliverable_event(event):
        return False
    if not deliverable_kinds:
        return True

    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if is_write_tool(tool_id):
        return bool(deliverable_kinds & {"file", "code", "document", *ARTIFACT_DELIVERABLE_KINDS})
    if EXTERNAL_STATE_CHANGE in event_effects(event):
        return "external_state" in deliverable_kinds
    if DELIVERABLE in event_intended_roles(event):
        return bool(
            event_path_hints(event)
            and deliverable_kinds & {"file", "code", "document", *ARTIFACT_DELIVERABLE_KINDS}
        )
    return False


def _can_be_intended_deliverable_for_contract(
    event: dict[str, Any],
    task_contract: dict[str, Any] | None,
) -> bool:
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    deliverable_kinds = contract_deliverable_kinds(task_contract)
    intended_roles = event_intended_roles(event)
    intended_effects = event_intended_effects(event)
    if is_write_tool(tool_id):
        return not deliverable_kinds or bool(
            deliverable_kinds & {"file", "code", "document", *ARTIFACT_DELIVERABLE_KINDS}
        )
    if EXTERNAL_STATE_CHANGE in intended_effects:
        return not deliverable_kinds or "external_state" in deliverable_kinds
    if _contract_expects_artifact(task_contract):
        return bool(
            ARTIFACT_EFFECTS & intended_effects
            or _event_has_artifact(event)
            or (
                VERIFICATION in intended_roles
                and _event_has_visual_artifact(event)
            )
        )
    return DELIVERABLE in intended_roles


def _contract_allows_alternative_path(
    event: dict[str, Any],
    task_contract: dict[str, Any] | None,
) -> bool:
    if not isinstance(task_contract, dict):
        return True
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if not is_write_tool(tool_id) and not (
        DELIVERABLE in event_intended_roles(event)
        and event_path_hints(event)
    ) and not (
        _contract_expects_artifact(task_contract)
        and _event_has_artifact(event)
    ):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("kind") or "").strip().lower() in {
            "file",
            "code",
            "document",
            *ARTIFACT_DELIVERABLE_KINDS,
        }
        and str(item.get("path_policy") or "hint").strip().lower() != "exact"
        for item in task_contract.get("deliverables") or []
    )


def _is_verification_event(
    event: dict[str, Any],
    mode: str | None,
    *,
    written_paths: set[str],
) -> bool:
    if _event_has_degraded_shell_stderr(event):
        return False
    if (
        VERIFICATION in event_observed_roles(event)
        and _status_is_success_or_partial(event)
    ):
        return True
    if _status_is_success_or_partial(event) and _event_has_visual_artifact(event):
        return True
    return is_meaningful_verification_event(event, mode, written_paths=written_paths)


def _status_is_success_or_partial(event: dict[str, Any]) -> bool:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if output.get("error") is True:
        return False
    return str(event.get("status") or "") in {"success", "partial"}


def _event_has_degraded_shell_stderr(event: dict[str, Any]) -> bool:
    if canonical_tool_id(str(event.get("tool") or "")) != "shell.run_command":
        return False
    for risk in event.get("runtime_risks") or []:
        if isinstance(risk, dict) and risk.get("code") == SHELL_STDERR_WARNING_CODE:
            return True
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    return shell_success_has_stderr_warning(output)


def _normalize_path_hint(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


def _path_matches_any(path: str, candidates: set[str]) -> bool:
    normalized = _normalize_path_hint(path)
    if not normalized:
        return False
    for candidate in candidates:
        other = _normalize_path_hint(candidate)
        if not other:
            continue
        if normalized == other:
            return True
        if normalized.endswith("/" + other) or other.endswith("/" + normalized):
            return True
    return False


def _path_matches_any_deliverable_hint(
    path: str,
    candidates: list[tuple[str, str]],
) -> bool:
    normalized = _normalize_path_hint(path)
    if not normalized:
        return False
    exact_candidates = {candidate for candidate, _policy in candidates}
    if _path_matches_any(normalized, exact_candidates):
        return True
    return any(
        policy != "exact" and _path_matches_loose_hint(normalized, candidate)
        for candidate, policy in candidates
    )


def _path_matches_loose_hint(path: str, expected: str) -> bool:
    actual_name = _basename(path)
    expected_name = _basename(expected)
    if not actual_name or not expected_name:
        return False
    expected_stem, expected_ext = _split_extension(expected_name)
    if expected_ext:
        return False
    actual_stem, _actual_ext = _split_extension(actual_name)
    if actual_stem == expected_stem:
        return True
    separators = (" ", "-", "_", ".", ":", "：", "—", "－")
    return any(actual_stem.startswith(expected_stem + separator) for separator in separators)


def _basename(path: str) -> str:
    return _normalize_path_hint(path).rsplit("/", 1)[-1]


def _split_extension(name: str) -> tuple[str, str]:
    if "." not in name:
        return name, ""
    stem, extension = name.rsplit(".", 1)
    if not stem:
        return name, ""
    return stem, extension
