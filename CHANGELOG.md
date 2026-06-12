# Changelog

All notable changes to YuntaoCode will be documented in this file.

The format follows Keep a Changelog style, and this project uses pre-1.0 semantic versioning while APIs are still evolving.

## [Unreleased]

### Added

- Runtime-owned conversation attachments for images and files, including
  persisted previews and controlled text extraction for text, PDF, and Word
  inputs without placing uploads in project workspaces.
- Open-source contribution guide, security policy, issue templates, pull request template, and CI workflow.
- `AGENTS.md` with AI-assisted development conventions for runtime, tools, frontend streaming, safety, and verification.
- `runtime/agent_strategy/` strategy modules for classifiers, profiles, policy, prompts, and plan tracking.
- `docs/task-model.md` to define the Task-first direction for task state, lifecycle, trace, recovery, audit, and templates.
- `docs/context-runtime.md` and `docs/capability-runtime.md` to define context and capability runtime foundations.
- `runtime/core/` pure schema package for product-level Task, TraceEvent, RuntimeResult, ContextRecord, EvidenceRecord, and CapabilityContract concepts.
- `docs/capability-router.md` and `runtime/agent_strategy/capability_router.py` to define model-first task routing through runtime-validated capability contracts.
- Pytest coverage for workspace path boundaries, task confirmation behavior, disabled plugin blocking, and tool registry metadata.
- Strategy tests covering internal profiles, deterministic plan routing, prompt helpers, plan tracking, and scripted model/tool behavior.
- Development extras in `pyproject.toml` for tests, document tools, web tools, and sidecar builds.
- Resumable Word translation checkpoints for long `document.translate_docx` tasks, including partial task status and UI progress details.
- `filesystem.write_temp_file` and task-scoped temporary directories so one-off scripts and intermediate files do not pollute user projects.
- Model-proposed `task_contract` normalization so task intent, deliverables, write requirements, verification requirements, and plan needs can be decided before execution and audited in run events.
- Single-source product release versioning with synchronized desktop manifests, README labels, Runtime health output, and CI drift checks.
- Controlled web artifact tools: `web.collect_site_assets` saves bounded website page/resource snapshots, and `web.capture_page` exports webpages as PDF or screenshots.
- Text artifact draft tools for large text/code outputs: create a draft, append bounded chunks, inspect progress, and finalize to a validated workspace file.
- Independent MCP service management foundation with local configuration,
  redacted secrets, explicit lifecycle actions, connection state, logs, and a
  dedicated management page.
- Generic stdio MCP sessions with protocol handshake, tool discovery, dynamic
  capability binding, invocation, and disconnect cleanup.
- A disabled Blender MCP example configuration for demonstrating the MCP
  connection boundary without a Blender-specific built-in runtime adapter.
- Generic MCP prerequisite checks for TCP endpoints and executable commands,
  including separate Blender Add-on and `uvx` readiness indicators.
- MCP executable resolution through the current Python runtime's `Scripts`
  directory, plus local-first telemetry disablement for the Blender example.
- Task contracts can distinguish local file writes from broader observable
  state changes, including external application state.
- Capability and MCP tool contracts can declare successful `effects`, task
  `roles`, and artifact kinds for provider-neutral result auditing.
- Shared atomic JSON persistence mechanics and an indexed SQLite Run/RunEvent
  repository with one-time legacy `runs.json` import.

### Changed

