from runtime.agent_strategy.task_contract import (
    apply_task_continuity,
    default_task_contract,
    extract_task_contract_json,
    inherit_task_contract_for_followup,
    looks_like_execute_contract_followup,
    looks_like_task_revision_followup,
    merge_model_task_contract,
    promote_task_contract_for_write_intent,
    should_use_model_task_contract,
    task_contract_context_messages,
    task_contract_prompt,
)
from runtime.conversation_runner import ConversationRunExecutor
from runtime.run_events import canonical_run_event_name, compact_run_event


def _fallback(intent: str = "answer_only") -> dict:
    return default_task_contract(
        task_intent=intent,
        mode="terminal",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path="D:\\code\\demo",
        access_scope="workspace",
    )


def test_extract_task_contract_json_from_fenced_response() -> None:
    raw = '```json\n{"intent":"write_required","requires_write":true}\n```'

    assert extract_task_contract_json(raw) == {
        "intent": "write_required",
        "requires_write": True,
    }


def test_model_contract_can_raise_write_requirement() -> None:
    contract = merge_model_task_contract(
        {
            "goal": "创建 HTML 示例页",
            "intent": "answer_only",
            "requires_write": True,
            "requires_plan": False,
            "deliverables": [
                {"kind": "file", "path_hint": "model-viewer.html", "description": "3D 模型查看器"}
            ],
            "first_action": "write",
            "confidence": 0.8,
        },
        _fallback("answer_only"),
    )

    assert contract["source"] == "model"
    assert contract["intent"] == "write_required"
    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert contract["first_action"] == "write"
    assert contract["deliverables"][0]["path_hint"] == "model-viewer.html"
    assert "target_deliverable_success" in contract["success_conditions"]


def test_hard_no_write_lock_overrides_model_contract() -> None:
    contract = merge_model_task_contract(
        {
            "intent": "write_required",
            "requires_write": True,
            "deliverables": [{"kind": "file", "path_hint": "demo.html"}],
        },
        _fallback("answer_only"),
        hard_no_write_lock=True,
    )

    assert contract["intent"] == "read_only_analysis"
    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is False
    assert contract["requires_verification"] is False
    assert contract["deliverables"] == []
    assert "hard_no_write_lock" in contract["system_overrides"]


def test_invalid_model_contract_falls_back_to_policy_contract() -> None:
    fallback = _fallback("read_only_analysis")

    contract = merge_model_task_contract(None, fallback)

    assert contract["intent"] == "read_only_analysis"
    assert contract["requires_write"] is False
    assert contract["raw_model_contract"] is None


def test_task_contract_keeps_planning_and_confirmation_policies_independent() -> None:
    contract = default_task_contract(
        task_intent="write_required",
        mode="terminal",
        planning_policy="off",
        confirmation_policy="aggressive",
        workspace_path=r"D:\code\demo",
        access_scope="workspace",
    )

    assert contract["planning_policy"] == "off"
    assert contract["confirmation_policy"] == "aggressive"
    assert contract["requires_plan"] is False


def test_task_contract_prompt_contains_only_contract_request() -> None:
    prompt = task_contract_prompt("D:\\code\\demo", _fallback())

    assert "只输出 JSON" in prompt
    assert "requires_write" in prompt
    assert "requires_state_change" in prompt
    assert "系统负责权限、工具执行和完成验收" in prompt


def test_model_contract_can_require_external_state_without_local_file_write() -> None:
    contract = merge_model_task_contract(
        {
            "goal": "在 Blender 当前场景中创建模型",
            "intent": "write_required",
            "requires_write": False,
            "requires_state_change": True,
            "requires_verification": True,
            "deliverables": [
                {
                    "kind": "external_state",
                    "path_hint": "",
                    "description": "Blender 当前场景中的模型",
                }
            ],
            "first_action": "use_tool",
        },
        _fallback("write_required"),
    )

    assert contract["intent"] == "write_required"
    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert "target_deliverable_success" in contract["success_conditions"]


def test_task_contract_prompt_includes_runtime_capabilities_when_provided() -> None:
    prompt = task_contract_prompt(
        "D:\\code\\demo",
        _fallback(),
        capability_context="- web.network_fetch: Fetch network content; tools=web.extract_text, web.render_page",
    )

    assert "Runtime capability context" in prompt
    assert "web.extract_text" in prompt
    assert "classify it as read_only_analysis" in prompt


