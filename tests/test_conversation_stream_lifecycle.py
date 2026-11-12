import asyncio
from types import SimpleNamespace

import pytest
import tornado.web

from runtime.api import conversations as api
from runtime.api.runs import RunActionHandler
from runtime.product_task_store import ProductTaskStore
from runtime.run_events import RunEventHub
from runtime.run_store import RunStore


@pytest.fixture
def stream_context(tmp_path, monkeypatch):
    runs = RunStore(tmp_path / "runs.json")
    tasks = ProductTaskStore(tmp_path / "tasks.db")
    messages, events, settings_updates = [], [], []

    def add_message(*_args):
        message = SimpleNamespace(id=f"message-{len(messages)}", to_public_dict=lambda: {})
        messages.append(message)
        return message

    runtime = SimpleNamespace(
        conversations=SimpleNamespace(get=lambda _id: SimpleNamespace(workspace_id="workspace"), add_message=add_message),
        workspaces=SimpleNamespace(get=lambda _id: object()),
        attachments=SimpleNamespace(validate_for_message=lambda *_args, **_kwargs: [], bind_message=lambda *_args: None),
        settings=SimpleNamespace(get_default_model=lambda: "demo", update=settings_updates.append),
        runs=runs, product_tasks=tasks,
    )
    runtime.run_events = RunEventHub(runs, product_tasks=tasks)

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        async def execute(self, **kwargs):
            runtime.run_events.emit(kwargs["run"].id, {"event": "done", "run_status": "success"})

    monkeypatch.setattr(api, "ConversationRunExecutor", Executor)

    def handler(payload=None):
        instance = object.__new__(api.ConversationMessagesStreamHandler)
        instance.runtime = runtime
        instance.parse_json_body = lambda: {"content": "Inspect project", **(payload or {})}
        instance.set_header = lambda *_args: None
        instance._effective_mode = lambda *_args: "terminal"
        instance.write_event = events.append
        instance.write_json_line = events.append

        async def flush():
            pass

        instance.flush = flush
        return instance

    yield SimpleNamespace(runtime=runtime, handler=handler, messages=messages, events=events, settings_updates=settings_updates)
    api._active_stream_conversation_runs.pop("conv", None)
    runs.close()
    tasks.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,code", [
    ({"prepared_run_id": "missing"}, 404),
    ({"task_id": "missing"}, 404),
    ({"source_run_id": "missing"}, 409),
])
async def test_rejected_request_does_not_persist_or_reserve_and_retry_can_start(stream_context, payload, code):
    ctx = stream_context
    for _ in range(2):
        with pytest.raises(tornado.web.HTTPError) as error:
            await ctx.handler({**payload, "access_scope": "workspace"}).post("conv")
        assert error.value.status_code == code
    assert ctx.messages == []
    assert ctx.events == []
    assert ctx.settings_updates == []
    assert "conv" not in api._active_stream_conversation_runs
    await ctx.handler().post("conv")
    await asyncio.sleep(0)
    assert len(ctx.messages) == 1
    assert [event["event"] for event in ctx.events] == ["user", "run", "done"]
    assert "conv" not in api._active_stream_conversation_runs


@pytest.mark.asyncio
async def test_source_scope_is_checked_even_with_explicit_task(stream_context):
    ctx = stream_context
    task = ctx.runtime.product_tasks.create(goal="Inspect", conversation_id="conv", workspace_id="workspace")
    source = ctx.runtime.runs.create(conversation_id="another", workspace_id="workspace", mode="terminal", user_content="Inspect")
    with pytest.raises(tornado.web.HTTPError, match="another conversation"):
        await ctx.handler({"task_id": task.id, "source_run_id": source.id}).post("conv")
    assert ctx.messages == []


@pytest.mark.asyncio
async def test_cancelled_setup_releases_only_its_reservation(stream_context):
    ctx = stream_context
    first = ctx.handler()
    entered = asyncio.Event()

    async def wait_flush():
        entered.set()
        await asyncio.Event().wait()

    first.flush = wait_flush
    request = asyncio.create_task(first.post("conv"))
    await entered.wait()
    with pytest.raises(tornado.web.HTTPError) as error:
        await ctx.handler().post("conv")
    assert error.value.status_code == 409
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert "conv" not in api._active_stream_conversation_runs
    await ctx.handler().post("conv")
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_failure_after_run_creation_closes_run_and_releases_reservation(stream_context):
    ctx = stream_context
    handler = ctx.handler()
    count = 0

    async def fail_second_flush():
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("setup failed")

    handler.flush = fail_second_flush
    with pytest.raises(RuntimeError, match="setup failed"):
        await handler.post("conv")
    run = ctx.runtime.runs.list(conversation_id="conv")[0]
    assert (run.status, run.stage) == ("failure", "done")
    assert ctx.runtime.product_tasks.get(run.task_id).state == "failed"
    assert "conv" not in api._active_stream_conversation_runs
    await ctx.handler().post("conv")
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_disconnected_stream_keeps_execution_controllable_until_stop(stream_context, monkeypatch):
    ctx = stream_context
    entered = asyncio.Event()

    class Executor:
        def __init__(self, *_args, **_kwargs):
            pass

        async def execute(self, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(api, "ConversationRunExecutor", Executor)
    handler = ctx.handler()
    handler._client_stream_closed = True
    await handler.post("conv")
    await entered.wait()
    run_id = api._active_stream_conversation_runs["conv"]
    execution = api._active_run_tasks[run_id]
    assert not execution.done()
    with pytest.raises(tornado.web.HTTPError) as error:
        await ctx.handler().post("conv")
    assert error.value.status_code == 409
    stop = object.__new__(RunActionHandler)
    stop.runtime = ctx.runtime
    stop.finish_json = lambda _value: None
    stop._stop(run_id, "stop test")
    with pytest.raises(asyncio.CancelledError):
        await execution
    await asyncio.sleep(0)
    run = ctx.runtime.runs.get(run_id)
    assert (run.status, run.stage) == ("stopped", "done")
    assert run_id not in api._active_run_tasks
    assert "conv" not in api._active_stream_conversation_runs
