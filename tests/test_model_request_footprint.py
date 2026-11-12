"""使用完整 Runtime 与真实请求构造，仅替换模型传输，防止轻量 fake 掩盖上下文膨胀。"""

import json
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path

import pytest
import tornado.web
from tornado.simple_httpclient import HTTPTimeoutError

from runtime import app as app_module
from runtime import conversation_runner as runner_module
from runtime.api.conversations import ConversationMessagesStreamHandler
from runtime.config import RuntimeConfig
from runtime.settings_store import SettingsStore
from runtime.model_providers import client as provider_client
from runtime.tool_call_loop import ToolCallLoop
from runtime.tool_discovery import DISCOVERY_TOOL_NAME
from runtime.tool_registry import ToolSpec


@pytest.fixture
def full_runtime(tmp_path, monkeypatch):
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    settings = SettingsStore(tmp_path / "data" / "settings.json")
    settings.update({"confirmation_policy": "aggressive"})
    monkeypatch.setattr(settings, "is_memory_auto_extract_enabled", lambda: False)
    monkeypatch.setattr(app_module, "SettingsStore", lambda: settings)
    runtime = app_module.build_runtime(RuntimeConfig.build("127.0.0.1", 0, "test", [str(workspace_path)]))
    workspace = runtime.workspaces.add(str(workspace_path))
    yield runtime, workspace
    runtime.close()
    runtime.product_tasks.close()


def tool_round(name, **arguments):
    return [{"tool_calls": [{"index": 0, "id": f"call-{name}", "function": {
        "name": name.replace(".", "__"), "arguments": json.dumps(arguments),
    }}]}, {"finish_reason": "tool_calls"}]


async def execute(full_runtime, monkeypatch, content, rounds, *, confirmation_policy="aggressive", on_round_finished=None, transport=None, conversation=None):
    runtime, workspace = full_runtime
    calls = []

    async def stream(**kwargs):
        calls.append(deepcopy(kwargs))
        assert len(calls) <= len(rounds), "unexpected model round"
        if transport is not None:
            async for event in transport(**kwargs):
                yield event
        else:
            for event in rounds[len(calls) - 1]:
                if isinstance(event, Exception):
                    raise event
                yield event
        if on_round_finished is not None:
            await on_round_finished(len(calls))

    monkeypatch.setattr(runner_module, "ToolCallLoop", lambda **kw: ToolCallLoop(**kw, stream_factory=stream))
    conversation = conversation or runtime.conversations.create(workspace.id)
    runtime.conversations.add_message(conversation.id, "user", content)
    task = runtime.product_tasks.create(goal=content, conversation_id=conversation.id, workspace_id=workspace.id)
    run = runtime.runs.create(conversation_id=conversation.id, workspace_id=workspace.id, mode="terminal", user_content=content, task_id=task.id)
    runtime.product_tasks.attach_run(task.id, run.id)
    host = object.__new__(ConversationMessagesStreamHandler)
    host.runtime = runtime
    host.request = SimpleNamespace(headers={})
    host.get_lang = lambda: "zh-CN"
    executor = runner_module.ConversationRunExecutor(host, run_id=run.id, conversation_id=conversation.id)
    await executor.execute(
        conversation_id=conversation.id, conversation=conversation, workspace=workspace,
        payload={"enable_thinking": False, "confirmation_policy": confirmation_policy}, content=content,
        image_data="", attachments=[], model="test", requested_mode=None, effective_mode="terminal", run=run,
    )
    assert len(calls) == len(rounds)
    return calls, runtime.runs.get(run.id), conversation.messages[-1]


