from __future__ import annotations

from types import SimpleNamespace

from runtime.api.conversations import (
    _latest_user_message_id,
    _message_content_with_attachment_catalog,
)


def test_latest_user_message_id_returns_current_user_turn() -> None:
    conversation = SimpleNamespace(messages=[
        SimpleNamespace(id="user-1", role="user"),
        SimpleNamespace(id="assistant-1", role="assistant"),
        SimpleNamespace(id="user-2", role="user"),
    ])

    assert _latest_user_message_id(conversation) == "user-2"


def test_current_attachment_catalog_is_current_request_scoped() -> None:
    text = _message_content_with_attachment_catalog(
        "请处理这个文件",
        {
            "attachments": [
                {
                    "id": "att-current",
                    "name": "paper.pdf",
                    "media_type": "application/pdf",
                    "size": 1234,
                }
            ]
        },
    )

    assert "Current user-provided immutable conversation attachments" in text
    assert "Use attachment.extract_text" in text
    assert "att-current" in text
    assert "Historical message attachments" not in text


def test_historical_attachment_catalog_is_not_current_request_scoped() -> None:
    text = _message_content_with_attachment_catalog(
        "之前的文件",
        {
            "attachments": [
                {
                    "id": "att-old",
                    "name": "old.pdf",
                    "media_type": "application/pdf",
                    "size": 5678,
                }
            ]
        },
        historical=True,
    )

    assert "Historical message attachments from an earlier turn" in text
    assert "historical context candidates only" in text
    assert "current user-provided" not in text.lower()
    assert "att-old" in text
