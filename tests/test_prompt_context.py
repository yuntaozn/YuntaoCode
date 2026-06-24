from runtime.prompt_context import build_system_prompt


class _Settings:
    def get_memory_prompt(self, *, user_message: str = "", workspace_id: str = "") -> str:
        return ""


def _mode_config() -> dict:
    return {
        "system_prompt": (
            "You are YuntaoCode.\n"
            "Current project directory: {workspace_path}\n"
            "{user_memory}\n"
            "## Capability Extension Rules\n"
        ),
    }


def test_build_system_prompt_adds_web_access_guidance_when_web_tools_are_available() -> None:
    prompt = build_system_prompt(
        settings=_Settings(),
        mode_config=_mode_config(),
        workspace_path=r"D:\code\demo",
        capability_context="- web.network_fetch: Fetch network content; tools=web.extract_text, web.render_page",
    )

    assert "Web Access Capability Addendum" in prompt
    assert "try web.extract_text first" in prompt
    assert "web.render_page" in prompt


def test_build_system_prompt_does_not_add_web_access_guidance_without_web_tools() -> None:
    prompt = build_system_prompt(
        settings=_Settings(),
        mode_config=_mode_config(),
        workspace_path=r"D:\code\demo",
        capability_context="- filesystem.local_files: Read local files; tools=filesystem.read_file",
    )

    assert "Web Access Capability Addendum" not in prompt


def test_build_system_prompt_adds_text_write_route_guidance_when_available() -> None:
    prompt = build_system_prompt(
        settings=_Settings(),
        mode_config=_mode_config(),
        workspace_path=r"D:\code\demo",
        capability_context="- code.text_write: Write text files; tools=code.edit_file, filesystem.write_file, filesystem.finalize_text_file",
    )

    assert "Text Write Route Addendum" in prompt
    assert "code.edit_file" in prompt
    assert "filesystem.write_file" in prompt
    assert "filesystem.create_text_draft" in prompt
    assert "filesystem.finalize_text_file" in prompt
    assert "New or rewritten complete text/code artifact with non-trivial length" in prompt
    assert "not use filesystem.write_file or a large filesystem.apply_changes payload" in prompt
    assert "Plan chunk boundaries" in prompt
    assert "do not wait for truncation before switching to draft chunks" in prompt