- Normalized repository metadata URLs in `pyproject.toml`.
- Updated quick-start documentation with editable install, pytest, smoke test, and desktop UI build commands.
- Reframed README and roadmap around a Task Runtime foundation instead of a feature/tool checklist.
- Reframed the public architecture around Task Runtime, Context Runtime, and Capability Runtime.
- Moved planning/stage policy out of inline runner branches so `conversation_runner.py` can stay closer to orchestration.
- Improved streaming chat reconciliation to avoid duplicate submissions and preserve reasoning/process history during final message replacement.
- Distinguished resumable partial tool output from hard failures in task records and run results.
- Extended `ToolSpec` with capability metadata so tools can declare artifacts, long-running behavior, retry safety, and idempotency.
- Clarified cross-platform shell guidance: portable tasks should prefer `command` plus `args` over platform-specific shell syntax.
- Shifted task routing toward Task Contract First: the model proposes task semantics, while the runtime enforces schema, local safety overrides, and completion evidence.
- Tightened code verification semantics so directory/existence checks no longer count as tests; `RunResult` now records `test_successes` and flags `test_not_observed` when code is written without a real test/build/check.
- Added Verification Runtime guards for long-running service commands so `python -m http.server`, `npm run dev`, and similar commands are not treated as ordinary post-write verification.
- Adjusted RunResult severity for successful writes with invalid verification methods from hard failure to partial, with explicit `invalid_verification_method` and `runtime_verification_not_observed` risks.
- Made model task-contract decisions context-aware for short follow-up requests instead of automatically routing them as isolated chat.
- Added protocol-level correction and final-output cleanup for malformed or parameterless textual tool-call markers.
- Split planning policy from execution confirmation policy. Planning now uses `off` / `auto` / `always`, while confirmation uses `conservative` / `auto` / `aggressive`.
- Validate required tool inputs before requesting manual confirmation, so parameterless writes cannot enter the confirmation flow.
- Replace partial-run model narration with a deterministic final answer based on `RunResult`, and discard pre-tool narration from the final assistant message.
- Stabilized the streaming confirmation bar so long status text no longer changes action-button height.
- Added a conversation-level execution-confirmation selector and live waiting status that distinguishes connection heartbeat, recent progress, and repeated tool failures.
- Simplified the convergence contract: identical tool failures now stop and record the real failure directly instead of injecting another model strategy-change prompt.
- Reduced soft runtime steering by making execution-stage prompts status-only and limiting malformed/dangling/progress correction prompts to one retry.
- Shifted planning, progress, write-repair, duplicate-read, and post-write nudges toward reminder/audit events instead of additional model-facing strategy prompts.
- Count verification evidence only after the latest successful write, and finalize once write and verification success conditions are both met.
- Bumped panel asset versions so the conversation-level execution selector loads its matching JavaScript and CSS instead of stale cached assets.
- Added a text-artifact integrity guard that rejects clearly truncated full HTML overwrites and prevents incomplete HTML reads from satisfying verification.
- Added a Context Hygiene layer that cleans polluted model history before execution while preserving visible conversation history and audit records.
- Tightened HTML/code verification so escaped HTML documents and truncated previews no longer make a code-writing run look successful.
- Reject malformed, non-object, or provider-truncated tool arguments instead of repairing and executing incomplete state-changing calls.
- Preserve model-provider `finish_reason` in run metadata so output-limit truncation is visible and auditable.
- Reframe task contracts as model-declared, revisable task interpretations; deliverable paths are hints while the runtime audits execution evidence and truthfulness.
- Added transactional `code.apply_patch` as the preferred incremental code-writing capability, with full-patch validation, PathGuard enforcement, backups, multi-file audit paths, and confirmation details.
- Added provider-neutral, optional model output-budget declarations (`max_output_tokens` plus `output_token_param`) without guessing unsupported API parameters; low-level request options remain available as overrides.
- Web tasks now prefer controlled asset/capture tools for website redesign, archival, screenshot, and PDF-export requests instead of asking the model to generate crawlers or oversized file writes.
- Large HTML/code/config generation now routes through text artifact drafts instead of a single oversized `filesystem.write_file` call when the artifact may exceed model output limits.
- Capability providers now expose their implementation source. MCP-sourced
  tools remain outside model context until their service is protocol-connected,
  while the plugin catalog remains a capability view rather than a service
  lifecycle manager.
- External-state capability runs are audited from tool effect facts instead of
  being forced through the local file-write contract. MCP tool failures now
  degrade individual binding health, and oversized provider logs are truncated.
- Runtime run history now writes to `runtime.db` transactionally instead of
  rewriting the full `runs.json` document for every event. Existing
  `runs.json` data is imported once and retained as a migration snapshot.
- Follow-up task contracts now preserve a semantic continuity anchor for
  continued/revised work, preventing an implementation fallback from replacing
  the user's original target.
- Deliverable paths now default to soft hints. Same-kind alternative paths can
  satisfy the task contract and are recorded as audit deviations; explicit
  `path_policy=exact` remains available for strict path requirements.

### Known Gaps

- API token enforcement and CORS tightening are still planned security hardening tasks.
- The external plugin manifest and loader are not yet implemented.
- Full Tauri package builds require the platform-specific Rust, WebView, Node, and Python sidecar toolchain.