def test_task_contract_context_keeps_recent_task_and_current_follow_up() -> None:
    context = task_contract_context_messages(
        [
            {"role": "system", "content": "large tool catalog"},
            {"role": "user", "content": "重写一个 3D 模型查看器"},
            {"role": "assistant", "content": "已创建 viewer.html"},
            {"role": "user", "content": "现在想加能选构件的能力"},
        ],
        "现在想加能选构件的能力",
    )

    assert context == [
        {"role": "user", "content": "重写一个 3D 模型查看器"},
        {"role": "assistant", "content": "已创建 viewer.html"},
        {"role": "user", "content": "现在想加能选构件的能力"},
    ]


def test_short_action_request_still_uses_model_contract() -> None:
    assert should_use_model_task_contract(
        "在 Blender 中建个二层小楼",
        "answer_only",
        False,
    )


def test_obvious_chat_can_skip_model_contract_without_recent_task() -> None:
    assert not should_use_model_task_contract("你好", "answer_only", False)


def test_obvious_chat_uses_model_contract_when_it_may_be_task_follow_up() -> None:
    assert should_use_model_task_contract(
        "好",
        "answer_only",
        False,
        has_recent_task_context=True,
    )


def test_execute_followup_inherits_external_state_contract_without_file_write() -> None:
    previous = {
        "intent": "write_required",
        "goal": "在 Blender 中创建一个二层小楼的 3D 模型",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "requires_plan": True,
        "deliverables": [
            {"kind": "external_state", "description": "Blender 场景中的二层小楼"}
        ],
        "first_action": "plan",
    }

    contract = inherit_task_contract_for_followup(previous, _fallback("answer_only"))

    assert looks_like_execute_contract_followup("立即执行")
    assert contract["source"] == "conversation_context"
    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is True
    assert contract["requires_plan"] is False
    assert contract["first_action"] == "use_tool"
    assert contract["deliverables"][0]["kind"] == "external_state"
    assert "target_deliverable_success" in contract["success_conditions"]


