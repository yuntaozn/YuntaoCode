from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from runtime.api.conversations import ConversationMessagesStreamHandler
from runtime.conversation_interactions import confirm_responses, pending_confirms
from runtime.product_task_store import ProductTaskStore
from runtime.run_events import RunEventHub
from runtime.run_store import RunStore


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "paused"), [("continue", False), ("cancel", False), ("continue", True)])
async def test_confirmation_resolution_preserves_task_state_and_explicit_pause(tmp_path, action, paused):
    tasks = ProductTaskStore(tmp_path / "tasks.db")
    runs = RunStore(store_path=tmp_path / "runs.json")
    task = tasks.create(goal="Change application state")
    run = runs.create(conversation_id="confirm-conversation", workspace_id="workspace", mode="terminal", user_content="create", task_id=task.id)
    tasks.attach_run(task.id, run.id)
    hub = RunEventHub(runs, product_tasks=tasks)
    handler = object.__new__(ConversationMessagesStreamHandler)
    handler.runtime = SimpleNamespace(runs=runs)
    handler._active_conversation_id = run.conversation_id
    handler._active_run_id = run.id
    handler.write_event = lambda event: hub.emit(run.id, event)
    handler._runtime_confirmation_message = lambda *_args: "Confirm operation"

    async def flush():
        return None

    handler.flush = flush
    waiting = asyncio.create_task(handler._confirm_runtime_tool_call("mcp_app.execute", {}, SimpleNamespace(to_dict=lambda: {})))
    await asyncio.sleep(0)
    assert runs.get(run.id).status == "waiting_confirmation"
    if paused:
        hub.emit(run.id, {"event": "status", "status": "paused"})
    confirm_responses[run.conversation_id] = action
    pending_confirms[run.conversation_id].set()
    assert await waiting is (action == "continue")
    expected = "paused" if paused else "running"
    assert runs.get(run.id).status == expected
    assert tasks.get(task.id).state == expected
    assert run.conversation_id not in pending_confirms
    tasks.close()
    runs.close()
