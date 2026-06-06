from runtime import __version__
from runtime.api import health
from scripts.sync_release_version import (
    ROOT,
    _json_with_version,
    _package_lock_with_version,
    release_version,
    rendered_targets,
    sync_release_version,
)


def test_release_version_source_matches_runtime_public_version() -> None:
    assert release_version() == __version__
    assert health.__version__ == __version__


def test_release_version_references_are_synchronized() -> None:
    assert sync_release_version(check=True) == []


def test_release_version_targets_exclude_independent_versions() -> None:
    targets = {path.relative_to(ROOT).as_posix() for path in rendered_targets(__version__)}

    assert "runtime/settings_store.py" not in targets
    assert not any(path.startswith("runtime/core/") for path in targets)
    assert not any(path.startswith("ai-plugins/") for path in targets)
    assert not any(path.startswith("runtime/panel/") for path in targets)


def test_python_package_uses_dynamic_release_version() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in pyproject
    assert 'version = {attr = "runtime.version.__version__"}' in pyproject


def test_json_version_sync_preserves_existing_formatting(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{\n  "version": "0.1.0",\n  "targets": ["nsis"]\n}\n',
        encoding="utf-8",
    )

    rendered = _json_with_version(manifest, "0.2.0")

    assert rendered == '{\n  "version": "0.2.0",\n  "targets": ["nsis"]\n}\n'


def test_package_lock_sync_changes_only_project_version_entries(tmp_path) -> None:
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        '{\n'
        '  "version": "0.1.0",\n'
        '  "packages": {\n'
        '    "": {\n'
        '      "version": "0.1.0"\n'
        "    },\n"
        '    "node_modules/demo": {\n'
        '      "version": "9.9.9"\n'
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    rendered = _package_lock_with_version(lockfile, "0.2.0")

    assert rendered.count('"version": "0.2.0"') == 2
    assert '"version": "9.9.9"' in rendered
