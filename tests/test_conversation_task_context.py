from __future__ import annotations

from types import SimpleNamespace

from runtime.agent_strategy.conversation_task_context import (
    code_change_intent,
    classify_task_intent,
    effective_mode,
    expected_min_output_chars,
    has_recent_task_context,
    previous_task_contract_context,
    previous_write_context,
)


def _message(role: str, content: str, metadata: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content, metadata=metadata or {})


def test_previous_task_contract_context_skips_unanchored_retry_contract() -> None:
    external_contract = {
        "intent": "write_required",
        "goal": "Create the model in Blender",
        "requires_write": False,
        "requires_state_change": True,
        "deliverables": [{"kind": "external_state"}],
    }
    fallback_script_contract = {
        "intent": "write_required",
        "goal": "Write a Blender script",
        "requires_write": True,
        "requires_state_change": True,
        "deliverables": [{"kind": "code", "path_hint": "house.py"}],
    }
    conversation = SimpleNamespace(messages=[
        _message("user", "Create a house in Blender"),
        _message("assistant", "done", {"task_contract": external_contract}),
        _message("user", "not good enough, try again"),
        _message("assistant", "wrote a script", {"task_contract": fallback_script_contract}),
        _message("user", "try again"),
    ])

    assert previous_task_contract_context(conversation, "try again") == external_contract


def test_previous_task_contract_context_skips_answer_only_anchor() -> None:
    external_contract = {
        "intent": "write_required",
        "goal": "Create a house model in Blender",
        "requires_write": False,
        "requires_state_change": True,
        "deliverables": [{"kind": "external_state"}],
    }
    answer_contract = {
        "intent": "answer_only",
        "goal": "Explain how to install Blender MCP",
        "requires_write": False,
        "requires_state_change": False,
        "deliverables": [{"kind": "answer"}],
    }
    conversation = SimpleNamespace(messages=[
        _message("user", "Create a house in Blender"),
        _message("assistant", "failed", {"task_contract": external_contract}),
        _message("user", "How do I install Blender MCP?"),
        _message("assistant", "install notes", {"task_contract": answer_contract}),
    ])

    assert (
        previous_task_contract_context(conversation, "Now it is installed; build the house")
        == external_contract
    )


def test_follow_up_inherits_previous_write_context_for_mode_and_intent() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "创建一个 viewer.html 示例页"),
        _message(
            "assistant",
            "已创建文件",
            {
                "task_contract": {
                    "intent": "write_required",
                    "requires_write": True,
                    "goal": "创建 viewer.html 示例页",
                }
            },
        ),
        _message("user", "继续加选择构件功能"),
    ])

    assert previous_write_context(conversation, "继续加选择构件功能")
    assert effective_mode(None, "继续加选择构件功能", conversation) == "coding"
    assert code_change_intent("继续加选择构件功能", "coding", conversation)


def test_plan_with_write_step_alone_does_not_create_previous_write_context() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "\u5206\u6790\u5e76\u63a8\u8350\u4e00\u6b3e\u4f4e\u4ef7\u65e0\u4eba\u673a"),
        _message(
            "assistant",
            "\u5efa\u8bae\u8c03\u7814\u4ea7\u54c1\u53c2\u6570",
            {
                "execution_plan": {
                    "steps": [
                        {
                            "title": "\u6267\u884c\u4ee3\u7801\u53d8\u66f4",
                            "status": "pending",
                            "tool_hint": "code.edit_file",
                        }
                    ]
                },
                "task_contract": {
                    "intent": "read_only_analysis",
                    "requires_write": False,
                    "requires_state_change": False,
                    "deliverables": [{"kind": "answer"}],
                },
            },
        ),
    ])

    follow_up = "\u518d\u63a8\u8350\u4e00\u6b3e\u5177\u4f53\u578b\u53f7"

    assert not previous_write_context(conversation, follow_up)
    assert effective_mode(None, follow_up, conversation) == "terminal"


def test_expected_min_output_chars_uses_current_request_before_history() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "写一篇 50000 字报告"),
        _message(
            "assistant",
            "已生成报告",
            {"task_contract": {"expected_min_output_chars": 50000}},
        ),
    ])

    assert expected_min_output_chars("改成 30000 字版本", conversation) == 30000


def test_expected_min_output_chars_does_not_inherit_for_read_only_question() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "\u6269\u5199\u6210 30000 \u5b57\u8bba\u6587"),
        _message(
            "assistant",
            "\u5df2\u5904\u7406",
            {"task_contract": {"expected_min_output_chars": 30000}},
        ),
    ])

    assert expected_min_output_chars(
        "\u770b\u5f53\u524d\u8bba\u6587\u6709\u591a\u5c11\u5b57\uff0c\u6269\u5199\u7a7a\u95f4\u6709\u591a\u5c11",
        conversation,
    ) == 0


def test_expected_min_output_chars_does_not_inherit_from_code_contract() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "create the interactive lesson page"),
        _message(
            "assistant",
            "wrote code",
            {
                "task_contract": {
                    "intent": "write_required",
                    "requires_write": True,
                    "expected_min_output_chars": 2000,
                    "deliverables": [{"kind": "code", "path_hint": "src/app.js"}],
                }
            },
        ),
    ])

    assert expected_min_output_chars("try again", conversation) == 0


def test_diagnostic_feedback_uses_recent_write_context_without_forcing_write() -> None:
    conversation = SimpleNamespace(messages=[
        _message("user", "where is the frontend API base URL?"),
        _message(
            "assistant",
            "It is in web/home.js",
            {
                "task_contract": {
                    "intent": "read_only_analysis",
                    "goal": "Find frontend API base URL",
                    "requires_write": False,
                    "deliverables": [{"kind": "answer"}],
                }
            },
        ),
        _message("user", "change home.js to use the FastAPI backend"),
        _message(
            "assistant",
            "updated home.js",
            {
                "task_contract": {
                    "intent": "write_required",
                    "goal": "Modify web/home.js to call the FastAPI backend",
                    "requires_write": True,
                    "requires_state_change": True,
                    "requires_verification": True,
                    "deliverables": [{"kind": "code", "path_hint": "web/home.js"}],
                }
            },
        ),
    ])
    log = (
        "home.js:1 Uncaught TypeError: Cannot set properties of null "
        "(setting 'onclick')\n"
        "Failed to load resource: the server responded with a status of "
        "405 (Method Not Allowed)"
    )

    assert has_recent_task_context(conversation, log)
    assert previous_write_context(conversation, log)
    assert classify_task_intent(log, "terminal", conversation) == "read_only_analysis"
    assert effective_mode(None, log, conversation) == "coding"
    assert previous_task_contract_context(conversation, log)["goal"].startswith("Modify web/home.js")
