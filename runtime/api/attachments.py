from __future__ import annotations

import mimetypes
from urllib.parse import quote

import tornado.web

from .base import ApiHandler


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024


class AttachmentsHandler(ApiHandler):
    def post(self) -> None:
        workspace_id = self.get_body_argument("workspace_id", "").strip()
        conversation_id = self.get_body_argument("conversation_id", "").strip()
        if not workspace_id or not conversation_id:
            raise tornado.web.HTTPError(400, reason="workspace_id and conversation_id are required")
        workspace = self.runtime.workspaces.get(workspace_id)
        conversation = self.runtime.conversations.get(conversation_id)
        if not workspace or not conversation or conversation.workspace_id != workspace_id:
            raise tornado.web.HTTPError(404, reason="workspace or conversation not found")
        uploads = self.request.files.get("file") or []
        if len(uploads) != 1:
            raise tornado.web.HTTPError(400, reason="exactly one file is required")
        upload = uploads[0]
        content = upload.get("body") or b""
        filename = str(upload.get("filename") or "attachment")
        media_type = str(upload.get("content_type") or mimetypes.guess_type(filename)[0] or "")
        limit = MAX_IMAGE_BYTES if media_type.startswith("image/") else MAX_FILE_BYTES
        if not content:
            raise tornado.web.HTTPError(400, reason="file is empty")
        if len(content) > limit:
            raise tornado.web.HTTPError(413, reason=f"file exceeds the {limit // (1024 * 1024)}MB limit")
        record = self.runtime.attachments.create(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            original_name=filename,
            media_type=media_type,
            content=content,
        )
        self.finish_json({"success": True, "data": record.to_public_dict()})


class AttachmentDetailHandler(ApiHandler):
    def get(self, attachment_id: str) -> None:
        record = self.runtime.attachments.get(attachment_id)
        if not record:
            raise tornado.web.HTTPError(404, reason="attachment not found")
        self.finish_json({"success": True, "data": record.to_public_dict()})

    def delete(self, attachment_id: str) -> None:
        try:
            deleted = self.runtime.attachments.delete(attachment_id, require_unbound=True)
        except ValueError as exc:
            raise tornado.web.HTTPError(409, reason=str(exc)) from exc
        if not deleted:
            raise tornado.web.HTTPError(404, reason="attachment not found")
        self.finish_json({"success": True, "data": {"deleted": True}})


class AttachmentContentHandler(ApiHandler):
    def get(self, attachment_id: str) -> None:
        record = self.runtime.attachments.get(attachment_id)
        if not record:
            raise tornado.web.HTTPError(404, reason="attachment not found")
        self.set_header("Content-Type", record.media_type)
        self.set_header("X-Content-Type-Options", "nosniff")
        disposition = "inline" if record.is_image else "attachment"
        self.set_header(
            "Content-Disposition",
            f"{disposition}; filename*=UTF-8''{quote(record.original_name)}",
        )
        self.finish(self.runtime.attachments.read_bytes(attachment_id))
