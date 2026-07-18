from __future__ import annotations

from runtime.api.conversations import ConversationMessagesStreamHandler


def test_raw_toolcall_text_triggers_synthesized_final_answer() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    assert handler._needs_synthesized_final_answer(
        'done <toolcall>filesystem__write_file({"path":"demo.html","content":"x"})</toolcall>',
        [{"tool": "filesystem.write_file", "status": "success"}],
    )


def test_answer_only_text_is_not_rejected_by_runtime_style_classifier() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    contract = {
        "intent": "answer_only",
        "requires_write": False,
        "requires_state_change": False,
    }
    content = "I will first check the current project directory."

    assert handler._answer_only_final_answer_error(content, [], contract) == ""
    assert not handler._needs_synthesized_final_answer(content, [], task_contract=contract)


def test_tool_failure_message_prefers_shell_timeout() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    message = handler._tool_event_failure_message({
        "tool": "shell.run_command",
        "status": "failure",
        "input": {"command": "python -m http.server 8000", "timeout": 10},
        "output": {"exit_code": 1, "timed_out": True},
        "error": "command exited with code 1",
    })

    assert message == "command timed out after 10s"


def test_partial_run_uses_truthful_synthesized_answer() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    answer = handler._synthesize_partial_answer(
        r"D:\ifctool",
        [],
        {
            "status": "partial",
            "changed_paths": ["viewer.html"],
            "failures": [
                {
                    "tool": "filesystem.write_file",
                    "path": "viewer.html",
                    "error": "path is required",
                }
            ],
            "risks": ["test_not_observed", "partial_write_failure"],
            "counts": {"test_successes": 0},
        },
    )

    assert answer.startswith("运行事实摘要")
    assert "viewer.html" in answer
    assert "path is required" in answer
    assert "建议：下一轮应基于这些事实继续修正或补充验证" in answer
