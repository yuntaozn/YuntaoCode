from runtime.agent_strategy.task_contract import (
    apply_task_continuity,
    contract_expects_text_output,
    default_task_contract,
    extract_task_contract_json,
    inherit_task_contract_for_followup,
    looks_like_execute_contract_followup,
    looks_like_task_revision_followup,
    merge_model_task_contract,
    promote_task_contract_for_write_intent,
    should_apply_task_continuity,
    should_use_model_task_contract,
    task_continuity_anchor,
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


def test_no_write_hint_does_not_override_model_contract() -> None:
    contract = merge_model_task_contract(
        {
            "intent": "write_required",
            "requires_write": True,
            "deliverables": [{"kind": "file", "path_hint": "demo.html"}],
        },
        _fallback("answer_only"),
        user_no_write_hint=True,
    )

    assert contract["intent"] == "write_required"
    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert contract["deliverables"][0]["path_hint"] == "demo.html"
    assert contract["user_no_write_hint"] is True
    assert "user_no_write_hint" in contract["system_overrides"]


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
    assert "referenced_task_candidate_id" in prompt
    assert "系统负责权限、工具执行和完成验收" in prompt


def test_task_contract_prompt_includes_workspace_context_as_facts() -> None:
    prompt = task_contract_prompt(
        "D:\\code\\demo",
        _fallback(),
        workspace_context='Workspace fact snapshot: {"name":"lesson","extension_counts":{".html":1}}',
    )

    assert "Runtime workspace context" in prompt
    assert "Workspace fact snapshot" in prompt
    assert '"lesson"' in prompt


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


def test_model_contract_can_require_visual_verification() -> None:
    contract = merge_model_task_contract(
        {
            "goal": "Build a good-looking two-floor house in Blender",
            "intent": "write_required",
            "requires_write": False,
            "requires_state_change": True,
            "requires_verification": True,
            "required_verification_modalities": ["visual", "structural", "unknown"],
            "deliverables": [
                {
                    "kind": "external_state",
                    "description": "Rendered Blender scene with a two-floor house",
                }
            ],
            "first_action": "use_tool",
        },
        _fallback("write_required"),
    )

    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is True
    assert contract["required_verification_modalities"] == ["visual", "structural"]
    assert "target_visual_verification" in contract["success_conditions"]


def test_task_contract_prompt_includes_runtime_capabilities_when_provided() -> None:
    prompt = task_contract_prompt(
        "D:\\code\\demo",
        _fallback(),
        capability_context="- web.network_fetch: Fetch network content; tools=web.extract_text, web.render_page",
    )

    assert "Runtime capability context" in prompt
    assert "web.extract_text" in prompt
    assert "classify it as read_only_analysis" in prompt
    assert "required_verification_modalities" in prompt


def test_task_contract_prompt_allows_analysis_first_repair_advisory() -> None:
    prompt = task_contract_prompt("D:\\code\\demo", _fallback())

    assert "analysis-first repairable task" in prompt
    assert "execution_advisories" in prompt
    assert "evidence_may_require_repair" in prompt


def test_model_contract_preserves_execution_advisories_as_non_binding_context() -> None:
    contract = merge_model_task_contract(
        {
            "intent": "read_only_analysis",
            "requires_write": False,
            "first_action": "read",
            "execution_advisories": [
                {
                    "code": "evidence_may_require_repair",
                    "message": "Read first; repair if evidence shows a broken local artifact.",
                    "suggested_first_action": "read",
                }
            ],
        },
        _fallback("answer_only"),
    )

    assert contract["requires_write"] is False
    assert contract["execution_advisories"] == [
        {
            "code": "evidence_may_require_repair",
            "message": "Read first; repair if evidence shows a broken local artifact.",
            "suggested_first_action": "read",
        }
    ]


def test_task_contract_context_keeps_recent_task_and_current_follow_up() -> None:
    context = task_contract_context_messages(
        [
            {"role": "system", "content": "large tool catalog"},
            {"role": "user", "content": "重写一个 3D 模型查看器"},
            {"role": "assistant", "content": "已创建 viewer.html"},
            {"role": "user", "content": "现在想加能选构件的能力"},
        ],
        "现在想加能选构件的能力",
        include_history=True,
    )

    assert context == [
        {"role": "user", "content": "重写一个 3D 模型查看器"},
        {"role": "assistant", "content": "已创建 viewer.html"},
        {"role": "user", "content": "现在想加能选构件的能力"},
    ]


def test_task_contract_context_can_use_current_request_only() -> None:
    context = task_contract_context_messages(
        [
            {"role": "user", "content": "Create a Blender house"},
            {"role": "assistant", "content": "I changed the scene"},
            {"role": "user", "content": "Now update the teaching page code"},
        ],
        "Now update the teaching page code",
        include_history=False,
    )

    assert context == [{"role": "user", "content": "Now update the teaching page code"}]


def test_short_action_request_still_uses_model_contract() -> None:
    assert should_use_model_task_contract(
        "在 Blender 中建个二层小楼",
        "answer_only",
        False,
    )


def test_obvious_chat_can_skip_model_contract_without_recent_task() -> None:
    assert not should_use_model_task_contract("你好", "answer_only", False)


def test_no_write_hint_still_uses_model_contract_for_semantic_judgment() -> None:
    assert should_use_model_task_contract(
        "Only analyze the current issue; do not modify files yet.",
        "answer_only",
        True,
    )


def test_non_chat_recommendation_uses_model_contract_for_semantic_judgment() -> None:
    assert should_use_model_task_contract(
        "Compare several options for a low-cost programmable consumer device and recommend a concrete model.",
        "answer_only",
        False,
    )


def test_obvious_chat_uses_model_contract_when_it_may_be_task_follow_up() -> None:
    assert should_use_model_task_contract(
        "好",
        "answer_only",
        False,
        has_recent_task_context=True,
    )


def test_diagnostic_feedback_uses_model_contract_even_if_fallback_is_chat() -> None:
    assert should_use_model_task_contract(
        "home.js:1 Uncaught TypeError: Cannot set properties of null "
        "(setting 'onclick')",
        "answer_only",
        False,
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
    assert contract["first_action"] != "verify"
    assert contract["deliverables"][0]["kind"] == "external_state"
    assert "target_deliverable_success" in contract["success_conditions"]


def test_execute_followup_inherits_visual_verification_requirement() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Create a good-looking house in the current Blender scene",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [
            {"kind": "external_state", "description": "Current Blender scene"}
        ],
        "first_action": "use_tool",
    }

    contract = inherit_task_contract_for_followup(previous, _fallback("answer_only"))

    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is True
    assert contract["required_verification_modalities"] == ["visual"]
    assert "target_visual_verification" in contract["success_conditions"]


