from runtime.agent_strategy.confirmation_policy import (
    classify_tool_risk,
    decide_tool_confirmation,
    normalize_confirmation_policy,
)


def test_read_only_tools_never_require_confirmation() -> None:
    for policy in ("conservative", "auto", "aggressive"):
        decision = decide_tool_confirmation(policy, "filesystem.read_file")

        assert decision.requires_confirmation is False
        assert decision.risk == "read_only"


def test_conservative_policy_confirms_workspace_write() -> None:
    decision = decide_tool_confirmation("conservative", "filesystem.write_file")

    assert decision.requires_confirmation is True
    assert decision.risk == "workspace_write"


def test_auto_policy_allows_workspace_write_but_confirms_privileged_tools() -> None:
    write_decision = decide_tool_confirmation("auto", "filesystem.write_file")
    shell_decision = decide_tool_confirmation("auto", "shell.run_command")
    git_decision = decide_tool_confirmation("auto", "git.commit")

    assert write_decision.requires_confirmation is False
    assert shell_decision.requires_confirmation is True
    assert git_decision.requires_confirmation is True


def test_aggressive_policy_allows_authorized_privileged_tool() -> None:
    decision = decide_tool_confirmation("aggressive", "shell.run_command")

    assert decision.requires_confirmation is False
    assert decision.risk == "privileged"


def test_declared_unknown_state_change_uses_confirmation_policy() -> None:
    assert classify_tool_risk("plugin.custom", declared_confirmation=True) == "declared_state_change"
    assert decide_tool_confirmation(
        "auto",
        "plugin.custom",
        declared_confirmation=True,
    ).requires_confirmation
    assert not decide_tool_confirmation(
        "aggressive",
        "plugin.custom",
        declared_confirmation=True,
    ).requires_confirmation


def test_invalid_confirmation_policy_falls_back_to_auto() -> None:
    assert normalize_confirmation_policy("unknown") == "auto"

