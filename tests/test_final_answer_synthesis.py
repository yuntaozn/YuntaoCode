from __future__ import annotations

from runtime.api.conversations import ConversationMessagesStreamHandler


def test_raw_toolcall_text_triggers_synthesized_final_answer() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)

    assert handler._needs_synthesized_final_answer(
        '已完成。<toolcall>filesystem__write_file({"path":"demo.html","content":"x"})</toolcall>',
        [{"tool": "filesystem.write_file", "status": "success"}],
    )


def test_answer_only_dangling_text_without_tools_is_invalid_final_answer() -> None:
    handler = object.__new__(ConversationMessagesStreamHandler)
    contract = {
        "intent": "answer_only",
        "requires_write": False,
        "requires_state_change": False,
    }
    content = "我来帮你了解 Blender MCP 的安装方法。首先让我查看一下当前项目目录的情况。"

    assert handler._answer_only_final_answer_error(content, [], contract)
    assert handler._needs_synthesized_final_answer(content, [], task_contract=contract)


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

    assert answer.startswith("未完整完成")
    assert "viewer.html" in answer
    assert "path is required" in answer
    assert "不能把本轮视为目标已完成" in answer
