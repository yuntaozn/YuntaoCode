from __future__ import annotations

import tornado.web

from .base import ApiHandler


class CapabilityPacksHandler(ApiHandler):
    def get(self) -> None:
        include_archived = str(self.get_query_argument("include_archived", "")).lower() in {"1", "true", "yes"}
        self.finish_json({
            "success": True,
            "data": [item.to_dict() for item in self.runtime.capability_packs.list(include_archived=include_archived)],
            "meta": {
                "root": str(self.runtime.capability_packs.root_path),
                "items_root": str(self.runtime.capability_packs.items_path),
                "exports_root": str(self.runtime.capability_packs.exports_path),
            },
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        try:
            pack = self.runtime.capability_packs.create(payload)
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.finish_json({"success": True, "data": pack.to_dict()})


class CapabilityPackDetailHandler(ApiHandler):
    def get(self, pack_id: str) -> None:
        pack = self.runtime.capability_packs.get(pack_id)
        if not pack:
            raise tornado.web.HTTPError(404, reason="capability pack not found")
        self.finish_json({"success": True, "data": pack.to_dict()})

    def put(self, pack_id: str) -> None:
        payload = self.parse_json_body()
        if not self.runtime.capability_packs.get(pack_id):
            raise tornado.web.HTTPError(404, reason="capability pack not found")
        try:
            pack = self.runtime.capability_packs.update(pack_id, payload)
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.finish_json({"success": True, "data": pack.to_dict()})

    def delete(self, pack_id: str) -> None:
        if not self.runtime.capability_packs.delete(pack_id):
            raise tornado.web.HTTPError(404, reason="capability pack not found")
        self.finish_json({"success": True, "data": {"deleted": pack_id}})


class CapabilityPackActionHandler(ApiHandler):
    def post(self, pack_id: str) -> None:
        payload = self.parse_json_body()
        action = str(payload.get("action") or "").strip().lower()
        if not self.runtime.capability_packs.get(pack_id):
            raise tornado.web.HTTPError(404, reason="capability pack not found")

        if action in {"enable", "disable", "archive", "testing", "fail"}:
            state = {
                "enable": "enabled",
                "disable": "disabled",
                "archive": "archived",
                "testing": "testing",
                "fail": "failed",
            }[action]
            pack = self.runtime.capability_packs.set_state(pack_id, state)
            self.finish_json({"success": True, "data": pack.to_dict()})
            return

        if action == "export":
            try:
                bundle = self.runtime.capability_packs.export_bundle(pack_id)
            except PermissionError as exc:
                raise tornado.web.HTTPError(403, reason=str(exc)) from exc
            self.finish_json({"success": True, "data": bundle})
            return

        raise tornado.web.HTTPError(
            400,
            reason="action must be enable, disable, archive, testing, fail, or export",
        )
