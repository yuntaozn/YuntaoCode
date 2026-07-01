from runtime.agent_strategy.context_noise import (
    classify_context_noise,
    historical_failure_summary,
    historical_process_summary,
    historical_user_feedback_summary,
    strip_tool_markup_like_text,
    truncate,
)


def test_classify_context_noise_detects_textual_tool_markup() -> None:
    noise = classify_context_noise("I will call <toolcall>filesystem.write_file</toolcall>")

    assert noise.has_tool_markup is True
    assert noise.has_failed_run is False


def test_classify_context_noise_detects_chinese_failure_text() -> None:
    noise = classify_context_noise(
        "\u672a\u5b8c\u6210\uff1a\u5de5\u5177\u8c03\u7528\u7f3a\u5c11\u5fc5\u586b\u53c2\u6570"
    )

    assert noise.has_failed_run is True


def test_historical_failure_summary_keeps_paths_as_evidence() -> None:
    content = "tool call failed\n- D:\\code\\demo\\viewer.html\n<toolcall>bad</toolcall>"
    noise = classify_context_noise(content)

    summary = historical_failure_summary(content, noise)

    assert "Historical run summary" in summary
    assert "textual tool-call markup" in summary
    assert "D:\\code\\demo\\viewer.html" in summary
    assert "<toolcall>bad" not in summary


def test_historical_process_and_user_feedback_summaries_are_stable() -> None:
    assert "Historical process summary" in historical_process_summary()
    assert "Historical user feedback summary" in historical_user_feedback_summary()


def test_strip_tool_markup_like_text_replaces_markup_before_truncating() -> None:
    cleaned = strip_tool_markup_like_text(
        "before <toolcall>filesystem.write_file</toolcall> after",
        200,
    )

    assert "<toolcall" not in cleaned.lower()
    assert "[historical tool markup]" in cleaned


def test_truncate_has_minimum_bound() -> None:
    value = truncate("x" * 300, 1)

    assert len(value) > 200
    assert "historical message truncated" in value
