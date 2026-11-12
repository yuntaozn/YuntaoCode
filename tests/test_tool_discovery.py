import json

import pytest

from runtime.tool_discovery import DISCOVERY_TOOL_ID, DISCOVERY_TOOL_NAME, ToolDiscovery


def catalog():
    ids = ["filesystem.read_file", "filesystem.write_file", "mcp_blender.execute_code", "runtime.update_task"]
    tools = [{"type": "function", "function": {
        "name": key.replace(".", "__"), "description": key,
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}},
    }} for key in ids]
    names = {name: key for key in ids for name in (key, key.replace(".", "__"))}
    return tools, names


async def discover(control, arguments, finish_reason="tool_calls"):
    call = {"id": "discover-1", "function": {"name": DISCOVERY_TOOL_NAME, "arguments": json.dumps(arguments)}}
    message = await control.handle_call(call, DISCOVERY_TOOL_ID, arguments, finish_reason)
    assert message["role"] == "tool" and message["tool_call_id"] == "discover-1"
    return json.loads(message["content"])


@pytest.mark.asyncio
async def test_namespace_listing_and_paged_search_only_load_model_requested_definitions():
    tools, names = catalog()
    events = []
    control = ToolDiscovery(lambda: (tools, names), emit=events.append)
    assert len(control.model_tools()) == 1
    index = await discover(control, {})
    assert index["namespaces"] == {"filesystem": 2, "mcp_blender": 1, "runtime": 1}
    assert len(control.model_tools()) == 1
    first = await discover(control, {"query": "filesystem", "limit": 1})
    assert first["total"] == 2 and first["next_offset"] == 1
    assert control.model_tools()[1:] == tools[:1]
    await discover(control, {"query": "filesystem", "limit": 1, "offset": 1})
    assert control.model_tools()[1:] == tools[:2]
    await discover(control, {"query": "nonexistent"})
    assert control.model_tools()[1:] == tools[:2]
    assert all(event["event"] == "tool_discovery" for event in events)


@pytest.mark.asyncio
async def test_mcp_and_task_control_load_original_schema_without_executing_or_duplicating():
    tools, names = catalog()
    control = ToolDiscovery(lambda: (tools, names), emit=lambda _: None)
    await discover(control, {"tool_ids": ["mcp_blender__execute_code", "runtime.update_task"]})
    assert control.model_tools()[1:] == tools[2:]
    await discover(control, {"tool_ids": ["runtime.update_task", "runtime.update_task"]})
    assert len(control.model_tools()) == 3
    # 新 Run 没有隐式继承已加载清单。
    assert len(ToolDiscovery(lambda: (tools, names), emit=lambda _: None).model_tools()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"limit": 0}, {"limit": 11}, {"offset": -1}, {"offset": True},
    {"tool_ids": "filesystem.read_file"}, {"tool_ids": [""]},
    {"tool_ids": ["filesystem.read_file", "missing"]}, {"query": 1},
    {"query": "read", "tool_ids": ["filesystem.read_file"]}, {"unexpected": True},
])
async def test_invalid_discovery_is_atomic(arguments):
    control = ToolDiscovery(catalog, emit=lambda _: None)
    assert (await discover(control, arguments))["status"] == "rejected"
    assert len(control.model_tools()) == 1


@pytest.mark.asyncio
async def test_truncated_discovery_does_not_load_definitions():
    control = ToolDiscovery(catalog, emit=lambda _: None)
    assert (await discover(control, {"query": "filesystem"}, "length"))["status"] == "rejected"
    assert len(control.model_tools()) == 1


@pytest.mark.asyncio
async def test_explicit_discovery_refreshes_catalog_without_an_extra_model_or_initial_scan():
    tools, names = catalog()
    current = []
    reads = []

    def load():
        reads.append(True)
        return current[:], names

    control = ToolDiscovery(load, emit=lambda _: None)
    assert len(control.model_tools()) == 1 and reads == []
    assert (await discover(control, {"query": "mcp_blender"}))["tools"] == []
    current.append(tools[2])
    assert len((await discover(control, {"query": "mcp_blender"}))["tools"]) == 1
    assert control.model_tools()[1:] == [tools[2]]
    current.clear()
    await discover(control, {})
    assert len(control.model_tools()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["{", "[]", "null"])
async def test_malformed_arguments_are_reported_as_rejected(raw):
    control = ToolDiscovery(catalog, emit=lambda _: None)
    call = {"id": "invalid", "function": {"name": DISCOVERY_TOOL_NAME, "arguments": raw}}
    message = await control.handle_call(call, DISCOVERY_TOOL_ID, {}, "tool_calls")
    assert json.loads(message["content"])["status"] == "rejected"
    assert len(control.model_tools()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected", [
    ("write file read file local file system", ["filesystem.read_file", "filesystem.write_file"]),
    ("read file text content local file", ["filesystem.read_file", "filesystem.write_file"]),
    ("filesystem.write_file", ["filesystem.write_file", "filesystem.read_file"]),
])
async def test_free_text_queries_rank_tool_names_before_generic_description_matches(query, expected):
    tools, names = catalog()
    tools.insert(0, {"type": "function", "function": {
        "name": "code__apply_patch", "description": "read write local file text content system",
        "parameters": {"type": "object", "properties": {}},
    }})
    names["code__apply_patch"] = "code.apply_patch"
    control = ToolDiscovery(lambda: (tools, names), emit=lambda _: None)
    result = await discover(control, {"query": query, "limit": 2})
    assert [tool["id"] for tool in result["tools"]] == expected[:result["total"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["温度读取", "读取温度", "设备 温度读取"])
async def test_cjk_search_uses_lexical_overlap_without_capability_keyword_mapping(query):
    tools, names = catalog()
    tool = {"type": "function", "function": {
        "name": "sensor__inspect", "description": "读取设备温度",
        "parameters": {"type": "object", "properties": {}},
    }}
    tools.append(tool)
    names["sensor__inspect"] = "sensor.inspect"
    control = ToolDiscovery(lambda: (tools, names), emit=lambda _: None)
    result = await discover(control, {"query": query})
    assert [item["id"] for item in result["tools"]] == ["sensor.inspect"]
    assert control.model_tools()[1:] == [tool]
    assert (await discover(control, {"query": "星际冰川"}))["tools"] == []


@pytest.mark.asyncio
async def test_new_reader_does_not_displace_more_complete_name_or_description_matches():
    ids = ["filesystem.read_file", "filesystem.write_file", "filesystem.write_temp_file", "attachment.read_image"]
    descriptions = ["读取文件", "创建和写入文件", "创建临时文件", "读取历史图片"]
    tools = [{"type": "function", "function": {
        "name": key.replace(".", "__"), "description": description,
        "parameters": {"type": "object", "properties": {}},
    }} for key, description in zip(ids, descriptions)]
    names = {key.replace(".", "__"): key for key in ids}
    control = ToolDiscovery(lambda: (tools, names), emit=lambda _: None)
    english = await discover(control, {"query": "write file read file local file system", "limit": 2})
    assert {tool["id"] for tool in english["tools"]} == set(ids[:2])
    chinese = await discover(control, {"query": "文件创建 文件写入 文件读取", "limit": 2})
    assert {tool["id"] for tool in chinese["tools"]} == set(ids[:2])
