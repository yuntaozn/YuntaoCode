from runtime.agent_strategy.classifiers import TOOL_ID_ALIASES as STRATEGY_TOOL_ID_ALIASES
from runtime.skills import register_builtin_tools
from runtime.tool_aliases import TOOL_ID_ALIASES, normalize_tool_id
from runtime.tool_registry import DEFAULT_TOOL_ID_ALIASES, ToolRegistry


def _registered_tool_ids() -> set[str]:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return {item["id"] for item in registry.list_specs()}


def test_tool_aliases_have_single_source_of_truth() -> None:
    assert DEFAULT_TOOL_ID_ALIASES is TOOL_ID_ALIASES
    assert STRATEGY_TOOL_ID_ALIASES is TOOL_ID_ALIASES


def test_all_default_tool_alias_targets_are_registered_tools() -> None:
    registered = _registered_tool_ids()

    missing = {
        alias: target
        for alias, target in TOOL_ID_ALIASES.items()
        if target not in registered
    }

    assert missing == {}


def test_common_model_tool_name_variants_resolve_to_registered_tools() -> None:
    registered = _registered_tool_ids()
    aliases = {
        "filesystem.list_dir": "filesystem.scan_folder",
        "filesystem.list_files": "filesystem.scan_folder",
        "filesystem.list_project_files": "code.list_project_files",
        "filesystem.preview_text": "filesystem.read_text_preview",
        "filesystem.write_changes": "filesystem.apply_changes",
        "filesystem.apply_change_set": "filesystem.apply_changes",
        "filesystem.write_temp": "filesystem.write_temp_file",
        "filesystem.remove_file": "filesystem.delete_file",
        "filesystem.copy": "filesystem.copy_file",
        "filesystem.cp": "filesystem.copy_file",
        "document.pdf_extract_text": "document.extract_pdf_text_preview",
        "document.extract_docx": "document.extract_docx_outline",
        "document.pdf_to_word": "document.extract_pdf_to_docx",
        "document.convert_pdf_to_docx": "document.extract_pdf_to_docx",
        "document.translate_word": "document.translate_docx",
        "document.generate_powerpoint": "document.generate_ppt",
        "code.search": "code.search_text",
        "code.search_files": "code.search_text",
        "shell.exec": "shell.run_command",
        "git.get_diff": "git.diff",
        "web.fetch": "web.fetch_url",
        "preview.verify_ui": "preview.interact_page",
        "preview.interact": "preview.interact_page",
        "memory.search": "memory.recall",
    }

    for alias, target in aliases.items():
        assert normalize_tool_id(alias) == target
        assert target in registered


def test_double_underscore_tool_names_are_normalized() -> None:
    assert normalize_tool_id("filesystem__read_file") == "filesystem.read_file"
    assert normalize_tool_id("document__pdf_extract_text") == "document.extract_pdf_text_preview"


def test_xml_parameter_suffix_is_stripped_from_tool_names() -> None:
    assert (
        normalize_tool_id('filesystem.read_file</parameter><parameter name="path" string="true')
        == "filesystem.read_file"
    )
    assert (
        normalize_tool_id('filesystem.scan_folder</parameter><parameter name="path" string="true')
        == "filesystem.scan_folder"
    )


def test_xml_parameter_suffix_keeps_alias_resolution() -> None:
    assert (
        normalize_tool_id('filesystem.list_dir</parameter><parameter name="path" string="true')
        == "filesystem.scan_folder"
    )


def test_registry_resolves_tool_name_with_xml_parameter_suffix() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)

    assert (
        registry.resolve_id('filesystem.read_file</parameter><parameter name="path" string="true')
        == "filesystem.read_file"
    )