def test_revision_followup_preserves_previous_external_state_target() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Create a two-story house in the current Blender scene",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {"kind": "external_state", "description": "Current Blender scene"}
        ],
    }
    proposed = merge_model_task_contract(
        {
            "intent": "write_required",
            "goal": "Improve the Blender Python script",
            "requires_write": True,
            "requires_state_change": True,
            "deliverables": [
                {"kind": "code", "path_hint": "build_house_v2.py"}
            ],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="not good enough, try again",
    )

    assert looks_like_task_revision_followup("not good enough, try again")
    assert contract["scope_relation"] == "revise"
    assert contract["goal"] == previous["goal"]
    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is True
    assert contract["deliverables"][0]["kind"] == "external_state"
    assert contract["revision_request"] == "not good enough, try again"


def test_local_file_delete_contract_is_not_external_state() -> None:
    contract = merge_model_task_contract(
        {
            "intent": "write_required",
            "goal": "\u5220\u6389\u8fd9\u4e2a\u65b0\u52a0\u7684\u6587\u6863",
            "requires_write": False,
            "requires_state_change": True,
            "requires_verification": True,
            "capability_ids": ["filesystem.local_files"],
            "deliverables": [
                {
                    "kind": "external_state",
                    "description": "\u5220\u9664\u9879\u76ee\u4e2d\u7684\u6587\u6863\u6587\u4ef6",
                }
            ],
            "expected_min_output_chars": 500,
        },
        _fallback("answer_only"),
        expected_min_output_chars=500,
    )

    assert contract["intent"] == "write_required"
    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["deliverables"][0]["kind"] == "file"
    assert contract["capability_ids"][0] == "filesystem.local_state"
    assert contract["expected_min_output_chars"] == 0
    assert "document_min_output_chars" not in contract["success_conditions"]


def test_revision_followup_can_retarget_from_document_to_local_file_delete() -> None:
    previous = {
        "intent": "write_required",
        "goal": "\u5206\u6790\u5f53\u524d\u9879\u76ee\u7684\u5f00\u53d1\u60c5\u51b5",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "capability_ids": ["code.local_project", "filesystem.local_files"],
        "deliverables": [
            {
                "kind": "document",
                "path_hint": "YuntaoCode_\u9879\u76ee\u5f00\u53d1\u60c5\u51b5\u5206\u6790.md",
                "description": "Project analysis report",
            }
        ],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "revise",
            "intent": "write_required",
            "goal": "\u5220\u9664\u9879\u76ee\u4e2d\u7684\u6587\u6863\u6587\u4ef6\u4ee5\u907f\u514d\u5f71\u54cdGitHub\u66f4\u65b0",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "capability_ids": ["filesystem.local_files"],
            "deliverables": [
                {
                    "kind": "file",
                    "path_hint": "YuntaoCode_\u9879\u76ee\u5f00\u53d1\u60c5\u51b5\u5206\u6790.md",
                    "path_policy": "exact",
                    "description": "\u5220\u9664\u6307\u5b9a\u7684\u6587\u6863\u6587\u4ef6",
                }
            ],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="\u80fd\u5220\u9664\u5417",
    )

    assert contract["scope_relation"] == "revise"
    assert contract["goal"].startswith("\u5220\u9664")
    assert contract["deliverables"][0]["kind"] == "file"
    assert contract["deliverables"][0]["path_policy"] == "exact"
    assert contract["capability_ids"][0] == "filesystem.local_state"
    assert contract["continuity_anchor"]["goal"].startswith("\u5220\u9664")


def test_read_only_followup_keeps_current_goal_instead_of_old_anchor() -> None:
    previous = {
        "intent": "read_only_analysis",
        "goal": "\u68c0\u67e5\u8bba\u6587\u4e2d\u53c2\u8003\u6587\u732e\u90e8\u5206\u7684\u89c4\u8303\u6027\u4e0e\u5408\u7406\u6027",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": True,
        "capability_ids": ["filesystem.local_files"],
        "deliverables": [
            {"kind": "answer", "description": "\u53c2\u8003\u6587\u732e\u68c0\u67e5\u7ed3\u679c\u62a5\u544a"}
        ],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "continue",
            "intent": "read_only_analysis",
            "goal": "\u68c0\u67e5\u5f53\u524d\u8bba\u6587\u5b57\u6570\u5e76\u8bc4\u4f30\u6269\u5199\u7a7a\u95f4",
            "requires_write": False,
            "requires_state_change": False,
            "requires_verification": True,
            "capability_ids": ["filesystem.local_files"],
            "deliverables": [
                {"kind": "answer", "description": "\u8bba\u6587\u5b57\u6570\u7edf\u8ba1\u7ed3\u679c\u4e0e\u6269\u5199\u7a7a\u95f4\u8bc4\u4f30\u62a5\u544a"}
            ],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="\u770b\u5f53\u524d\u8bba\u6587\u6709\u591a\u5c11\u5b57\uff0c\u6269\u5199\u7a7a\u95f4\u6709\u591a\u5c11",
    )

    assert contract["intent"] == "read_only_analysis"
    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is False
    assert contract["goal"].startswith("\u68c0\u67e5\u5f53\u524d\u8bba\u6587\u5b57\u6570")
    assert contract["deliverables"][0]["description"].startswith("\u8bba\u6587\u5b57\u6570")
    assert contract["continuity_anchor"]["goal"].startswith("\u68c0\u67e5\u5f53\u524d\u8bba\u6587\u5b57\u6570")


def test_revision_followup_promotes_current_write_requirement_over_read_only_anchor() -> None:
    previous = {
        "intent": "read_only_analysis",
        "goal": "Inspect and fix the stray CSS2D label",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": False,
        "capability_ids": ["filesystem.local_files"],
        "deliverables": [{"kind": "answer", "description": "Analysis"}],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "revise",
            "intent": "write_required",
            "goal": "Compare sibling projects and fix the CSS2D label",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "capability_ids": ["filesystem.local_files", "code.local_project"],
            "deliverables": [
                {"kind": "code", "path_hint": "src/app.js", "description": "CSS2D label fix"}
            ],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="that fix did not work; compare the other subprojects",
    )

    assert contract["scope_relation"] == "revise"
    assert contract["goal"] == previous["goal"]
    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert contract["intent"] == "write_required"
    assert contract["deliverables"][0]["kind"] == "code"
    assert contract["capability_ids"] == ["filesystem.local_files", "code.local_project"]
    assert "target_deliverable_success" in contract["success_conditions"]
    assert "target_deliverable_verification" in contract["success_conditions"]


def test_runtime_write_promotion_turns_answer_contract_into_verifiable_code_target() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": False,
        "deliverables": [
            {
                "kind": "answer",
                "path_hint": "D:/workspace/app",
                "description": "Analysis only",
            }
        ],
        "system_overrides": [],
    }

    changed = promote_task_contract_for_write_intent(
        contract,
        reason="planned_write_step",
        deliverable_kind="code",
        description="Plan includes a code edit",
    )

    assert changed is True
    assert contract["intent"] == "write_required"
    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert contract["deliverables"][0]["kind"] == "code"
    assert contract["deliverables"][0]["path_hint"] == "D:/workspace/app"
    assert "planned_write_step" in contract["system_overrides"]
    assert "target_deliverable_success" in contract["success_conditions"]
    assert "target_deliverable_verification" in contract["success_conditions"]