def test_execute_followup_does_not_inherit_text_length_from_code_contract() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Create an interactive code artifact",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "expected_min_output_chars": 2000,
        "deliverables": [
            {"kind": "code", "path_hint": "src/app.js"}
        ],
    }

    contract = inherit_task_contract_for_followup(previous, _fallback("answer_only"))

    assert contract["expected_min_output_chars"] == 0
    assert "document_min_output_chars" not in contract["success_conditions"]


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


def test_task_continuity_applies_only_after_model_continuation_judgment() -> None:
    explicit_continue = {
        "intent": "write_required",
        "scope_relation": "continue",
        "scope_relation_source": "model",
    }
    explicit_replace = {
        "intent": "write_required",
        "scope_relation": "replace",
        "scope_relation_source": "model",
    }
    explicit_new = {
        "intent": "write_required",
        "scope_relation": "new",
        "scope_relation_source": "model",
    }
    fallback_retry = {
        "intent": "answer_only",
        "scope_relation": "new",
        "scope_relation_source": "default",
    }

    assert should_apply_task_continuity(
        explicit_continue,
        current_user_content="continue",
    )
    assert not should_apply_task_continuity(
        explicit_replace,
        current_user_content="continue",
    )
    assert not should_apply_task_continuity(
        explicit_new,
        current_user_content="try again",
    )
    assert should_apply_task_continuity(
        fallback_retry,
        current_user_content="try again",
    )


