from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import base64

import pytest

from runtime.attachment_store import AttachmentStore
from runtime.skills.attachments import extract_attachment_text, read_attachment_image
from runtime.tool_media import MAX_ATTACHMENT_IMAGE_BYTES


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


@pytest.mark.asyncio
async def test_read_image_uses_conversation_attachment_bytes_without_exposing_storage_path(tmp_path):
    store = AttachmentStore(tmp_path / "attachments.db", tmp_path / "attachments")
    try:
        data = b"\x89PNG\r\n\x1a\noriginal"
        record = store.create(workspace_id="w", conversation_id="c", original_name="ref.png", media_type="image/png", content=data)
        store.bind_message([record.id], "previous-user-message")
        context = SimpleNamespace(attachment_store=store, attachment_ids=(record.id,))
        output = await read_attachment_image({"attachment_id": record.id}, context)
        assert output["type"] == "attachment_image"
        assert output["attachment"]["id"] == record.id
        assert base64.b64decode(output["mcp_content"][0]["data"]) == data
        assert output["mcp_content"][0]["mimeType"] == "image/png"
        assert "relative_path" not in output["attachment"]
        assert "path" not in output
        with pytest.raises(PermissionError, match="not available"):
            await read_attachment_image({"attachment_id": record.id}, SimpleNamespace(attachment_store=store, attachment_ids=()))
        with pytest.raises(ValueError, match="text extraction does not support"):
            await extract_attachment_text({"attachment_id": record.id}, context)
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", ["text/plain", "image/svg+xml", "image/bmp"])
async def test_read_image_rejects_unsupported_media(tmp_path, media_type):
    store = AttachmentStore(tmp_path / "attachments.db", tmp_path / "attachments")
    try:
        record = store.create(workspace_id="w", conversation_id="c", original_name="input.bin", media_type=media_type, content=b"data")
        with pytest.raises(ValueError, match="image input does not support media type"):
            await read_attachment_image({"attachment_id": record.id}, SimpleNamespace(attachment_store=store, attachment_ids=(record.id,)))
    finally:
        store.close()


@pytest.mark.asyncio
async def test_read_image_checks_access_before_store_lookup_and_byte_limit_before_read():
    def forbidden(*_args):
        raise AssertionError("unexpected attachment data access")

    context = SimpleNamespace(attachment_ids=(), attachment_store=SimpleNamespace(get=forbidden))
    with pytest.raises(PermissionError):
        await read_attachment_image({"attachment_id": "other-conversation"}, context)
    record = SimpleNamespace(media_type="image/png", size=MAX_ATTACHMENT_IMAGE_BYTES + 1)
    context = SimpleNamespace(attachment_ids=("large",), attachment_store=SimpleNamespace(get=lambda _id: record, read_bytes=forbidden))
    with pytest.raises(ValueError, match="bytes"):
        await read_attachment_image({"attachment_id": "large"}, context)
