import pytest

from runtime.app import RuntimeState
from runtime.tool_registry import ToolRegistry, ToolSpec


async def _noop_handler(input_data, context):
    return {"ok": True}


def test_runtime_state_combines_tool_readiness_with_provider_lifecycle() -> None:
    runtime = type("RuntimeStub", (), {"cli_providers": None, "mcp_services": None})()

    assert RuntimeState.is_tool_available(
        runtime,
        {"id": "preview.capture_local_html", "source_type": "builtin", "available": False},
    ) is False
    assert RuntimeState.is_tool_available(
        runtime,
        {"id": "filesystem.read_file", "source_type": "builtin", "available": True},
    ) is True


def test_tool_registry_rejects_duplicate_tool_ids() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        id="demo.tool",
        name="Demo Tool",
        description="Demo",
        input_schema={"type": "object"},
    )

    registry.register(spec, _noop_handler)

    with pytest.raises(ValueError):
        registry.register(spec, _noop_handler)


def test_tool_spec_reports_missing_optional_dependencies() -> None:
    spec = ToolSpec(
        id="demo.optional",
        name="Optional Demo",
        description="Demo",
        input_schema={"type": "object"},
        optional_dependencies=["definitely_missing_yuntaocode_dependency"],
    )

    assert spec.check_dependencies() == {
        "definitely_missing_yuntaocode_dependency": False,
    }
    readiness = spec.check_readiness()
    assert readiness["available"] is False
    assert readiness["health"] == "unavailable"
    assert readiness["code"] == "python_dependency_missing"


def test_tool_spec_exposes_runtime_readiness_without_executing_tool() -> None:
    spec = ToolSpec(
        id="demo.degraded",
        name="Degraded Demo",
        description="Demo",
        input_schema={"type": "object"},
        readiness_probe=lambda: {
            "available": True,
            "health": "degraded",
            "code": "optional_route_missing",
            "message": "One optional route is unavailable.",
            "details": {"route": "browser"},
        },
    )

    public = spec.to_public_dict()

    assert public["available"] is True
    assert public["tool_health"] == "degraded"
    assert public["readiness"]["code"] == "optional_route_missing"
    assert public["tool_last_error"] == "One optional route is unavailable."


def test_list_specs_includes_public_metadata() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="demo.read",
            name="Demo Read",
            description="Reads demo data",
            input_schema={"type": "object"},
            requires_confirmation=False,
            local_only=True,
            capability="demo.read",
            artifacts=["text"],
            effects=["external_state_change"],
            roles=["evidence"],
            idempotent=True,
        ),
        _noop_handler,
    )

    specs = registry.list_specs()

    assert specs == [
        {
            "id": "demo.read",
            "name": "Demo Read",
            "description": "Reads demo data",
            "input_schema": {"type": "object"},
            "requires_confirmation": False,
            "local_only": True,
            "dependencies": {},
            "available": True,
            "tool_health": "available",
            "readiness": {
                "available": True,
                "health": "available",
                "code": "ready",
                "message": "",
                "details": {},
            },
            "capability": "demo.read",
            "artifacts": ["text"],
            "effects": ["external_state_change"],
            "roles": ["evidence"],
            "long_running": False,
            "retry_safe": False,
            "idempotent": True,
            "provider_id": "demo",
            "provider_kind": "builtin",
            "provider": {
                "schema_version": "capability_provider.v1",
                "provider_id": "demo",
                "provider_kind": "builtin",
                "source_type": "builtin",
                "source_id": "demo",
                "display_name": "demo",
                "lifecycle": "in_process",
                "local_only": True,
                "metadata": {},
            },
            "source_type": "builtin",
            "source_id": "demo",
        }
    ]


def test_registry_exposes_provider_source_metadata() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="demo.get_scene_info",
            name="Scene",
            description="Read scene information",
            input_schema={"type": "object"},
        ),
        _noop_handler,
    )
    registry.set_provider_metadata(
        "demo",
        source_type="external_adapter",
        source_id="demo-adapter",
    )

    spec = registry.list_specs()[0]

    assert spec["source_type"] == "external_adapter"
    assert spec["source_id"] == "demo-adapter"
    assert spec["provider_id"] == "demo"
    assert spec["provider_kind"] == "external_plugin"
    assert spec["provider"]["lifecycle"] == "external_adapter"
    assert registry.get_public_spec("demo.get_scene_info") == spec


def test_registry_exposes_cli_provider_kind() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="pdf_cli.convert",
            name="Convert PDF",
            description="Convert PDF with a declared CLI provider",
            input_schema={"type": "object"},
        ),
        _noop_handler,
    )
    registry.set_provider_metadata(
        "pdf_cli",
        source_type="cli",
        source_id="pdf-tools",
    )

    spec = registry.list_specs()[0]

    assert spec["provider_kind"] == "cli"
    assert spec["provider"]["lifecycle"] == "subprocess"
    assert spec["source_type"] == "cli"


def test_registry_can_unbind_all_tools_from_a_dynamic_source() -> None:
    registry = ToolRegistry()
    registry.set_provider_metadata("remote", source_type="mcp", source_id="remote")
    registry.register(
        ToolSpec(
            id="remote.echo",
            name="Echo",
            description="Echo",
            input_schema={"type": "object"},
        ),
        _noop_handler,
    )

    removed = registry.unregister_source(source_type="mcp", source_id="remote")

    assert removed == ["remote.echo"]
    with pytest.raises(KeyError):
        registry.get("remote.echo")