def test_observation_followup_over_previous_state_task_adds_soft_advisory() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Create a two-story house in the current Blender scene",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "capability_ids": ["mcp.blender"],
        "deliverables": [
            {"kind": "external_state", "description": "Current Blender scene"}
        ],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "continue",
            "intent": "write_required",
            "goal": "Create a two-story house in the current Blender scene",
            "requires_write": False,
            "requires_state_change": True,
            "requires_verification": True,
            "required_verification_modalities": ["visual"],
            "capability_ids": ["mcp.blender"],
            "deliverables": [
                {"kind": "external_state", "description": "Current Blender scene"}
            ],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content=(
            "\u6a21\u578b\u662f\u5efa\u4e86\uff0c\u4f46\u5e76\u4e0d\u50cf\uff0c"
            "\u90fd\u662f\u6563\u5f00\u7684\uff0c\u4f60\u53ef\u4ee5\u770b\u5230"
            "\u6548\u679c\u5427"
        ),
    )

    assert contract["intent"] == "write_required"
    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert contract["required_verification_modalities"] == ["visual"]
    assert contract["first_action"] != "verify"
    assert contract["capability_ids"] == ["mcp.blender"]
    assert contract["deliverables"][0]["kind"] == "external_state"
    assert contract["continuity_advisories"][0]["code"] == "possible_observation_followup"
    assert contract["continuity_advisories"][0]["suggested_first_action"] == "verify"
    assert "observation_followup_read_only" not in contract.get("system_overrides", [])


