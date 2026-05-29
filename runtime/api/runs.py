from __future__ import annotations

import asyncio
import json

import tornado.iostream
import tornado.web

from .base import ApiHandler


class RunsHandler(ApiHandler):
    def get(self) -> None:
        conversation_id = self.get_argument("conversation_id", None)
        workspace_id = self.get_argument("workspace_id", None)
        status = self.get_argument("status", None)
        runs = self.runtime.runs.list(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            status=status,
        )
        self.finish_json({
            "success": True,
            "data": [item.to_public_dict() for item in runs],
        })


class RunDetailHandler(ApiHandler):
    def get(self, run_id: str) -> None:
        run = self.runtime.runs.get(run_id)
        if not run:
            raise tornado.web.HTTPError(404, reason="run not found")
        self.finish_json({
            "success": True,
            "data": run.to_public_dict(include_events=True),
        })


class RunEventsStreamHandler(ApiHandler):
    async def get(self, run_id: str) -> None:
        run = self.runtime.runs.get(run_id)
        if not run:
            raise tornado.web.HTTPError(404, reason="run not found")

        self.set_header("Content-Type", "application/x-ndjson; charset=utf-8")
        cursor = self._cursor()

        try:
            for index, event in enumerate(run.events[cursor:], start=cursor):
                self._write_event(index, run_id, event)
            await self.flush()

            if run.status in {"success", "failure", "stopped"}:
                self._write_stream_done(run_id)
                await self.flush()
                return

            queue = self.runtime.run_events.subscribe(run_id)
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        self.write(json.dumps({
                            "event": "heartbeat",
                            "run_id": run_id,
                            "message": "run still active",
                        }, ensure_ascii=False) + "\n")
                        await self.flush()
                        continue

                    current = self.runtime.runs.get(run_id)
                    index = max(0, len(current.events) - 1) if current else None
                    self._write_event(index, run_id, event)
                    await self.flush()
                    if event.get("event") in {"done", "error"}:
                        break
            finally:
                self.runtime.run_events.unsubscribe(run_id, queue)
        except tornado.iostream.StreamClosedError:
            return

    def _cursor(self) -> int:
        value = self.get_argument("cursor", "0")
        try:
            cursor = int(value)
        except ValueError:
            cursor = 0
        return max(0, cursor)

    def _write_event(self, index: int | None, run_id: str, event: dict) -> None:
        self.write(json.dumps({
            "event": "run_event",
            "run_id": run_id,
            "index": index,
            "data": event,
        }, ensure_ascii=False) + "\n")

    def _write_stream_done(self, run_id: str) -> None:
        self.write(json.dumps({
            "event": "stream_done",
            "run_id": run_id,
        }, ensure_ascii=False) + "\n")
