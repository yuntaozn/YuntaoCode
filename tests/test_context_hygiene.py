from runtime.agent_strategy.context_hygiene import sanitize_model_context


def test_context_hygiene_collapses_old_textual_tool_calls() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "帮我写一个 HTML 示例页"},
        {
            "role": "assistant",
            "content": "我来处理。<toolcall>filesystem.write_file</toolcall>",
        },
        {"role": "user", "content": "上次没成功，请再次尝试"},
    ]

    cleaned, report = sanitize_model_context(messages)
    joined = "\n".join(str(item.get("content") or "") for item in cleaned)

    assert report["changed"] is True
    assert report["tool_markup_messages"] == 1
    assert cleaned[0] == messages[0]
    assert cleaned[1]["role"] == "system"
    assert cleaned[-1] == messages[-1]
    assert "<toolcall" not in joined.lower()
    assert "结构化工具调用" in joined


def test_context_hygiene_keeps_normal_history_unchanged() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "分析当前文件"},
        {"role": "assistant", "content": "这个文件主要包含一个模型查看器。"},
        {"role": "user", "content": "继续说明"},
    ]

    cleaned, report = sanitize_model_context(messages)

    assert cleaned == messages
    assert report["changed"] is False


def test_context_hygiene_summarizes_failure_noise_without_losing_recovery_fact() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "创建 viewer.html"},
        {
            "role": "assistant",
            "content": (
                "未完成：本轮有工具执行失败，系统已按实际执行结果标记为失败。\n"
                "失败记录：\n"
                "- filesystem.write_file: 工具调用缺少必填参数：path, content。"
                "请补全参数后重新发送结构化工具调用；无效调用不会进入人工确认。"
            ),
        },
        {"role": "user", "content": "重新执行一次"},
    ]

    cleaned, report = sanitize_model_context(messages)
    joined = "\n".join(str(item.get("content") or "") for item in cleaned)

    assert report["failed_run_messages"] == 1
    assert "工具参数不完整" in joined
    assert "上一轮或更早的任务执行未能稳定完成" in joined
    assert "filesystem.write_file: 工具调用缺少必填参数" not in joined
    assert cleaned[-1]["content"] == "重新执行一次"


def test_context_hygiene_preserves_latest_user_message_exactly() -> None:
    current = "思考过程\n<toolcall>filesystem.read_file</toolcall>\n这是我正在反馈的问题"
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "assistant", "content": "普通回答"},
        {"role": "user", "content": current},
    ]

    cleaned, report = sanitize_model_context(messages)

    assert report["changed"] is False
    assert cleaned[-1]["content"] == current