def test_registry_resolves_legacy_tool_aliases_without_listing_them() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="filesystem.scan_folder",
            name="Scan Folder",
            description="Scan folder",
            input_schema={"type": "object"},
        ),
        _noop_handler,
    )

    assert registry.resolve_id("filesystem.list_dir") == "filesystem.scan_folder"
    assert registry.resolve_id("filesystem__list_dir") == "filesystem.scan_folder"
    assert registry.get("filesystem.list_dir").spec.id == "filesystem.scan_folder"
    assert [spec["id"] for spec in registry.list_specs()] == ["filesystem.scan_folder"]


def test_registry_resolves_pdf_document_aliases_without_listing_them() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="document.extract_pdf_text_preview",
            name="Extract PDF Text",
            description="Extract PDF text",
            input_schema={"type": "object"},
        ),
        _noop_handler,
    )

    assert registry.resolve_id("document.pdf_extract_text") == "document.extract_pdf_text_preview"
    assert registry.resolve_id("document.extract_pdf_text") == "document.extract_pdf_text_preview"
    assert registry.resolve_id("document.read_pdf") == "document.extract_pdf_text_preview"
    assert registry.get("document.pdf_extract_text").spec.id == "document.extract_pdf_text_preview"
    assert [spec["id"] for spec in registry.list_specs()] == ["document.extract_pdf_text_preview"]


def test_registry_resolves_spreadsheet_aliases_without_listing_them() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="spreadsheet.inspect_workbook",
            name="Inspect Workbook",
            description="Inspect spreadsheet",
            input_schema={"type": "object"},
        ),
        _noop_handler,
    )

    assert registry.resolve_id("document.read_excel") == "spreadsheet.inspect_workbook"
    assert registry.resolve_id("spreadsheet.read_excel") == "spreadsheet.inspect_workbook"
    assert registry.resolve_id("spreadsheet.preview") == "spreadsheet.inspect_workbook"
    assert registry.get("document.read_excel").spec.id == "spreadsheet.inspect_workbook"
    assert [spec["id"] for spec in registry.list_specs()] == ["spreadsheet.inspect_workbook"]


def test_registry_reports_missing_required_input_before_execution() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="filesystem.write_file",
            name="Write File",
            description="Write a file",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        ),
        _noop_handler,
    )

    assert registry.missing_required_input_fields("filesystem.write_file", {}) == [
        "path",
        "content",
    ]
    assert registry.missing_required_input_fields(
        "filesystem.write_file",
        {"path": "demo.txt", "content": ""},
    ) == []


def test_registry_normalizes_code_edit_file_top_level_replace_fields() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="code.edit_file",
            name="Edit File",
            description="Edit a file",
            input_schema={
                "type": "object",
                "required": ["path", "edits"],
                "properties": {
                    "path": {"type": "string"},
                    "edits": {"type": "array"},
                },
            },
        ),
        _noop_handler,
    )

    input_data = {
        "path": "src/app.js",
        "old_text": "const value = 1;",
        "new_text": "const value = 2;",
    }

    assert registry.missing_required_input_fields("code.edit_file", input_data) == []
    assert registry.normalize_input_data("code.edit_file", input_data) == {
        "path": "src/app.js",
        "old_text": "const value = 1;",
        "new_text": "const value = 2;",
        "edits": [{"old_text": "const value = 1;", "new_text": "const value = 2;"}],
    }


def test_registry_normalizes_code_edit_file_top_level_line_range_fields() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="code.edit_file",
            name="Edit File",
            description="Edit a file",
            input_schema={
                "type": "object",
                "required": ["path", "edits"],
                "properties": {
                    "path": {"type": "string"},
                    "edits": {"type": "array"},
                },
            },
        ),
        _noop_handler,
    )

    input_data = {
        "path": "src/app.js",
        "start_line": 10,
        "end_line": 12,
        "new_text": "replacement",
    }

    assert registry.missing_required_input_fields("code.edit_file", input_data) == []
    assert registry.normalize_input_data("code.edit_file", input_data) == {
        "path": "src/app.js",
        "start_line": 10,
        "end_line": 12,
        "new_text": "replacement",
        "edits": [{"start_line": 10, "end_line": 12, "new_text": "replacement"}],
    }


def test_registry_normalizes_apply_changes_top_level_replace_fields() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="filesystem.apply_changes",
            name="Apply Changes",
            description="Apply changes",
            input_schema={
                "type": "object",
                "required": ["operations"],
                "properties": {"operations": {"type": "array"}},
            },
        ),
        _noop_handler,
    )

    input_data = {
        "path": "src/app.js",
        "old_text": "const value = 1;",
        "new_text": "const value = 2;",
    }

    assert registry.missing_required_input_fields("filesystem.apply_changes", input_data) == []
    assert registry.normalize_input_data("filesystem.apply_changes", input_data)["operations"] == [
        {
            "type": "replace_text",
            "path": "src/app.js",
            "old_text": "const value = 1;",
            "new_text": "const value = 2;",
        }
    ]
