from __future__ import annotations

import asyncio
import json

import tornado.iostream
import tornado.web

from .base import ApiHandler
from runtime.conversation_interactions import (
    active_run_tasks as _active_run_tasks,
    active_stream_conversation_runs as _active_stream_conversation_runs,
    confirm_responses as _confirm_responses,
    pending_confirms as _pending_confirms,
    paused_runs as _paused_runs,
)
from runtime.diagnostic_export import build_diagnostic_export
from runtime.evaluation.fixtures import build_evaluation_fixture_export
from runtime.evaluation.reports import build_evaluation_report
from runtime.run_evidence import build_run_evidence
from runtime.runbook import build_replay_request, build_runbook
from runtime.skill_sample_export import build_skill_sample_export


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


class RunActionHandler(ApiHandler):
    def post(self, run_id: str) -> None:
        run = self.runtime.runs.get(run_id)
        if not run:
            raise tornado.web.HTTPError(404, reason="run not found")
        payload = self.parse_json_body()
        action = str(payload.get("action") or "").strip().lower()
        reason = str(payload.get("reason") or "").strip()
        if action == "pause":
            self._pause(run_id, reason)
            return
        if action in {"stop", "cancel"}:
            self._stop(run_id, reason)
            return
        if action == "resume":
            self._resume(run_id, reason)
            return
        if action == "runbook":
            self.finish_json({"success": True, "data": build_runbook(run)})
            return
        if action == "evidence":
            self.finish_json({"success": True, "data": build_run_evidence(run)})
            return
        if action == "export_diagnostic":
            self.finish_json({"success": True, "data": build_diagnostic_export(self.runtime, run)})
            return
        if action == "export_fixture":
            self.finish_json({"success": True, "data": build_skill_sample_export(run)})
            return
        if action == "export_evaluation_fixture":
            self.finish_json({"success": True, "data": build_evaluation_fixture_export(run)})
            return
        if action == "evaluate_fixture":
            fixture = payload.get("fixture") or payload.get("evaluation_fixture")
            if not isinstance(fixture, dict):
                raise tornado.web.HTTPError(400, reason="fixture is required for evaluate_fixture")
            self.finish_json({
                "success": True,
                "data": build_evaluation_report(fixture, build_run_evidence(run)),
            })
            return
        if action == "replay":
            self.finish_json({"success": True, "data": self._prepare_new_run(run, recovery=False)})
            return
        raise tornado.web.HTTPError(
            400,
            reason=(
                "action must be pause, stop, resume, evidence, runbook, export_diagnostic, "
                "export_fixture, export_evaluation_fixture, evaluate_fixture, or replay"
            ),
        )

    def _pause(self, run_id: str, reason: str) -> None:
        run = self.runtime.runs.get(run_id)
        if not run:
            raise tornado.web.HTTPError(404, reason="run not found")
        if run.status in {"success", "failure", "stopped", "partial", "cancelled"}:
            raise tornado.web.HTTPError(409, reason=f"run is already finished: {run.status}")
        if run.status == "paused":
            self.finish_json({"success": True, "data": run.to_public_dict()})
            return
        self.runtime.run_events.emit(run_id, {
            "event": "status",
            "status": "paused",
            "message": reason or "run paused by user",
        })
        if run.task_id:
            latest_snapshots = self.runtime.product_tasks.list_context_snapshots(run_id=run.id)
            self.runtime.product_tasks.create_checkpoint(
                task_id=run.task_id,
                run_id=run.id,
                kind="pause",
                state="paused",
                context_snapshot_id=latest_snapshots[0]["id"] if latest_snapshots else "",
                data={"reason": reason or "run paused by user", "stage": run.stage},
            )
        updated = self.runtime.runs.get(run_id) or run
        self.finish_json({"success": True, "data": updated.to_public_dict()})

    def _stop(self, run_id: str, reason: str) -> None:
        run = self.runtime.runs.get(run_id)
        if not run:
            raise tornado.web.HTTPError(404, reason="run not found")
        if run.status in {"success", "failure", "stopped", "partial", "cancelled"}:
            self.finish_json({"success": True, "data": run.to_public_dict()})
            return
        self.runtime.run_events.emit(run_id, {
            "event": "status",
            "status": "stopped",
            "message": reason or "run stopped by user",
        })
        pause_event = _paused_runs.pop(run_id, None)
        if pause_event:
            pause_event.set()
        if run.conversation_id:
            confirm_event = _pending_confirms.get(run.conversation_id)
            if confirm_event:
                _confirm_responses[run.conversation_id] = "cancel"
                confirm_event.set()
            else:
                _confirm_responses.pop(run.conversation_id, None)
            if _active_stream_conversation_runs.get(run.conversation_id) == run_id:
                _active_stream_conversation_runs.pop(run.conversation_id, None)
        task = _active_run_tasks.pop(run_id, None)
        if task and not task.done():
            task.cancel()
        updated = self.runtime.runs.get(run_id) or run
        self.finish_json({"success": True, "data": updated.to_public_dict()})

    def _resume(self, run_id: str, reason: str) -> None:
        run = self.runtime.runs.get(run_id)
        if not run:
            raise tornado.web.HTTPError(404, reason="run not found")
        if run.status in {"stopped", "failure", "partial"}:
            self.finish_json({"success": True, "data": self._prepare_new_run(run, recovery=True)})
            return
        if run.status != "paused":
            raise tornado.web.HTTPError(409, reason=f"run is not paused or recoverable: {run.status}")
        self.runtime.run_events.emit(run_id, {
            "event": "status",
            "status": "resumed",
            "message": reason or "run resumed by user",
        })
        event = _paused_runs.pop(run_id, None)
        if event:
            event.set()
        updated = self.runtime.runs.get(run_id) or run
        self.finish_json({"success": True, "data": updated.to_public_dict()})

    def _prepare_new_run(self, source_run: object, *, recovery: bool) -> dict:
        task_id = str(getattr(source_run, "task_id", "") or "")
        task = self.runtime.product_tasks.get(task_id) if task_id else None
        if not task:
            task = self.runtime.product_tasks.create(
                goal=str(getattr(source_run, "user_content", "") or ""),
                conversation_id=str(getattr(source_run, "conversation_id", "") or ""),
                workspace_id=str(getattr(source_run, "workspace_id", "") or ""),
                kind="recovered_legacy_run",
                metadata={"source_run_id": str(getattr(source_run, "id", "") or "")},
            )
            task_id = task.id
        checkpoints = self.runtime.product_tasks.list_checkpoints(run_id=str(getattr(source_run, "id", "") or ""))
        checkpoint_id = checkpoints[0]["id"] if recovery and checkpoints else ""
        prepared = self.runtime.runs.create(
            conversation_id=str(getattr(source_run, "conversation_id", "") or ""),
            workspace_id=str(getattr(source_run, "workspace_id", "") or ""),
            mode=str(getattr(source_run, "mode", "") or "terminal"),
            user_content=str(getattr(source_run, "user_content", "") or ""),
            task_id=task_id,
            parent_run_id=str(getattr(source_run, "id", "") or ""),
            source_run_id=str(getattr(source_run, "id", "") or ""),
            attempt=max(1, int(getattr(source_run, "attempt", 1) or 1) + 1),
            resume_from_checkpoint_id=checkpoint_id,
            status="created",
        )
        self.runtime.product_tasks.attach_run(task_id, prepared.id, state="created")
        replay = build_replay_request(source_run)
        replay["prepared_run"] = prepared.to_public_dict()
        replay["resume_from_checkpoint_id"] = checkpoint_id
        replay["boundary"] = "explicit_start_required"
        return replay


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

            if run.status in {"success", "failure", "partial", "stopped", "cancelled"}:
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
