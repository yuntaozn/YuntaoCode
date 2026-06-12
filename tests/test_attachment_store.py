from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.attachment_store import AttachmentStore
from runtime.skills.attachments import extract_attachment_text


def test_attachment_store_persists_and_binds_immutable_input(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db", tmp_path / "attachments")
    record = store.create(
        workspace_id="workspace-1",
        conversation_id="conversation-1",
        original_name="../notes.txt",
        media_type="text/plain",
        content="hello attachment".encode(),
    )

    assert record.original_name == "notes.txt"
    assert "relative_path" not in record.to_public_dict()
    assert store.read_bytes(record.id) == b"hello attachment"
    assert store.validate_for_message(
        [record.id],
        workspace_id="workspace-1",
        conversation_id="conversation-1",
    )[0].id == record.id

    store.bind_message([record.id], "message-1")

    assert store.get(record.id).message_id == "message-1"
    with pytest.raises(ValueError, match="already bound"):
        store.validate_for_message(
            [record.id],
            workspace_id="workspace-1",
            conversation_id="conversation-1",
        )
    with pytest.raises(ValueError, match="cannot be deleted"):
        store.delete(record.id)
    assert store.delete_for_conversation("conversation-1") == 1
    assert store.get(record.id) is None
    store.close()


def test_attachment_store_builds_image_data_url(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db", tmp_path / "attachments")
    record = store.create(
        workspace_id="workspace-1",
        conversation_id="conversation-1",
        original_name="pixel.png",
        media_type="image/png",
        content=b"png",
    )

    assert record.is_image is True
    assert store.data_url(record.id) == "data:image/png;base64,cG5n"
    store.close()


def test_svg_attachment_is_not_treated_as_inline_image(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db", tmp_path / "attachments")
    record = store.create(
        workspace_id="workspace-1",
        conversation_id="conversation-1",
        original_name="unsafe.svg",
        media_type="image/svg+xml",
        content=b"<svg></svg>",
    )

    assert record.is_image is False
    store.close()


@pytest.mark.asyncio
async def test_read_attachment_text_requires_current_run_access(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "attachments.db", tmp_path / "attachments")
    record = store.create(
        workspace_id="workspace-1",
        conversation_id="conversation-1",
        original_name="notes.txt",
        media_type="text/plain",
        content=b"hello",
    )
    context = SimpleNamespace(attachment_store=store, attachment_ids=(record.id,))

    result = await extract_attachment_text({"attachment_id": record.id}, context)

    assert result["content"] == "hello"
    with pytest.raises(PermissionError, match="not available"):
        await extract_attachment_text({"attachment_id": "other"}, context)
    store.close()
