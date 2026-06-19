from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import tornado.web

from runtime.api.mcp_services import _with_linked_capabilities, require_local_mcp_control_request
from runtime.mcp_service_manager import MCP_SERVICE_SCHEMA_VERSION, McpServiceManager, normalize_mcp_service
from runtime.tool_registry import ToolRegistry


FAKE_MCP_SERVER = Path(__file__).parent / "fakes" / "fake_mcp_server.py"


def _stdio_service(**overrides):
    value = {
        "id": "demo-mcp",
        "name": "Demo MCP",
        "enabled": True,
        "transport": {
            "type": "stdio",
            "command": sys.executable,
            "args": [str(FAKE_MCP_SERVER)],
            "env": {"DEMO_TOKEN": "secret"},
        },
        "timeouts": {"call": 12},
        "tool_policies": {
            "echo": {"risk": "read_only", "roles": ["evidence"], "call_timeout": 3},
            "change_state": {
                "risk": "state_change",
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
            },
        },
    }
    value.update(overrides)
    return value


def test_mcp_service_configuration_is_persisted_and_secrets_are_redacted(tmp_path: Path) -> None:
    path = tmp_path / "mcp-services.json"
    manager = McpServiceManager(path)

    public = manager.upsert(_stdio_service())

    assert public["transport"]["env_keys"] == ["DEMO_TOKEN"]
    assert "env" not in public["transport"]
    assert "secret" not in str(public)
    assert "secret" not in path.read_text(encoding="utf-8")
    assert "secret" in manager.secrets_path.read_text(encoding="utf-8")

    reloaded = McpServiceManager(path).get_public("demo-mcp")

    assert reloaded["name"] == "Demo MCP"
    assert reloaded["timeouts"]["call"] == 12
    assert reloaded["tool_policies"]["echo"]["call_timeout"] == 3
    assert reloaded["transport"]["env_keys"] == ["DEMO_TOKEN"]


def test_mcp_service_update_preserves_hidden_environment_when_omitted(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service())

    manager.upsert(
        {
            "name": "Renamed MCP",
            "enabled": True,
            "transport": {
                "type": "stdio",
                "command": sys.executable,
                "args": [str(FAKE_MCP_SERVER)],
            },
        },
        service_id="demo-mcp",
    )

    assert manager.get_public("demo-mcp")["transport"]["env_keys"] == ["DEMO_TOKEN"]


