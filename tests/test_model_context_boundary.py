from runtime.agent_strategy.model_context_boundary import (
    current_request_boundary_notice,
    historical_task_candidate_marker,
    historical_task_turns_marker,
    historical_user_request_marker,
    insert_current_request_boundary,
    insert_hygiene_notice,
    is_historical_task_marker,
    marker_candidate_id,
    model_context_hygiene_notice,
)


def test_hygiene_notice_describes_boundary_without_task_decision() -> None:
    notice = model_context_hygiene_notice()

    assert "Context hygiene" in notice
    assert "Visible chat history and audit records are unchanged" in notice
    assert "structured runtime tool calls" in notice


def test_current_request_boundary_inserted_before_latest_user() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "old task"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current task"},
    ]

    updated, inserted = insert_current_request_boundary(messages)

    assert inserted is True
    assert updated[-2] == {"role": "system", "content": current_request_boundary_notice()}
    assert updated[-1] == {"role": "user", "content": "current task"}


def test_current_request_boundary_is_idempotent() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "system", "content": current_request_boundary_notice()},
        {"role": "user", "content": "current task"},
    ]

    updated, inserted = insert_current_request_boundary(messages)

    assert inserted is False
    assert updated == messages


def test_hygiene_notice_inserted_after_system_prompt() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "current task"},
    ]

    updated = insert_hygiene_notice(messages)

    assert updated[0] == messages[0]
    assert updated[1] == {"role": "system", "content": model_context_hygiene_notice()}
    assert updated[2] == messages[1]


def test_historical_task_markers_are_parseable() -> None:
    candidate = historical_task_candidate_marker("candidate-1")
    user = historical_user_request_marker("candidate-1")

    assert is_historical_task_marker(candidate) is True
    assert is_historical_task_marker(user) is True
    assert marker_candidate_id(candidate) == "candidate-1"
    assert marker_candidate_id(user) == "candidate-1"
    assert "current goal" in candidate
    assert "current goal" in user


def test_compacted_historical_task_turns_marker_deduplicates_ids() -> None:
    marker = historical_task_turns_marker(["candidate-1", "candidate-1", "candidate-2"])

    assert "Historical task turns moved to Context Pack" in marker
    assert "candidate_ids=candidate-1, candidate-2" in marker
