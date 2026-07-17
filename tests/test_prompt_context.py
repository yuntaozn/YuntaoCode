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

    assert "Web Capability Facts" in prompt
    assert "exact descriptions and schemas" in prompt
    assert "web.render_page" in prompt
    assert "try web.extract_text first" not in prompt


def test_build_system_prompt_does_not_add_web_access_guidance_without_web_tools() -> None:
    prompt = build_system_prompt(
        settings=_Settings(),
        mode_config=_mode_config(),
        workspace_path=r"D:\code\demo",
        capability_context="- filesystem.local_files: Read local files; tools=filesystem.read_file",
    )

    assert "Web Capability Facts" not in prompt


def test_build_system_prompt_adds_text_write_route_guidance_when_available() -> None:
    prompt = build_system_prompt(
        settings=_Settings(),
        mode_config=_mode_config(),
        workspace_path=r"D:\code\demo",
        capability_context="- code.text_write: Write text files; tools=code.edit_file, filesystem.write_file, filesystem.finalize_text_file",
    )

    assert "Text Write Capability Facts" in prompt
    assert "code.edit_file" in prompt
    assert "filesystem.write_file" in prompt
    assert "filesystem.finalize_text_file" in prompt
    assert "Large single-call arguments can be truncated" in prompt
    assert "model chooses the method" in prompt
    assert "default to" not in prompt


def test_build_system_prompt_adds_preview_guidance_when_available() -> None:
    prompt = build_system_prompt(
        settings=_Settings(),
        mode_config=_mode_config(),
        workspace_path=r"D:\code\demo",
        capability_context=(
            "- preview.visual_debug: Capture visual evidence; "
            "tools=preview.capture_local_html, preview.capture_file, preview.capture_url, preview.interact_page"
        ),
    )

    assert "Preview Capability Facts" in prompt
    assert "preview.capture_local_html" in prompt
    assert "preview.capture_file" in prompt
    assert "preview.interact_page" in prompt
    assert "interaction traces" in prompt
    assert "visual evidence" in prompt
    assert "model decides" in prompt


def test_build_system_prompt_accepts_explicit_memory_boundary() -> None:
    class _UnexpectedMemorySettings:
        def get_memory_prompt(self, *, user_message: str = "", workspace_id: str = "") -> str:
            raise AssertionError("memory selection must stay outside the base prompt")

    prompt = build_system_prompt(
        settings=_UnexpectedMemorySettings(),
        mode_config=_mode_config(),
        workspace_path=r"D:\code\demo",
        user_memory="",
    )

    assert "Current project directory" in prompt