def test_continuity_keeps_current_specific_local_target_over_broad_anchor() -> None:
    previous = {
        "intent": "write_required",
        "goal": "优化独立基础施工全过程交互动画的模型和动画细节",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "capability_ids": ["filesystem.local_files", "code.edit_file"],
        "deliverables": [
            {
                "kind": "file",
                "path_hint": "D:\\code\\demo\\教学课件\\",
                "path_policy": "hint",
                "description": "优化后的3D模型文件、动画相关代码/配置文件，以及优化说明文档",
            },
            {
                "kind": "code",
                "path_hint": "D:\\code\\demo\\教学课件\\独立基础施工全过程\\交互动画\\src\\app.js",
                "path_policy": "hint",
                "description": "Successful local write via code.edit_file",
            },
        ],
    }
    proposed = merge_model_task_contract(
        {
            "goal": "从其他子项目查找站立人.glb，复制到当前项目 assets 目录，并修改代码引用替代示意人模型",
            "intent": "write_required",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "required_verification_modalities": ["visual"],
            "capability_ids": ["filesystem.local_files", "filesystem.change_set", "code.edit_file"],
            "deliverables": [
                {
                    "kind": "file",
                    "path_hint": "D:\\code\\demo\\教学课件\\独立基础施工全过程\\交互动画\\assets\\站立人.glb",
                    "path_policy": "hint",
                    "description": "复制到 assets 目录的站立人3D模型文件",
                },
                {
                    "kind": "code",
                    "path_hint": "D:\\code\\demo\\教学课件\\独立基础施工全过程\\交互动画\\src\\app.js",
                    "path_policy": "hint",
                    "description": "引用新站立人模型的项目代码文件",
                },
            ],
            "scope_relation": "revise",
            "referenced_task_candidate_id": "previous-run",
            "first_action": "read",
            "confidence": 0.95,
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="可从其他子项目中找到 站立人.glb 复制到 assets 目录，然后在项目中引用替代现在的示意人模型",
    )

    assert contract["goal"].startswith("从其他子项目查找站立人.glb")
    assert contract["deliverables"][0]["path_hint"].endswith("assets\\站立人.glb")
    assert "优化后的3D模型文件" not in contract["deliverables"][0]["description"]
    assert contract["continuity_anchor"]["goal"].startswith("从其他子项目查找站立人.glb")
    assert contract["requires_write"] is True
    assert contract["requires_verification"] is True


def test_retry_followup_still_preserves_previous_state_change_target() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Create a two-story house in the current Blender scene",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "capability_ids": ["mcp.blender"],
        "deliverables": [
            {"kind": "external_state", "description": "Current Blender scene"}
        ],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "revise",
            "intent": "write_required",
            "goal": "Create a two-story house in the current Blender scene",
            "requires_write": False,
            "requires_state_change": True,
            "requires_verification": True,
            "required_verification_modalities": ["visual"],
            "capability_ids": ["mcp.blender"],
            "deliverables": [
                {"kind": "external_state", "description": "Current Blender scene"}
            ],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content=(
            "\u6a21\u578b\u751f\u6210\u6548\u679c\u4e0d\u7406\u60f3\uff0c"
            "\u5e2e\u6211\u518d\u91cd\u65b0\u505a\u4e00\u4e0b"
        ),
    )

    assert contract["intent"] == "write_required"
    assert contract["requires_state_change"] is True
    assert contract["deliverables"][0]["kind"] == "external_state"
    assert "observation_followup_read_only" not in contract.get("system_overrides", [])


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
    assert contract["goal"] == "Compare sibling projects and fix the CSS2D label"
    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert contract["intent"] == "write_required"
    assert contract["deliverables"][0]["kind"] == "code"
    assert contract["capability_ids"] == ["filesystem.local_files", "code.local_project"]
    assert contract["continuity_anchor"]["goal"] == "Compare sibling projects and fix the CSS2D label"
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
        reason="model_selected_write_tool",
        deliverable_kind="code",
        description="Model selected a write tool",
    )

    assert changed is True
    assert contract["intent"] == "write_required"
    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["requires_verification"] is True
    assert contract["deliverables"][0]["kind"] == "code"
    assert contract["deliverables"][0]["path_hint"] == "D:/workspace/app"
    assert "model_selected_write_tool" in contract["system_overrides"]
    assert "target_deliverable_success" in contract["success_conditions"]
    assert "target_deliverable_verification" in contract["success_conditions"]


def test_write_followup_keeps_model_target_over_old_read_only_anchor() -> None:
    previous = {
        "intent": "read_only_analysis",
        "goal": "Find the frontend API address configuration",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": False,
        "capability_ids": ["code.local_project"],
        "deliverables": [{"kind": "answer", "description": "API address location"}],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "continue",
            "intent": "write_required",
            "goal": "Modify web/home.js to call the local FastAPI backend",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "capability_ids": ["code.local_project", "code.text_write"],
            "deliverables": [
                {
                    "kind": "code",
                    "path_hint": "web/home.js",
                    "description": "Update request URL handling",
                }
            ],
        },
        _fallback("answer_only"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="change home.js to use the FastAPI backend",
    )

    assert contract["goal"] == "Modify web/home.js to call the local FastAPI backend"
    assert contract["requires_write"] is True
    assert contract["deliverables"][0]["path_hint"] == "web/home.js"
    assert contract["continuity_anchor"]["goal"] == "Modify web/home.js to call the local FastAPI backend"


def test_model_selected_write_tool_can_promote_analysis_contract_without_scenario_rule() -> None:
    contract = {
        "intent": "read_only_analysis",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": False,
        "deliverables": [{"kind": "answer", "description": "Analysis"}],
        "system_overrides": [],
    }

    changed = promote_task_contract_for_write_intent(
        contract,
        reason="model_selected_write_tool",
        path_hint="viewer/index.html",
        deliverable_kind="code",
        description="Model selected a write tool",
    )

    assert changed is True
    assert contract["requires_write"] is True
    assert contract["requires_verification"] is True
    assert contract["deliverables"][0]["kind"] == "code"
    assert contract["deliverables"][0]["path_hint"] == "viewer/index.html"
    assert "model_selected_write_tool" in contract["system_overrides"]


