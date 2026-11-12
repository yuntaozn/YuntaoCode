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


def test_base_prompt_contains_boundary_without_tool_catalog_or_route_appendices() -> None:
    prompt = build_system_prompt(
        settings=_Settings(), mode_config=_mode_config(), workspace_path="/project",
    )
    assert "/project" in prompt
    assert "Runtime" in prompt
    assert "filesystem." not in prompt
    assert "web." not in prompt
    assert "能力包草稿边界补充" not in prompt
    assert len(prompt) < 300


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