def test_mcp_service_persists_auto_start_lifecycle(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")

    public = manager.upsert(_stdio_service(lifecycle={"auto_start": True}))
    reloaded = McpServiceManager(tmp_path / "mcp-services.json").get_public("demo-mcp")

    assert public["lifecycle"]["auto_start"] is True
    assert reloaded["lifecycle"]["auto_start"] is True


def test_mcp_tool_call_timeout_prefers_tool_policy_over_service_default(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service())

    assert manager._tool_call_timeout("demo-mcp", "echo") == 3
    assert manager._tool_call_timeout("demo-mcp", "change_state") == 12


def test_mcp_public_status_reports_protocol_disconnected_process(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service())
    runtime = manager._runtime_for("demo-mcp")
    runtime.state = "running"
    runtime.message = "process running; MCP protocol is not connected"
    runtime.process = SimpleNamespace(returncode=None, pid=1234)

    public = manager.get_public("demo-mcp")

    assert public["status"]["state"] == "protocol_disconnected"
    assert public["status"]["raw_state"] == "running"
    assert public["status"]["process_running"] is True
    assert public["status"]["protocol_connected"] is False
    assert public["status"]["requires_attention"] is True
    assert public["status"]["recommended_action"] == "restart"

    [issue] = [
        item for item in manager.capability_issues()
        if item["source_id"] == "demo-mcp"
    ]
    assert issue["capability_id"] == "mcp.demo-mcp"
    assert issue["code"] == "protocol_disconnected"
    assert issue["recommended_action"] == "restart"


@pytest.mark.asyncio
async def test_mcp_call_tool_passes_configured_timeout_to_session(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service())
    runtime = manager._runtime_for("demo-mcp")
    captured: dict[str, object] = {}

    async def fake_call_tool(
        name: str,
        arguments: dict[str, object],
        *,
        timeout: float = 30.0,
    ) -> dict[str, object]:
        captured.update({"name": name, "arguments": arguments, "timeout": timeout})
        return {"content": [{"type": "text", "text": "ok"}]}

    runtime.protocol_connected = True
    runtime.session = SimpleNamespace(call_tool=fake_call_tool)

    output = await manager.call_tool("demo-mcp", "echo", {"text": "hello"})

    assert output["content"] == "ok"
    assert output["call_timeout"] == 3
    assert captured == {"name": "echo", "arguments": {"text": "hello"}, "timeout": 3}


def test_mcp_service_validation_rejects_unsupported_transport() -> None:
    with pytest.raises(ValueError, match="unsupported MCP transport"):
        normalize_mcp_service({
            "id": "demo",
            "transport": {"type": "raw_socket"},
        })


def test_mcp_service_validation_rejects_unknown_permission_level() -> None:
    with pytest.raises(ValueError, match="unsupported arbitrary_code permission"):
        normalize_mcp_service({
            **_stdio_service(),
            "permissions": {"arbitrary_code": "always_without_review"},
        })


def test_mcp_executable_resolution_finds_current_python() -> None:
    resolved = McpServiceManager._resolve_executable(sys.executable)

    assert Path(resolved).resolve() == Path(sys.executable).resolve()


@pytest.mark.asyncio
async def test_mcp_stdio_lifecycle_connects_discovers_and_unbinds_tools(tmp_path: Path) -> None:
    registry = ToolRegistry()
    manager = McpServiceManager(tmp_path / "mcp-services.json", registry=registry)
    manager.upsert(_stdio_service())

    await manager.start("demo-mcp")

    connected = manager.get_public("demo-mcp")
    assert connected["status"]["state"] == "connected"
    assert connected["status"]["protocol_connected"] is True
    assert connected["status"]["protocol_version"] == "2025-06-18"
    assert connected["status"]["tool_ids"] == ["mcp_demo_mcp.echo", "mcp_demo_mcp.change_state"]
    assert connected["capability_bindings"][0]["remote_name"] == "echo"

    echo = registry.get("mcp_demo_mcp.echo")
    change_state = registry.get("mcp_demo_mcp.change_state")
    assert echo.spec.requires_confirmation is False
    assert change_state.spec.requires_confirmation is True
    assert echo.spec.effects == []
    assert echo.spec.roles == ["evidence"]
    assert change_state.spec.effects == ["external_state_change"]
    assert change_state.spec.roles == ["deliverable"]
    assert change_state.spec.capability == "mcp.demo-mcp"
    assert registry.get_public_spec("mcp_demo_mcp.echo")["source_type"] == "mcp"

    output = await echo.handler({"text": "hello"}, None)
    assert output["content"] == "hello"
    assert output["roles"] == ["evidence"]

    changed = await change_state.handler({}, None)
    assert changed["effects"] == ["external_state_change"]
    assert changed["roles"] == ["deliverable"]

    runtime = manager._runtime_for("demo-mcp")
    manager._update_binding_health(runtime, "echo", error="demo failure")
    degraded = manager.get_public("demo-mcp")["capability_bindings"][0]
    assert degraded["health"] == "degraded"
    assert degraded["last_error"] == "demo failure"
    degraded_public = manager.get_public("demo-mcp")
    assert degraded_public["status"]["state"] == "connected"
    assert degraded_public["status"]["issue_code"] == "tool_degraded"
    assert degraded_public["status"]["tool_health"]["state"] == "degraded"
    assert degraded_public["status"]["tool_roundtrip_healthy"] is False
    assert manager.tool_runtime_metadata(
        "mcp_demo_mcp.echo",
        source_id="demo-mcp",
    )["tool_health"] == "degraded"

    await manager.stop("demo-mcp")
    assert manager.get_public("demo-mcp")["status"]["state"] == "stopped"
    with pytest.raises(KeyError):
        registry.get("mcp_demo_mcp.echo")


@pytest.mark.asyncio
async def test_mcp_tool_diagnostics_persist_across_reconnect_and_clear_on_success(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mcp-services.json"
    registry = ToolRegistry()
    manager = McpServiceManager(path, registry=registry)
    manager.upsert(_stdio_service())

    await manager.start("demo-mcp")
    runtime = manager._runtime_for("demo-mcp")
    manager._update_binding_health(
        runtime,
        "echo",
        error="Unknown command type: echo",
        service_id="demo-mcp",
    )
    await manager.stop("demo-mcp")

    reloaded_registry = ToolRegistry()
    reloaded = McpServiceManager(path, registry=reloaded_registry)
    await reloaded.start("demo-mcp")

    public = reloaded.get_public("demo-mcp")
    [echo_binding] = [
        item for item in public["capability_bindings"]
        if item["remote_name"] == "echo"
    ]
    assert echo_binding["health"] == "degraded"
    assert echo_binding["last_error"] == "Unknown command type: echo"
    assert reloaded.tool_runtime_metadata(
        "mcp_demo_mcp.echo",
        source_id="demo-mcp",
    )["tool_health"] == "degraded"

    echo = reloaded_registry.get("mcp_demo_mcp.echo")
    output = await echo.handler({"text": "hello"}, None)

    assert output["content"] == "hello"
    assert reloaded.tool_runtime_metadata(
        "mcp_demo_mcp.echo",
        source_id="demo-mcp",
    )["tool_health"] == "available"
    assert "Unknown command type" not in path.read_text(encoding="utf-8")

    await reloaded.stop("demo-mcp")


@pytest.mark.asyncio
async def test_mcp_probe_targets_safe_no_argument_observation_tools(
    tmp_path: Path,
) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service())
    runtime = manager._runtime_for("demo-mcp")
    runtime.protocol_connected = True
    runtime.state = "connected"
    runtime.capability_bindings = [
        {
            "tool_id": "mcp_demo_mcp.inspect",
            "remote_name": "inspect",
            "risk": "read_only",
            "roles": ["verification"],
            "required_input_fields": [],
            "health": "available",
        },
        {
            "tool_id": "mcp_demo_mcp.visual_probe",
            "remote_name": "visual_probe",
            "risk": "read_only",
            "roles": ["verification"],
            "artifacts": ["screenshot"],
            "required_input_fields": [],
            "health": "available",
        },
        {
            "tool_id": "mcp_demo_mcp.echo",
            "remote_name": "echo",
            "risk": "read_only",
            "roles": ["evidence"],
            "required_input_fields": ["text"],
            "health": "available",
        },
        {
            "tool_id": "mcp_demo_mcp.change_state",
            "remote_name": "change_state",
            "risk": "state_change",
            "roles": ["deliverable"],
            "required_input_fields": [],
            "health": "available",
        },
    ]

    class ProbeSession:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.fail_visual = True

        async def call_tool(
            self,
            name: str,
            arguments: dict[str, object],
            *,
            timeout: float = 30.0,
        ) -> dict[str, object]:
            self.calls.append(name)
            if name == "visual_probe" and self.fail_visual:
                raise RuntimeError("Unknown command type: visual_probe")
            return {"content": [{"type": "text", "text": f"{name} ok"}]}

    session = ProbeSession()
    runtime.session = session

    results = await manager.probe("demo-mcp")

    assert session.calls == ["inspect", "visual_probe"]
    assert [item["status"] for item in results] == ["success", "failure"]
    visual = manager.tool_runtime_metadata(
        "mcp_demo_mcp.visual_probe",
        source_id="demo-mcp",
    )
    assert visual["tool_health"] == "degraded"
    assert "Unknown command type" in (tmp_path / "mcp-services.json").read_text(encoding="utf-8")
    assert runtime.probe_results == results
    assert runtime.last_probe_at

    session.calls.clear()
    session.fail_visual = False
    results = await manager.probe("demo-mcp")

    assert session.calls == ["inspect", "visual_probe"]
    assert [item["status"] for item in results] == ["success", "success"]
    visual = manager.tool_runtime_metadata(
        "mcp_demo_mcp.visual_probe",
        source_id="demo-mcp",
    )
    assert visual["tool_health"] == "available"
    assert "Unknown command type" not in (tmp_path / "mcp-services.json").read_text(encoding="utf-8")


def test_mcp_capability_issues_report_degraded_bindings(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service())
    runtime = manager._runtime_for("demo-mcp")
    runtime.protocol_connected = True
    runtime.state = "connected"
    runtime.capability_bindings = [{
        "tool_id": "mcp_demo_mcp.change_state",
        "remote_name": "change_state",
        "health": "degraded",
        "last_error": "MCP request timed out after 12s: tools/call",
        "effects": ["external_state_change"],
        "roles": ["deliverable"],
    }]

    [issue] = [
        item for item in manager.capability_issues()
        if item["source_id"] == "demo-mcp"
    ]

    assert issue["code"] == "tool_degraded"
    assert issue["capability_id"] == "mcp.demo-mcp"
    assert issue["tool_id"] == "mcp_demo_mcp.change_state"
    assert issue["recommended_action"] == "restart"


@pytest.mark.asyncio
async def test_disabled_mcp_service_cannot_start(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service(enabled=False))

    with pytest.raises(RuntimeError, match="enable"):
        await manager.start("demo-mcp")


@pytest.mark.asyncio
async def test_mcp_auto_start_connects_enabled_opt_in_service(tmp_path: Path) -> None:
    registry = ToolRegistry()
    manager = McpServiceManager(tmp_path / "mcp-services.json", registry=registry)
    manager.upsert(_stdio_service(lifecycle={"auto_start": True}))

    started = await manager.start_auto_services()

    assert [service["id"] for service in started] == ["demo-mcp"]
    public = manager.get_public("demo-mcp")
    assert public["status"]["state"] == "connected"
    assert registry.get_public_spec("mcp_demo_mcp.echo")["source_type"] == "mcp"

    await manager.stop("demo-mcp")


@pytest.mark.asyncio
async def test_mcp_on_demand_auto_start_connects_target_capability(tmp_path: Path) -> None:
    registry = ToolRegistry()
    manager = McpServiceManager(tmp_path / "mcp-services.json", registry=registry)
    manager.upsert(_stdio_service(lifecycle={"auto_start": True}))

    started = await manager.start_capability_services(["mcp.demo-mcp"])

    assert started == [{
        "service_id": "demo-mcp",
        "capability_id": "mcp.demo-mcp",
        "status": "started",
        "message": "MCP service started for targeted task capability.",
    }]
    public = manager.get_public("demo-mcp")
    assert public["status"]["state"] == "connected"
    assert registry.get_public_spec("mcp_demo_mcp.echo")["source_type"] == "mcp"

    await manager.stop("demo-mcp")


@pytest.mark.asyncio
async def test_mcp_on_demand_auto_start_requires_lifecycle_opt_in(tmp_path: Path) -> None:
    registry = ToolRegistry()
    manager = McpServiceManager(tmp_path / "mcp-services.json", registry=registry)
    manager.upsert(_stdio_service(lifecycle={"auto_start": False}))

    started = await manager.start_capability_services(["mcp.demo-mcp"])

    assert started == []
    assert manager.get_public("demo-mcp")["status"]["state"] == "stopped"
    with pytest.raises(KeyError):
        registry.get_public_spec("mcp_demo_mcp.echo")


def test_mcp_service_links_only_tools_from_matching_service() -> None:
    service = {"id": "demo-mcp"}
    specs = [
        {"id": "demo.echo", "source_type": "mcp", "source_id": "demo-mcp"},
        {"id": "other.echo", "source_type": "mcp", "source_id": "other-mcp"},
        {"id": "filesystem.read_file", "source_type": "builtin", "source_id": "filesystem"},
    ]

    public = _with_linked_capabilities(service, specs)

    assert public["linked_capability_count"] == 1
    assert public["linked_capabilities"][0]["id"] == "demo.echo"


def test_mcp_manager_seeds_disabled_blender_example_once(tmp_path: Path) -> None:
    path = tmp_path / "mcp-services.json"

    manager = McpServiceManager(path)
    blender = manager.get_public("blender")

    assert blender["enabled"] is False
    assert blender["installation"] == {
        "kind": "package_runner",
        "package": "blender-mcp",
        "managed": False,
    }
    assert blender["transport"]["command"] == "uvx"
    assert blender["transport"]["args"] == ["blender-mcp"]
    assert blender["transport"]["env_keys"] == ["BLENDER_MCP_DISABLE_TELEMETRY"]
    assert [item["id"] for item in blender["prerequisites"]] == ["blender-addon", "uvx"]
    assert blender["timeouts"]["call"] == 30
    assert blender["tool_policies"]["get_scene_info"]["risk"] == "read_only"
    assert blender["tool_policies"]["get_scene_info"]["roles"] == ["evidence", "verification"]
    assert blender["tool_policies"]["get_scene_info"]["verification_strength"] == "weak"
    assert blender["tool_policies"]["get_scene_info"]["call_timeout"] == 25
    assert blender["tool_policies"]["get_viewport_screenshot"]["verification_strength"] == "standard"
    assert blender["tool_policies"]["get_viewport_screenshot"]["artifacts"] == ["screenshot"]
    assert blender["tool_policies"]["get_viewport_screenshot"]["call_timeout"] == 60
    assert blender["tool_policies"]["execute_blender_code"]["effects"] == [
        "external_state_change"
    ]
    assert blender["tool_policies"]["execute_blender_code"]["call_timeout"] == 120
    assert blender["tool_policies"]["get_hunyuan3d_status"]["risk"] == "read_only"
    assert blender["tool_policies"]["poll_hunyuan_job_status"]["risk"] == "read_only"
    assert blender["tool_policies"]["get_sketchfab_status"]["risk"] == "read_only"
    assert blender["tool_policies"]["search_sketchfab_models"]["risk"] == "read_only"
    assert blender["tool_policies"]["get_sketchfab_model_preview"]["risk"] == "read_only"
    assert blender["tool_policies"]["download_sketchfab_model"]["effects"] == [
        "external_state_change"
    ]
    assert blender["tool_policies"]["generate_hunyuan3d_model"]["effects"] == [
        "external_state_change"
    ]
    assert blender["server_definition"]["id"] == "blender"
    assert blender["connection_profile"]["type"] == "stdio"
    assert blender["session"]["state"] == "disabled"
    assert MCP_SERVICE_SCHEMA_VERSION in path.read_text(encoding="utf-8")

    manager.delete("blender")
    reloaded = McpServiceManager(path)
    with pytest.raises(KeyError):
        reloaded.get_public("blender")


def test_mcp_schema_migration_adds_new_seed_prerequisites_to_old_blender_config(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mcp-services.json"
    path.write_text(
        """
        {
          "schema_version": "mcp_service.v3",
          "services": [{
            "id": "blender",
            "name": "My Blender",
            "enabled": false,
            "transport": {"type": "stdio", "command": "uvx", "args": ["blender-mcp"]},
            "prerequisites": []
          }]
        }
        """,
        encoding="utf-8",
    )

    blender = McpServiceManager(path).get_public("blender")

    assert blender["name"] == "My Blender"
    assert [item["id"] for item in blender["prerequisites"]] == ["blender-addon", "uvx"]
    assert blender["timeouts"]["call"] == 30
    assert blender["tool_policies"]["get_scene_info"]["call_timeout"] == 25
    assert blender["transport"]["env_keys"] == ["BLENDER_MCP_DISABLE_TELEMETRY"]


@pytest.mark.asyncio
async def test_disabled_service_check_reports_prerequisites_without_connecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = await asyncio.start_server(lambda _reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert({
        "id": "probe-demo",
        "enabled": False,
        "transport": {"type": "stdio", "command": sys.executable, "args": [str(FAKE_MCP_SERVER)]},
        "prerequisites": [
            {"id": "socket", "kind": "tcp", "host": "127.0.0.1", "port": port},
            {"id": "missing", "kind": "executable", "command": "definitely-missing-command"},
        ],
    })

    try:
        await manager.check("probe-demo")
    finally:
        server.close()
        await server.wait_closed()

    public = manager.get_public("probe-demo")
    assert public["status"]["state"] == "disabled"
    assert public["status"]["protocol_connected"] is False
    assert public["status"]["prerequisites"][0]["ready"] is True
    assert public["status"]["prerequisites"][1]["ready"] is False
    assert "1/2" in public["status"]["message"]


@pytest.mark.asyncio
async def test_start_reports_missing_prerequisite_before_launching_process(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert({
        "id": "missing-runner",
        "enabled": True,
        "transport": {"type": "stdio", "command": "definitely-missing-command", "args": []},
        "prerequisites": [
            {
                "id": "runner",
                "label": "Demo package runner",
                "kind": "executable",
                "command": "definitely-missing-command",
            },
        ],
    })

    with pytest.raises(RuntimeError, match="Demo package runner"):
        await manager.start("missing-runner")

    public = manager.get_public("missing-runner")
    assert public["status"]["state"] == "failed"
    assert public["status"]["pid"] is None


def test_mcp_control_request_rejects_cross_origin_browser_request() -> None:
    same_origin = SimpleNamespace(
        request=SimpleNamespace(
            headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"},
            remote_ip="127.0.0.1",
        )
    )
    require_local_mcp_control_request(same_origin)

    cross_origin = SimpleNamespace(
        request=SimpleNamespace(
            headers={"Origin": "https://example.com", "Host": "127.0.0.1:8765"},
            remote_ip="127.0.0.1",
        )
    )
    with pytest.raises(tornado.web.HTTPError) as exc:
        require_local_mcp_control_request(cross_origin)

    assert exc.value.status_code == 403


def test_mcp_control_request_rejects_remote_request_without_origin() -> None:
    remote = SimpleNamespace(
        request=SimpleNamespace(headers={"Host": "192.168.1.8:8765"}, remote_ip="192.168.1.20")
    )

    with pytest.raises(tornado.web.HTTPError) as exc:
        require_local_mcp_control_request(remote)

    assert exc.value.status_code == 403
