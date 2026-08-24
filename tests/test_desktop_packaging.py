from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_sidecar_build_is_consoleless_by_default() -> None:
    script = (ROOT / "scripts" / "build_sidecar_windows.ps1").read_text(encoding="utf-8")

    assert "[switch]$Console" in script
    assert "if (-not $Console)" in script
    assert '$pyinstallerArgs += @("--noconsole")' in script
    assert "[switch]$Windowed" not in script


def test_console_sidecar_requires_an_explicit_diagnostic_command() -> None:
    package = json.loads((ROOT / "desktop-shell" / "package.json").read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert "-Console" not in scripts["sidecar:windows"]
    assert "-Console" in scripts["sidecar:windows:console"]
    assert "-ConsoleSidecar" not in scripts["build:windows"]
    assert "-ConsoleSidecar" in scripts["build:windows:console"]


def test_panel_pages_use_the_shared_in_app_confirmation() -> None:
    pages = {
        "index.html": "panel.js",
        "settings.html": "settings.js",
        "automation.html": "automation.js",
        "mcp-services.html": "mcp-services.js",
    }
    template_root = ROOT / "runtime" / "panel" / "templates"
    static_root = ROOT / "runtime" / "panel" / "static"

    for template_name, page_script in pages.items():
        template = (template_root / template_name).read_text(encoding="utf-8")
        assert template.index("/static/confirm-dialog.js") < template.index(f"/static/{page_script}")

        source = (static_root / page_script).read_text(encoding="utf-8")
        assert "window.confirm" not in source
        assert "if (!confirm(" not in source
        assert "if (confirm(" not in source
