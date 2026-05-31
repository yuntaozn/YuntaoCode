# Changelog

All notable changes to YuntaoCode will be documented in this file.

The format follows Keep a Changelog style, and this project uses pre-1.0 semantic versioning while APIs are still evolving.

## [Unreleased]

### Added

- Open-source contribution guide, security policy, issue templates, pull request template, and CI workflow.
- `AGENTS.md` with AI-assisted development conventions for runtime, tools, frontend streaming, safety, and verification.
- `runtime/agent_strategy/` strategy modules for classifiers, profiles, policy, prompts, and plan tracking.
- Pytest coverage for workspace path boundaries, task confirmation behavior, disabled plugin blocking, and tool registry metadata.
- Strategy tests covering internal profiles, deterministic plan routing, prompt helpers, plan tracking, and scripted model/tool behavior.
- Development extras in `pyproject.toml` for tests, document tools, web tools, and sidecar builds.

### Changed

- Normalized repository metadata URLs in `pyproject.toml`.
- Updated quick-start documentation with editable install, pytest, smoke test, and desktop UI build commands.
- Moved planning/stage policy out of inline runner branches so `conversation_runner.py` can stay closer to orchestration.
- Improved streaming chat reconciliation to avoid duplicate submissions and preserve reasoning/process history during final message replacement.
- Refined the roadmap to separate open-source hardening, plugin protocol work, MCP integration, and later marketplace work.

### Known Gaps

- API token enforcement and CORS tightening are still planned security hardening tasks.
- The external plugin manifest and loader are not yet implemented.
- Full Tauri package builds require the platform-specific Rust, WebView, Node, and Python sidecar toolchain.
