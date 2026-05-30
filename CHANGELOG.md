# Changelog

All notable changes to YuntaoCode will be documented in this file.

The format follows Keep a Changelog style, and this project uses pre-1.0 semantic versioning while APIs are still evolving.

## [Unreleased]

### Added

- Open-source contribution guide, security policy, issue templates, pull request template, and CI workflow.
- Pytest coverage for workspace path boundaries, task confirmation behavior, disabled plugin blocking, and tool registry metadata.
- Development extras in `pyproject.toml` for tests, document tools, web tools, and sidecar builds.

### Changed

- Normalized repository metadata URLs in `pyproject.toml`.
- Updated quick-start documentation with editable install, pytest, smoke test, and desktop UI build commands.
- Refined the roadmap to separate open-source hardening, plugin protocol work, MCP integration, and later marketplace work.

### Known Gaps

- API token enforcement and CORS tightening are still planned security hardening tasks.
- The external plugin manifest and loader are not yet implemented.
- Full Tauri package builds require the platform-specific Rust, WebView, Node, and Python sidecar toolchain.
