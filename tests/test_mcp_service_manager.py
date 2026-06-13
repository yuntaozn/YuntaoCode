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
        "tool_policies": {
            "echo": {"risk": "read_only", "roles": ["evidence"]},
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

    await manager.stop("demo-mcp")
    assert manager.get_public("demo-mcp")["status"]["state"] == "stopped"
    with pytest.raises(KeyError):
        registry.get("mcp_demo_mcp.echo")


@pytest.mark.asyncio
async def test_disabled_mcp_service_cannot_start(tmp_path: Path) -> None:
    manager = McpServiceManager(tmp_path / "mcp-services.json")
    manager.upsert(_stdio_service(enabled=False))

    with pytest.raises(RuntimeError, match="enable"):
        await manager.start("demo-mcp")


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
    assert blender["tool_policies"]["get_scene_info"]["risk"] == "read_only"
    assert blender["tool_policies"]["get_scene_info"]["roles"] == ["evidence", "verification"]
    assert blender["tool_policies"]["get_scene_info"]["verification_strength"] == "weak"
    assert blender["tool_policies"]["get_viewport_screenshot"]["verification_strength"] == "standard"
    assert blender["tool_policies"]["execute_blender_code"]["effects"] == [
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