@pytest.mark.asyncio
async def test_historical_image_is_lazy_and_explicit_read_delivers_original_pixels(full_runtime, monkeypatch):
    import base64
    import io
    import random
    from PIL import Image

    runtime, workspace = full_runtime
    conversation = runtime.conversations.create(workspace.id)
    image = Image.frombytes("RGB", (1024, 1024), random.Random(0).randbytes(3 * 1024 * 1024))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    assert len(raw) > 2 * 1024 * 1024
    record = runtime.attachments.create(workspace_id=workspace.id, conversation_id=conversation.id,
                                        original_name="reference.png", media_type="image/png", content=raw)
    previous = runtime.conversations.add_message(conversation.id, "user", "这是参考效果图", metadata={"attachments": [record.to_public_dict()], "has_image": True})
    runtime.attachments.bind_message([record.id], previous.id)
    runtime.conversations.add_message(conversation.id, "assistant", "已收到图片。")
    calls, run, _ = await execute(full_runtime, monkeypatch, "按照之前的图片继续", [
        tool_round("runtime.discover_tools", tool_ids=["attachment.read_image"]),
        tool_round("attachment.read_image", attachment_id=record.id),
        [{"message": "已读取之前的参考图。"}, {"finish_reason": "stop"}],
    ], conversation=conversation)

    assert len(calls[0]["tools"]) == 1
    assert record.id in json.dumps(calls[0]["messages"])
    assert "Use attachment.extract_text" not in json.dumps(calls[0]["messages"])
    assert all(not isinstance(m.get("content"), list) for m in calls[0]["messages"])
    assert all(not isinstance(m.get("content"), list) for m in calls[1]["messages"])
    images = [part for m in calls[2]["messages"] if isinstance(m.get("content"), list)
              for part in m["content"] if part.get("type") == "image_url"]
    assert len(images) == 1
    assert base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1]) == raw
    events = [e for e in run.events if e["event"] == "tool"]
    assert [e["status"] for e in events] == ["running", "success"]
    assert "data:image/" not in json.dumps(run.events)
    assert base64.b64encode(raw).decode() not in json.dumps(run.events)
    round_event = [e for e in run.events if e["event"] == "model_round"][-1]
    assert list(round_event["visual_context_delivery"].values()) == ["accepted"]

    followup, _, _ = await execute(full_runtime, monkeypatch, "只说你好", [
        [{"message": "你好。"}, {"finish_reason": "stop"}],
    ], conversation=conversation)
    assert all(not isinstance(m.get("content"), list) for m in followup[0]["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["读取对话图片附件", "历史图片", "read image attachment"])
async def test_explicit_image_discovery_query_finds_image_reader(full_runtime, monkeypatch, query):
    calls, _, _ = await execute(full_runtime, monkeypatch, "查询工具", [
        tool_round("runtime.discover_tools", query=query),
        [{"message": "已查询。"}, {"finish_reason": "stop"}],
    ])
    assert "attachment__read_image" in {tool["function"]["name"] for tool in calls[1]["tools"]}


@pytest.mark.asyncio
async def test_image_reader_cannot_read_another_conversations_attachment(full_runtime, monkeypatch):
    runtime, workspace = full_runtime
    record = runtime.attachments.create(workspace_id=workspace.id, conversation_id="other",
                                        original_name="private.png", media_type="image/png", content=b"png")
    calls, run, _ = await execute(full_runtime, monkeypatch, "读取图片", [
        tool_round("runtime.discover_tools", tool_ids=["attachment.read_image"]),
        tool_round("attachment.read_image", attachment_id=record.id),
        [{"message": "附件不可访问。"}, {"finish_reason": "stop"}],
    ])
    failed = [e for e in run.events if e["event"] == "tool" and e["status"] == "failure"]
    assert len(failed) == 1 and "not available" in failed[0]["error"]
    assert all(not isinstance(m.get("content"), list) for m in calls[-1]["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["你好", "请分析项目并修改代码", "检查 Blender 当前场景"])
async def test_first_request_has_one_discovery_tool_and_bounded_system_context(full_runtime, monkeypatch, content):
    calls, run, message = await execute(full_runtime, monkeypatch, content, [[{"message": "收到。"}, {"finish_reason": "stop"}]])
    request = calls[0]
    assert [t["function"]["name"] for t in request["tools"]] == [DISCOVERY_TOOL_NAME]
    system = "\n".join(m["content"] for m in request["messages"] if m["role"] == "system")
    assert len(system) < 1000
    assert len(json.dumps(request["tools"], ensure_ascii=False)) < 1500
    assert any(m["role"] == "user" and m["content"] == content for m in request["messages"])
    assert "Context Pack" not in system and "filesystem.write_file" not in system
    assert message.content == "收到。"
    assert not any(event["event"] in {"tool", "tool_discovery"} for event in run.events)
    assert any(event["event"] == "capability_snapshot" for event in run.events)


@pytest.mark.asyncio
async def test_discover_then_real_write_and_read_keeps_execution_and_audit(full_runtime, monkeypatch):
    runtime, workspace = full_runtime
    calls, run, message = await execute(full_runtime, monkeypatch, "写入 result.txt 并读回", [
        tool_round("runtime.discover_tools", tool_ids=["filesystem.write_file", "filesystem.read_file"]),
        tool_round("filesystem.write_file", path="result.txt", content="验收成功"),
        tool_round("filesystem.read_file", path="result.txt"),
        [{"message": "已写入并读回 result.txt。"}, {"finish_reason": "stop"}],
    ])
    assert (Path(workspace.path) / "result.txt").read_text(encoding="utf-8") == "验收成功"
    assert len(calls[0]["tools"]) == 1 and len(calls[1]["tools"]) == 3
    assert len(calls[2]["tools"]) == 3
    assert any(event["event"] == "tool_discovery" for event in run.events)
    completed = [e for e in run.events if e["event"] == "tool" and e["status"] == "success"]
    assert [e["tool"] for e in completed] == ["filesystem.write_file", "filesystem.read_file"]
    assert all(e["task_id"] for e in completed)
    assert message.metadata["run_result"]["execution_status"] == "completed"
    assert message.metadata["run_result"]["goal_status"] == "unknown"
    assert runtime.product_tasks.get(run.task_id).state == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected", [
    ("文件创建 文件写入 文件读取", {"filesystem__write_file", "filesystem__read_file"}),
    ("文件创建、文件写入、文件读取", {"filesystem__write_file", "filesystem__read_file"}),
    ("文件读取 读文件", {"filesystem__read_file"}),
])
async def test_chinese_discovery_queries_find_real_definitions_despite_word_order(full_runtime, monkeypatch, query, expected):
    calls, run, _ = await execute(full_runtime, monkeypatch, "查找文件工具", [
        tool_round("runtime.discover_tools", query=query),
        [{"message": "已查询工具定义。"}, {"finish_reason": "stop"}],
    ])
    assert expected <= {tool["function"]["name"] for tool in calls[1]["tools"]}
    assert not any(event["event"] == "tool" for event in run.events)


@pytest.mark.asyncio
async def test_discovered_external_definition_uses_original_registry_handler(full_runtime, monkeypatch):
    runtime, _ = full_runtime
    received = []

    async def inspect_scene(arguments, context):
        received.append(arguments)
        return {"objects": ["Cube"]}

    runtime.registry.register(ToolSpec(
        id="mcp_blender.inspect_scene", name="Inspect scene", description="Inspect Blender scene",
        input_schema={"type": "object", "properties": {"detail": {"type": "string"}}, "required": ["detail"]},
    ), inspect_scene)
    runtime.registry.set_provider_metadata("mcp_blender", source_type="mcp", source_id="blender")
    monkeypatch.setattr(runtime.mcp_services, "is_connected", lambda source_id: source_id == "blender")
    calls, run, _ = await execute(full_runtime, monkeypatch, "查看 Blender", [
        tool_round("runtime.discover_tools", query="mcp_blender"),
        tool_round("mcp_blender.inspect_scene", detail="objects"),
        [{"message": "场景里有 Cube。"}, {"finish_reason": "stop"}],
    ])
    assert received == [{"detail": "objects"}]
    assert calls[1]["tools"][1]["function"]["parameters"]["required"] == ["detail"]
    assert any(e["event"] == "tool" and e["tool"] == "mcp_blender.inspect_scene" and e["status"] == "success" for e in run.events)


@pytest.mark.asyncio
async def test_discovery_cannot_expose_disabled_or_unavailable_tools(full_runtime, monkeypatch):
    runtime, _ = full_runtime
    enabled = runtime.settings.is_tool_enabled
    available = runtime.is_tool_available
    monkeypatch.setattr(runtime.settings, "is_tool_enabled", lambda key: key != "filesystem.write_file" and enabled(key))
    monkeypatch.setattr(runtime, "is_tool_available", lambda spec: spec["id"] != "filesystem.read_file" and available(spec))
    calls, run, _ = await execute(full_runtime, monkeypatch, "检查能力", [
        tool_round("runtime.discover_tools", tool_ids=["filesystem.write_file"]),
        tool_round("runtime.discover_tools", tool_ids=["filesystem.read_file"]),
        [{"message": "这两个工具当前不可用。"}, {"finish_reason": "stop"}],
    ])
    assert all(len(call["tools"]) == 1 for call in calls)
    discovery_events = [e for e in run.events if e["event"] == "tool_discovery"]
    assert [e["status"] for e in discovery_events] == ["rejected", "rejected"]
    assert not any(e["event"] == "tool" for e in run.events)


@pytest.mark.asyncio
async def test_discovered_write_still_respects_workspace_boundary(full_runtime, monkeypatch, tmp_path):
    target = tmp_path / "outside.txt"
    calls, run, _ = await execute(full_runtime, monkeypatch, "尝试越界写入", [
        tool_round("runtime.discover_tools", tool_ids=["filesystem.write_file"]),
        tool_round("filesystem.write_file", path=str(target), content="must not write"),
        [{"message": "路径权限校验阻止了写入。"}, {"finish_reason": "stop"}],
    ])
    assert len(calls[1]["tools"]) == 2
    assert not target.exists()
    assert not any(e["event"] == "tool" and e["status"] == "success" for e in run.events)
    assert any(e["event"] == "tool" and e["status"] == "failure" for e in run.events)


@pytest.mark.asyncio
async def test_loaded_tool_still_requires_confirmation_when_policy_requires_it(full_runtime, monkeypatch):
    confirmations = []

    async def decline(self, tool_id, arguments, decision):
        confirmations.append(tool_id)
        return False

    monkeypatch.setattr(ConversationMessagesStreamHandler, "_confirm_runtime_tool_call", decline)
    _, run, _ = await execute(full_runtime, monkeypatch, "写入文件", [
        tool_round("runtime.discover_tools", tool_ids=["filesystem.write_file"]),
        tool_round("filesystem.write_file", path="declined.txt", content="must not write"),
        [{"message": "操作已取消。"}, {"finish_reason": "stop"}],
    ], confirmation_policy="conservative")
    assert confirmations == ["filesystem.write_file"]
    assert not (Path(full_runtime[1].path) / "declined.txt").exists()
    assert not any(e["event"] == "tool" and e["status"] == "success" for e in run.events)


@pytest.mark.asyncio
async def test_optional_task_declaration_can_be_loaded_and_recorded(full_runtime, monkeypatch):
    calls, run, _ = await execute(full_runtime, monkeypatch, "记录当前目标", [
        tool_round("runtime.discover_tools", tool_ids=["runtime.update_task"]),
        tool_round("runtime.update_task", goal="记录当前目标", intent="answer_only"),
        [{"message": "已记录目标。"}, {"finish_reason": "stop"}],
    ])
    assert len(calls[0]["tools"]) == 1 and len(calls[1]["tools"]) == 2
    assert any(e["event"] == "task_contract" and e["contract"]["source"] == "model_execution" for e in run.events)
    assert not any(e["event"] == "tool" for e in run.events)


@pytest.mark.asyncio
async def test_model_selected_service_command_has_no_verification_route_advice(full_runtime, monkeypatch):
    runtime, _ = full_runtime
    received = []
    spec = runtime.registry.get("shell.run_command").spec

    async def simulated_service(arguments, context):
        received.append(arguments)
        return {"exit_code": 0, "stdout": "observed service output", "stderr": ""}

    runtime.registry.unregister(spec.id)
    runtime.registry.register(spec, simulated_service)
    calls, run, _ = await execute(full_runtime, monkeypatch, "写入页面并启动服务检查", [
        tool_round("runtime.discover_tools", tool_ids=["runtime.update_task", "filesystem.write_file", "shell.run_command"]),
        tool_round("runtime.update_task", intent="write_required", requires_write=True, requires_verification=True),
        tool_round("filesystem.write_file", path="index.html", content="<html lang='en'><meta charset='utf-8'><title>Test</title></html>"),
        tool_round("shell.run_command", command="python -m http.server 8080", timeout=5),
        [{"message": "已保存页面；服务行为仍需检查。"}, {"finish_reason": "stop"}],
    ])
    assert received == [{"command": "python -m http.server 8080", "timeout": 5}]
    tool_payload = next(json.loads(m["content"]) for m in reversed(calls[-1]["messages"]) if m["role"] == "tool")
    assert tool_payload["output"]["stdout"] == "observed service output"
    assert "runtime_advisories" not in tool_payload
    assert "runtime_risks" not in tool_payload
    assert not any("verification_runtime_advisory" in json.dumps(e) for e in run.events)


@pytest.mark.asyncio
async def test_failed_mcp_returns_facts_and_model_can_inspect_the_same_service(full_runtime, monkeypatch):
    runtime, _ = full_runtime
    observed = []

    async def mutate(arguments, context):
        observed.append("partial change")
        raise RuntimeError("failed after first mutation")

    async def inspect(arguments, context):
        return {"state": observed}

    for name, handler in [("mutate", mutate), ("inspect", inspect)]:
        runtime.registry.register(ToolSpec(
            id=f"mcp_demo.{name}", name=name, description=name,
            input_schema={"type": "object", "properties": {}},
        ), handler)
    runtime.registry.set_provider_metadata("mcp_demo", source_type="mcp", source_id="demo")
    monkeypatch.setattr(runtime.mcp_services, "is_connected", lambda source_id: source_id == "demo")
    calls, run, _ = await execute(full_runtime, monkeypatch, "执行后检查真实状态", [
        tool_round("runtime.discover_tools", query="mcp_demo"),
        tool_round("mcp_demo.mutate"),
        tool_round("mcp_demo.inspect"),
        [{"message": "发现部分变更，未观察到回滚。"}, {"finish_reason": "stop"}],
    ])
    failure = next(json.loads(m["content"]) for m in reversed(calls[2]["messages"]) if m["role"] == "tool")
    assert failure["status"] == "failure"
    risk = failure["runtime_risks"][0]
    assert risk["side_effects"] == "unknown" and risk["rollback_observed"] is False
    assert not {"action", "suggested_tools", "suggested_calls"} & risk.keys()
    assert "failed after first mutation" in risk["detail"]
    assert "runtime_advisories" not in failure
    assert any(e["event"] == "tool" and e["tool"] == "mcp_demo.inspect" and e["status"] == "success" for e in run.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["write file read file local file system", "read file text content local file"])
async def test_real_catalog_search_does_not_bury_file_tools_under_alphabetic_matches(full_runtime, monkeypatch, query):
    calls, _, _ = await execute(full_runtime, monkeypatch, "查询文件能力", [
        tool_round("runtime.discover_tools", query=query),
        [{"message": "已获取工具定义。"}, {"finish_reason": "stop"}],
    ])
    loaded = [tool["function"]["name"] for tool in calls[1]["tools"][1:]]
    assert "filesystem__read_file" in loaded[:2]
    if "write" in query:
        assert "filesystem__write_file" in loaded[:2]


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_without_discovery_hints_and_model_chooses_next_call(full_runtime, monkeypatch):
    (Path(full_runtime[1].path) / "input.txt").write_text("observed", encoding="utf-8")
    calls, _, message = await execute(full_runtime, monkeypatch, "读取 input.txt", [
        tool_round("invented.read_file", path="input.txt"),
        tool_round("runtime.discover_tools", tool_ids=["filesystem.read_file"]),
        tool_round("filesystem.read_file", path="input.txt"),
        [{"message": "读取内容：observed\n"}, {"finish_reason": "stop"}],
    ])
    failure = next(json.loads(m["content"]) for m in calls[1]["messages"] if m["role"] == "tool")
    observation = failure["output"]["observation"]
    assert observation["reason"] == "unknown_tool"
    assert observation["status"] == "not_executed"
    assert "model_decision" not in observation and "available_tool_ids" not in observation
    assert len(calls[1]["tools"]) == 1
    assert len(calls[2]["tools"]) == 2
    assert message.content == "读取内容：observed\n"


@pytest.mark.asyncio
async def test_protocol_errors_return_only_facts_and_do_not_stop_model_after_one_retry(full_runtime, monkeypatch):
    calls, _, message = await execute(full_runtime, monkeypatch, "检查调用协议", [
        [{"finish_reason": "tool_calls"}], [{"finish_reason": "tool_calls"}],
        [{"message": "调用未执行。"}, {"finish_reason": "stop"}],
    ])
    base = calls[0]["messages"][0]
    for request in calls[1:]:
        systems = [m for m in request["messages"] if m["role"] == "system" and m != base]
        assert len(systems) == 1
        assert json.loads(systems[0]["content"]) == {
            "kind": "model_protocol_error", "code": "missing_tool_call_payload", "executed_tool_calls": 0,
        }
    assert message.content == "调用未执行。"
    assert "model_provider_error" not in message.metadata["run_result"]["risks"]


@pytest.mark.asyncio
@pytest.mark.parametrize("requires_write", [False, True])
@pytest.mark.parametrize("last_call", ["read", "write", "failure", "discovery"])
async def test_round_resource_limit_is_independent_of_task_and_tool_result(full_runtime, monkeypatch, requires_write, last_call):
    original_config = runner_module.get_terminal_config
    monkeypatch.setattr(runner_module, "get_terminal_config", lambda lang="": {**original_config(lang), "max_rounds": 4})
    (Path(full_runtime[1].path) / "input.txt").write_text("observed", encoding="utf-8")
    last = {
        "read": tool_round("filesystem.read_file", path="input.txt"),
        "write": tool_round("filesystem.write_file", path="output.txt", content="observed"),
        "failure": tool_round("filesystem.read_file", path="missing.txt"),
        "discovery": tool_round("runtime.discover_tools", query="filesystem"),
    }[last_call]
    calls, run, message = await execute(full_runtime, monkeypatch, "检查资源上限", [
        tool_round("runtime.discover_tools", tool_ids=["runtime.update_task", "filesystem.read_file", "filesystem.write_file"]),
        tool_round("runtime.update_task", intent="write_required" if requires_write else "answer_only", requires_write=requires_write),
        tool_round("filesystem.read_file", path="input.txt"),
        last,
    ])
    assert len(calls) == 4
    assert message.metadata["task_contract"]["requires_write"] is requires_write
    assert message.metadata["max_rounds"] == 4
    assert "max_rounds_exceeded" in message.metadata["run_result"]["risks"]
    assert not any(e.get("status") == "round_budget_extended" for e in run.events)
    assert "4 轮" in message.content


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider", "http", "timeout"])
@pytest.mark.parametrize("after_write", [False, True])
async def test_transport_failure_finalizes_with_original_error_and_existing_evidence(full_runtime, monkeypatch, failure, after_write):
    error = "PROVIDER_UNAVAILABLE" if failure != "timeout" else "IDLE_TIMEOUT_PROBE"
    rounds = []
    if after_write:
        rounds = [
            tool_round("runtime.discover_tools", tool_ids=["filesystem.write_file"]),
            tool_round("filesystem.write_file", path="before_error.txt", content="retained"),
        ]
    if failure == "http":
        rounds.append([tornado.web.HTTPError(503, reason=error)])
    elif failure == "timeout":
        rounds.extend([[{"error": error, "idle_timeout": True}]] * 2)
    else:
        rounds.append([{"error": error}])
    calls, run, message = await execute(full_runtime, monkeypatch, "检查真实传输错误", rounds)
    result = message.metadata["run_result"]
    assert error in message.content
    assert "model_provider_error" in result["risks"]
    assert any(f["tool"] == "model.provider" and f["error"] == error for f in result["failures"])
    assert any(e["event"] == "result" for e in run.events)
    assert run.stage == "done" and run.status in {"failure", "partial"}
    assert full_runtime[0].product_tasks.get(run.task_id).state in {"failed", "paused"}
    assert len(calls) == len(rounds)
    if after_write:
        assert (Path(full_runtime[1].path) / "before_error.txt").read_text(encoding="utf-8") == "retained"
        assert result["counts"]["file_write_successes"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [HTTPTimeoutError("Timeout during request"), RuntimeError("transport worker failed")])
@pytest.mark.parametrize("with_text", [False, True])
async def test_real_provider_worker_exception_reaches_run_result_and_checkpoint(full_runtime, monkeypatch, error, with_text):
    runtime, _ = full_runtime
    monkeypatch.setattr(runtime.settings, "resolve_model", lambda model: (
        {"api_model": model, "context_limit": 128000},
        {"base_url": "https://provider.invalid", "api_key_required": False},
        "probe",
    ))

    async def context_limit(**kwargs):
        return 128000

    body = "主模型已输出的原文。\n"

    async def fetch(request, **kwargs):
        delta = {"reasoning_content": "observed reasoning before transport failure"}
        if with_text:
            delta["content"] = body
        request.streaming_callback(("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode())
        raise error

    monkeypatch.setattr(provider_client, "resolve_provider_context_limit", context_limit)
    monkeypatch.setattr(provider_client.tornado.httpclient, "AsyncHTTPClient", lambda: SimpleNamespace(fetch=fetch))
    calls, run, message = await execute(full_runtime, monkeypatch, "检查后台请求异常", [[]], transport=provider_client.stream_chat_completion)
    result = message.metadata["run_result"]
    assert any(f.get("tool") == "model.provider" and f.get("error") == str(error) for f in result["failures"])
    assert message.metadata["reasoning"] == "observed reasoning before transport failure"
    assert message.content == body if with_text else str(error) in message.content
    assert run.stage == "done" and run.status == "failure"
    assert runtime.product_tasks.get(run.task_id).state == "failed"
    assert runtime.product_tasks.get_checkpoint(message.metadata["checkpoint_id"])
    assert len(calls) == 1
    assert any(e.get("event") == "model_round" and e.get("model_error") == str(error) for e in run.events)


@pytest.mark.asyncio
async def test_streamed_answer_survives_transport_error_without_answer_repair(full_runtime, monkeypatch):
    body = "主模型已输出的部分内容。\n"
    _, run, message = await execute(full_runtime, monkeypatch, "检查部分响应", [
        [{"message": body}, {"error": "STREAM_INTERRUPTED"}],
    ])
    assert message.content == body
    assert "model_provider_error" in message.metadata["run_result"]["risks"]
    assert run.stage == "done" and run.status == "failure"


@pytest.mark.asyncio
async def test_single_idle_timeout_does_not_mark_eventual_answer_failed(full_runtime, monkeypatch):
    _, run, message = await execute(full_runtime, monkeypatch, "检查传输重试", [
        [{"error": "TRANSIENT_IDLE", "idle_timeout": True}],
        [{"message": "已收到正常响应。"}, {"finish_reason": "stop"}],
    ])
    assert message.content == "已收到正常响应。"
    assert "model_provider_error" not in message.metadata["run_result"]["risks"]
    assert any(e.get("status") == "idle_timeout" and e.get("error") == "TRANSIENT_IDLE" for e in run.events)
    assert run.stage == "done" and run.status == "success"
    assert full_runtime[0].product_tasks.get(run.task_id).state == "completed"


@pytest.mark.asyncio
async def test_pause_during_last_model_response_waits_for_user_resume_before_publication(full_runtime, monkeypatch):
    from runtime.api.runs import RunActionHandler
    from runtime.conversation_interactions import paused_runs

    runtime, _ = full_runtime
    waiting = asyncio.Event()
    original_wait = runner_module.ConversationRunExecutor._wait_if_paused

    async def observe_wait(self):
        if runtime.runs.get(self._active_run_id).status == "paused":
            waiting.set()
        await original_wait(self)

    monkeypatch.setattr(runner_module.ConversationRunExecutor, "_wait_if_paused", observe_wait)
    actions = object.__new__(RunActionHandler)
    actions.runtime = runtime
    actions.finish_json = lambda _value: None

    async def pause(_round):
        actions._pause(runtime.runs.list()[0].id, "user pause")

    execution = asyncio.create_task(execute(full_runtime, monkeypatch, "检查项目", [
        [{"message": "主模型的最终回答。"}, {"finish_reason": "stop"}],
    ], on_round_finished=pause))
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        run = runtime.runs.get(runtime.runs.list()[0].id)
        assert not execution.done()
        assert run.status == "paused"
        assert runtime.product_tasks.get(run.task_id).state == "paused"
        assert not any(e["event"] == "result" for e in run.events)
        actions._resume(run.id, "user resume")
        _, done, answer = await asyncio.wait_for(execution, 5)
        assert done.status == "success"
        assert runtime.product_tasks.get(done.task_id).state == "completed"
        assert answer.content == "主模型的最终回答。"
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        for summary in runtime.runs.list():
            paused_runs.pop(summary.id, None)
