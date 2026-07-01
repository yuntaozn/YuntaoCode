from runtime.agent_strategy.context_hygiene import sanitize_model_context


def test_context_hygiene_collapses_old_textual_tool_calls() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Create an HTML demo page"},
        {
            "role": "assistant",
            "content": "I will do it. <toolcall>filesystem.write_file</toolcall>",
        },
        {"role": "user", "content": "Try again; it failed last time"},
    ]

    cleaned, report = sanitize_model_context(messages)
    joined = "\n".join(str(item.get("content") or "") for item in cleaned)

    assert report["changed"] is True
    assert report["tool_markup_messages"] == 1
    assert report["current_request_boundary_inserted"] is True
    assert cleaned[0] == messages[0]
    assert cleaned[1]["role"] == "system"
    assert cleaned[-1] == messages[-1]
    assert "<toolcall" not in joined.lower()
    assert "structured runtime tool calls" in joined
    assert "Current request boundary" in joined


def test_context_hygiene_keeps_normal_history_unchanged() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Analyze the current file"},
        {"role": "assistant", "content": "It contains a model viewer."},
        {"role": "user", "content": "Continue the explanation"},
    ]

    cleaned, report = sanitize_model_context(messages)

    assert cleaned == messages
    assert report["changed"] is False
    assert report["current_request_boundary_inserted"] is False


def test_context_hygiene_moves_prior_task_turns_to_context_pack_marker() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Create a Blender house"},
        {
            "role": "assistant",
            "content": "I changed the scene.",
            "_yuntao_metadata": {
                "run_id": "run-1",
                "task_contract": {
                    "goal": "Create a Blender house",
                    "intent": "write_required",
                    "requires_write": False,
                    "requires_state_change": True,
                    "deliverables": [{"kind": "external_state"}],
                    "capability_ids": ["mcp.blender"],
                },
            },
        },
        {"role": "user", "content": "Now update the teaching page code"},
    ]

    cleaned, report = sanitize_model_context(messages)
    joined = "\n".join(str(item.get("content") or "") for item in cleaned)

    assert report["task_candidate_messages"] == 1
    assert report["task_user_anchor_messages"] == 1
    assert report["compacted_task_marker_messages"] == 1
    assert report["current_request_boundary_inserted"] is True
    assert "task_lineage_context.v1" not in joined
    assert "Historical task turns moved to Context Pack" in joined
    assert "Historical task candidate moved to Context Pack" not in joined
    assert "Historical task user request moved to Context Pack" not in joined
    assert "I changed the scene." not in joined
    assert "Create a Blender house" not in joined
    assert "Current request boundary" in joined
    assert cleaned[-1] == {"role": "user", "content": "Now update the teaching page code"}
    marker_messages = [
        item for item in cleaned
        if "moved to Context Pack" in str(item.get("content") or "")
    ]
    assert marker_messages
    assert {item["role"] for item in marker_messages} == {"system"}
    assert all("_yuntao_metadata" not in item for item in cleaned)


def test_context_hygiene_summarizes_failure_noise_without_losing_recovery_fact() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Create viewer.html"},
        {
            "role": "assistant",
            "content": (
                "The run failed because a tool call failed.\n"
                "Failure records:\n"
                "- filesystem.write_file: required arguments are missing: path, content.\n"
                "Invalid tool calls will not enter confirmation."
            ),
        },
        {"role": "user", "content": "Run it again"},
    ]

    cleaned, report = sanitize_model_context(messages)
    joined = "\n".join(str(item.get("content") or "") for item in cleaned)

    assert report["failed_run_messages"] == 1
    assert report["current_request_boundary_inserted"] is True
    assert "Historical run summary" in joined
    assert "required arguments" in joined
    assert "filesystem.write_file: required arguments are missing" not in joined
    assert cleaned[-1] == {"role": "user", "content": "Run it again"}


def test_context_hygiene_summarizes_chinese_failure_noise() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "create file"},
        {
            "role": "assistant",
            "content": (
                "\u672a\u5b8c\u6210\uff1a\u672c\u8f6e\u6709\u5de5\u5177\u6267\u884c\u5931\u8d25\n"
                "\u5931\u8d25\u8bb0\u5f55\uff1a\n"
                "- filesystem.write_file: \u5de5\u5177\u8c03\u7528\u7f3a\u5c11\u5fc5\u586b\u53c2\u6570"
            ),
        },
        {"role": "user", "content": "try again"},
    ]

    cleaned, report = sanitize_model_context(messages)
    joined = "\n".join(str(item.get("content") or "") for item in cleaned)

    assert report["failed_run_messages"] == 1
    assert "Historical run summary" in joined
    assert "filesystem.write_file:" not in joined
    assert cleaned[-1] == {"role": "user", "content": "try again"}


def test_context_hygiene_preserves_latest_user_message_exactly() -> None:
    current = (
        "Thinking process\n"
        "<toolcall>filesystem.read_file</toolcall>\n"
        "This is the issue I am reporting now."
    )
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "assistant", "content": "normal answer"},
        {"role": "user", "content": current},
    ]

    cleaned, report = sanitize_model_context(messages)

    assert report["changed"] is False
    assert cleaned[-1]["content"] == current
