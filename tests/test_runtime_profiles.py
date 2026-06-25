from __future__ import annotations

from runtime.app import RuntimeFeatureSet, build_runtime
from runtime.config import RuntimeConfig
from runtime.skills import CORE_BUILTIN_TOOL_GROUPS, DEFAULT_BUILTIN_TOOL_GROUPS, register_builtin_tools
from runtime.tool_registry import ToolRegistry


def _tool_ids_for(groups: tuple[str, ...]) -> set[str]:
    registry = ToolRegistry()
    register_builtin_tools(registry, groups=groups)
    return {item["id"] for item in registry.list_specs()}


def test_lite_profile_selects_core_runtime_tool_groups() -> None:
    lite = RuntimeFeatureSet.from_profile("lite")

    assert lite.profile == "lite"
    assert lite.tool_groups == CORE_BUILTIN_TOOL_GROUPS
    assert lite.mcp_services is False
    assert lite.cli_providers is False
    assert lite.automations is False
    assert lite.capability_packs is False


def test_full_profile_preserves_all_builtin_tool_groups() -> None:
    full = RuntimeFeatureSet.from_profile("full")

    assert full.profile == "full"
    assert full.tool_groups == DEFAULT_BUILTIN_TOOL_GROUPS


def test_lite_tool_groups_exclude_optional_product_capabilities() -> None:
    tool_ids = _tool_ids_for(CORE_BUILTIN_TOOL_GROUPS)

    assert "filesystem.read_file" in tool_ids
    assert "code.search_text" in tool_ids
    assert "shell.run_command" in tool_ids
    assert "document.extract_pdf_to_docx" not in tool_ids
    assert "spreadsheet.inspect_workbook" not in tool_ids
    assert "web.fetch_url" not in tool_ids


def test_lite_runtime_skips_optional_managers(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "appdata"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(data_root))
    config = RuntimeConfig.build("127.0.0.1", 8765, "test-token", [str(workspace)])

    runtime = build_runtime(config, profile="lite")
    try:
        assert runtime.features.profile == "lite"
        assert runtime.mcp_services is None
        assert runtime.cli_providers is None
        assert runtime.automations is None
        assert runtime.capability_packs is None
        assert "filesystem.read_file" in {item["id"] for item in runtime.registry.list_specs()}
        assert "document.extract_pdf_to_docx" not in {item["id"] for item in runtime.registry.list_specs()}
    finally:
        runtime.close()
