from runtime.user_guidance import (
    add_user_guidance,
    clear_user_guidance,
    has_pending_user_guidance,
    pop_user_guidance,
)


def test_user_guidance_queue_pops_prompt_without_intervention_word() -> None:
    conversation_id = "conv-guidance-a"
    clear_user_guidance(conversation_id)

    assert add_user_guidance(conversation_id, "先看最新要求") == 1
    assert has_pending_user_guidance(conversation_id)

    batch = pop_user_guidance(conversation_id)

    assert batch.items == ("先看最新要求",)
    assert "运行中插话" in batch.prompt
    assert "干预" not in batch.prompt
    assert not has_pending_user_guidance(conversation_id)


def test_user_guidance_queue_keeps_latest_items() -> None:
    conversation_id = "conv-guidance-limit"
    clear_user_guidance(conversation_id)

    for index in range(5):
        add_user_guidance(conversation_id, f"item-{index}", limit=3)

    batch = pop_user_guidance(conversation_id)

    assert batch.items == ("item-2", "item-3", "item-4")


def test_empty_user_guidance_is_ignored() -> None:
    conversation_id = "conv-guidance-empty"
    clear_user_guidance(conversation_id)

    assert add_user_guidance(conversation_id, "   ") == 0
    assert pop_user_guidance(conversation_id).items == ()
