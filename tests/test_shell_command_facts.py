from runtime.shell_command_facts import shell_command_facts


def test_python_playwright_install_is_long_running_dependency_install() -> None:
    facts = shell_command_facts(
        "python.exe",
        ["-m", "playwright", "install", "chromium"],
    )

    assert facts.role == "dependency_install"
    assert facts.long_running is True
    assert facts.default_timeout == 600


def test_common_package_managers_are_dependency_installs() -> None:
    assert shell_command_facts("npm.cmd", ["install"]).role == "dependency_install"
    assert shell_command_facts("uv", ["pip", "install", "pytest"]).role == "dependency_install"
    assert shell_command_facts("pip", ["install", "pytest"]).role == "dependency_install"


def test_inline_command_form_is_also_classified_for_execution_facts() -> None:
    facts = shell_command_facts("python -m playwright install chromium")

    assert facts.role == "dependency_install"
    assert facts.default_timeout == 600


def test_test_command_remains_an_ordinary_command() -> None:
    facts = shell_command_facts("python", ["-m", "pytest"])

    assert facts.role == "command"
    assert facts.default_timeout == 30