def test_model_code_contract_clears_fallback_text_length_goal() -> None:
    fallback = default_task_contract(
        task_intent="write_required",
        mode="terminal",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code\demo",
        access_scope="workspace",
        expected_min_output_chars=2000,
    )

    contract = merge_model_task_contract(
        {
            "intent": "write_required",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "expected_min_output_chars": 0,
            "deliverables": [
                {"kind": "code", "path_hint": "src/app.js"}
            ],
        },
        fallback,
        expected_min_output_chars=2000,
    )

    assert contract["expected_min_output_chars"] == 0
    assert contract_expects_text_output(contract) is False
    assert "document_min_output_chars" not in contract["success_conditions"]
    assert "cleared_non_text_min_output_chars" in contract["system_overrides"]


def test_text_file_contract_preserves_declared_min_output_chars() -> None:
    fallback = default_task_contract(
        task_intent="write_required",
        mode="terminal",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code\demo",
        access_scope="workspace",
    )

    contract = merge_model_task_contract(
        {
            "intent": "write_required",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "expected_min_output_chars": 50000,
            "deliverables": [
                {"kind": "file", "path_hint": "novel.txt"}
            ],
        },
        fallback,
        expected_min_output_chars=50000,
    )

    assert contract_expects_text_output(contract) is True
    assert contract["expected_min_output_chars"] == 50000
    assert "document_min_output_chars" in contract["success_conditions"]
    assert "cleared_non_text_min_output_chars" not in contract["system_overrides"]


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


def test_continuity_preserves_text_file_size_target() -> None:
    previous = {
        "intent": "write_required",
        "goal": "Write a novel to novel.txt",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "expected_min_output_chars": 50000,
        "deliverables": [{"kind": "file", "path_hint": "novel.txt"}],
    }
    proposed = merge_model_task_contract(
        {
            "scope_relation": "continue",
            "intent": "write_required",
            "requires_write": True,
            "expected_min_output_chars": 0,
            "deliverables": [{"kind": "file", "path_hint": "novel.txt"}],
        },
        _fallback("write_required"),
    )

    contract = apply_task_continuity(
        proposed,
        previous_contract=previous,
        current_user_content="再试一次",
    )

    assert contract_expects_text_output(contract) is True
    assert contract["expected_min_output_chars"] == 50000
    assert task_continuity_anchor(contract)["expected_min_output_chars"] == 50000


def test_continuity_preserves_model_contract_with_no_write_hint() -> None:
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
        user_no_write_hint=True,
    )

    contract = apply_task_continuity(
        locked,
        previous_contract=previous,
        current_user_content="only analyze, do not modify",
    )

    assert contract["requires_write"] is True
    assert contract["requires_state_change"] is True
    assert contract["deliverables"][0]["path_hint"] == "app.py"
    assert contract["user_no_write_hint"] is True


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


def test_model_contract_preserves_referenced_task_candidate_id() -> None:
    contract = merge_model_task_contract(
        {
            "goal": "Try the same Blender house again",
            "intent": "write_required",
            "scope_relation": "revise",
            "referenced_task_candidate_id": "run-1",
        },
        _fallback("answer_only"),
    )

    assert contract["scope_relation"] == "revise"
    assert contract["referenced_task_candidate_id"] == "run-1"


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


def test_runtime_guidance_does_not_apply_document_size_to_code_contract() -> None:
    executor = object.__new__(ConversationRunExecutor)
    contract = default_task_contract(
        task_intent="write_required",
        mode="terminal",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code\demo",
        access_scope="workspace",
    )
    contract["deliverables"] = [{"kind": "code", "path_hint": "src/app.js"}]

    changed = executor._apply_guidance_contract_updates(contract, "raise the target to 50000 words")

    assert changed is False
    assert contract["expected_min_output_chars"] == 0


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
