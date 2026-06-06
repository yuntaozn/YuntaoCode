from runtime.agent_strategy.task_contract import (
    default_task_contract,
    extract_task_contract_json,
    merge_model_task_contract,
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
    assert "系统负责权限、工具执行和完成验收" in prompt


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
