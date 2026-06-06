# Contributing to YuntaoCode

Thanks for helping improve YuntaoCode. This project is still in active alpha, so the most valuable contributions are small, well-tested changes that make the local runtime more stable, safer, and easier to extend.

## Development Setup

Use Python 3.10 or newer.

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

For the full document and browser toolchain, install:

```bash
python -m pip install -r requirements.txt
```

For the desktop shell:

```bash
cd desktop-shell
npm ci
npm run build:ui
```

## Verification

Before opening a pull request, run the checks that match your change:

```bash
python scripts/sync_release_version.py --check
pytest
python scripts/smoke_core.py
```

For frontend-only changes:

```bash
npm --prefix desktop-shell run build:ui
node --check desktop-shell/src/main.js
```

For Tauri changes:

```bash
powershell -ExecutionPolicy Bypass -File scripts/prepare_tauri_check.ps1
cargo check --manifest-path desktop-shell/src-tauri/Cargo.toml
```

## Contribution Guidelines

- Keep changes scoped to one clear problem.
- Prefer existing runtime patterns over new abstractions.
- Read `AGENTS.md` before making AI-assisted runtime, tool, or frontend changes.
- Add tests for path access, write tools, task execution, plugin behavior, and model-provider compatibility when those areas change.
- Do not include API keys, user data, local conversation data, packaged binaries, or generated build output.
- Document user-visible behavior changes in `CHANGELOG.md`.
- Change the product release version only in `runtime/version.py`, then run
  `python scripts/sync_release_version.py`. Do not tie schema, settings,
  plugin, or static asset versions to the product release version.

## Pull Requests

Please include:

- What changed.
- How it was verified.
- Any compatibility, security, or migration notes.

The public plugin and MCP interfaces are still evolving before v1.0, so changes in those areas should include a short rationale.