def test_model_can_explicitly_replace_previous_task_target() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Create a Blender scene",
        "requires_write": False,
        "requires_state_change": True,
        "deliverables": [{"kind": "external_state"}],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "replace",
            "intent": "write_required",
            "goal": "Export a reusable script instead",
            "requires_write": True,
            "deliverables": [{"kind": "code", "path_hint": "house.py"}],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="Export a reusable script instead",
    )

    assert contract["scope_relation"] == "replace"
    assert contract["goal"] == "Export a reusable script instead"
    assert contract["requires_write"] is True
    assert contract["deliverables"][0]["kind"] == "code"


def test_model_explicit_new_relation_is_not_overridden_by_retry_fallback() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Create a Blender scene",
        "requires_write": False,
        "requires_state_change": True,
        "deliverables": [{"kind": "external_state"}],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "new",
            "intent": "write_required",
            "goal": "Create an unrelated report",
            "requires_write": True,
            "deliverables": [{"kind": "document", "path_hint": "report.docx"}],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="try again with this unrelated report",
    )

    assert contract["scope_relation"] == "new"
    assert contract["scope_relation_source"] == "model"
    assert contract["deliverables"][0]["kind"] == "document"


def test_continuity_does_not_override_current_document_size_requirement() -> None:
    previous = {
        "intent": "document_export",
        "goal": "Expand the report",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "expected_min_output_chars": 30000,
        "deliverables": [{"kind": "document", "path_hint": "report.docx"}],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "revise",
            "intent": "document_export",
            "requires_write": True,
            "expected_min_output_chars": 50000,
            "deliverables": [{"kind": "document", "path_hint": "report.docx"}],
        },
        _fallback("document_export"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="raise the target to 50000 characters",
    )

    assert contract["expected_min_output_chars"] == 50000


def test_continuity_does_not_override_hard_no_write_lock() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Modify the project",
        "requires_write": True,
        "requires_state_change": True,
        "deliverables": [{"kind": "code", "path_hint": "app.py"}],
    }
    locked = merge_model_task_contract(
        {"scope_relation": "revise", "requires_write": True},
        _fallback("write_required"),
        hard_no_write_lock=True,
    )

    contract = apply_task_continuity(
        locked,
        previous_contract=previous,
        current_user_content="only analyze, do not modify",
    )

    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is False
    assert contract["deliverables"] == []


def test_deliverable_path_policy_defaults_to_hint_and_accepts_exact() -> None:
    hinted = merge_model_task_contract(
        {
            "intent": "write_required",
            "requires_write": True,
            "deliverables": [{"kind": "code", "path_hint": "app.py"}],
        },
        _fallback("answer_only"),
    )
    exact = merge_model_task_contract(
        {
            "intent": "write_required",
            "requires_write": True,
            "deliverables": [
                {"kind": "code", "path_hint": "app.py", "path_policy": "exact"}
            ],
        },
        _fallback("answer_only"),
    )

    assert hinted["deliverables"][0]["path_policy"] == "hint"
    assert exact["deliverables"][0]["path_policy"] == "exact"


def test_task_contract_run_event_is_recordable() -> None:
    payload = {"event": "task_contract", "contract": {"intent": "write_required"}}

    compact = compact_run_event(payload)

    assert canonical_run_event_name(payload) == "task.contract"
    assert compact["event_name"] == "task.contract"
    assert compact["contract"]["intent"] == "write_required"


def test_runtime_guidance_can_raise_document_size_contract() -> None:
    executor = object.__new__(ConversationRunExecutor)
    contract = default_task_contract(
        task_intent="document_export",
        mode="terminal",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code\demo",
        access_scope="workspace",
        expected_min_output_chars=30000,
    )

    changed = executor._apply_guidance_contract_updates(contract, "raise the target to 50000 words")

    assert changed is True
    assert contract["expected_min_output_chars"] == 50000
    assert "document_min_output_chars" in contract["success_conditions"]
    assert "expected_min_output_chars" in contract["system_overrides"]


def test_runtime_guidance_replaces_document_size_contract_with_latest_explicit_target() -> None:
    executor = object.__new__(ConversationRunExecutor)
    contract = default_task_contract(
        task_intent="document_export",
        mode="terminal",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code\demo",
        access_scope="workspace",
        expected_min_output_chars=50000,
    )

    changed = executor._apply_guidance_contract_updates(contract, "30000 words is enough")

    assert changed is True
    assert contract["expected_min_output_chars"] == 30000


def test_model_declared_document_size_is_preserved_by_contract_normalization() -> None:
    fallback = default_task_contract(
        task_intent="document_export",
        mode="document",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code\demo",
        access_scope="workspace",
    )

    contract = merge_model_task_contract(
        {
            "intent": "document_export",
            "requires_write": True,
            "expected_min_output_chars": 30000,
        },
        fallback,
    )

    assert contract["expected_min_output_chars"] == 30000
    assert "document_min_output_chars" in contract["success_conditions"]
