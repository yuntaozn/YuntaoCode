# Changelog

All notable changes to YuntaoCode will be documented in this file.

The format follows Keep a Changelog style, and this project uses pre-1.0 semantic versioning while APIs are still evolving.

## [Unreleased]

### Added

- Active Focus snapshots in Context Runtime, separating new/continued task
  actions from inherited/switched project, subproject, file, artifact, or
  external-state focus without turning historical goals into hidden routing.

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
- Runtime-owned capability preflight and per-run capability snapshots. New runs
  use `capability_preflight.v2`, which reports readiness issues, preferred
  tools, visual verification tools, and advisory route hints without turning
  provider fit into hidden execution locks.
- `RunResult` now separates target deliverable paths from observed local writes
  so optional model-initiated repairs are auditable without turning the task
  contract into an execution lock.
- Optional model-initiated local writes without observed verification now emit
  `optional_write_not_verified` and an execution notice while preserving the
  model's chosen strategy.
- Run-level pause/resume actions, deterministic Runbook generation, and Replay
  Request artifacts for 0.1 recovery/audit foundations.
- Product-level Task persistence with explicit Task/Run/ToolTask boundaries,
  Run lineage, recovery Checkpoints, Context Snapshots, prepared Replay Runs,
  and a task-history UI for pause/resume/Runbook/replay actions.
- Workspace-scoped memory boundaries so model context receives only global
  user-level memories plus memories from the current workspace.
- Task contracts can distinguish local file writes from broader observable
  state changes, including external application state.
- Capability and MCP tool contracts can declare successful `effects`, task
  `roles`, and artifact kinds for provider-neutral result auditing.
- Shared atomic JSON persistence mechanics and an indexed SQLite Run/RunEvent
  repository with one-time legacy `runs.json` import.
- `preview.interact_page` for generic Playwright-backed page interaction
  verification, returning screenshot, DOM text, interaction trace, visual
  evidence, and debug-session facts for RunResult.
- `preview.capture_file` as a generic visual observation entrypoint for
  workspace files: HTML delegates to browser preview, images become visual
  evidence, PDFs render page screenshots when PyMuPDF is available, and
  unsupported formats return structured diagnostics.
- A visual-context bridge that can feed eligible screenshot/image evidence back
  into the next model round when the selected model allows vision input, while
  recording the injected evidence for audit.

### Changed

- Context continuity now keeps runtime-observed history as candidate evidence
  without replacing a specific current model goal with the previous goal.
  Successful no-op code edits are rejected as correctable tool failures, and
  verification prompts distinguish earlier attempts from evidence gathered
  after the latest state change.
- Shell ToolTasks now stream bounded stdout/stderr into live tool logs, emit
  heartbeats while silent, preserve those logs in the conversation process
  record, and terminate child process trees when a stopped Run cancels the
  tool. Dependency-install commands use a longer default timeout while
  explicit timeouts and the existing confirmation policy remain authoritative.
- Tool availability now combines Python dependency checks with optional
  runtime readiness probes. Browser-backed capabilities distinguish the
  Playwright package from its managed Chromium binary, expose degraded or
  unavailable reasons to capability preflight, and include those facts in
  diagnostic exports.
- Multi-artifact RunResult verification now preserves structural evidence for
  the latest successful write of each target path instead of discarding
  earlier files when a later deliverable is written.
- Scoped composer submission, send-button, and streaming-status state to the
  current conversation so separate conversations can run in parallel without
  occupying each other's controls.
- Made RunResult convergence role-aware: blocking, degraded, incidental, and
  recovered failures are audited separately, while verification evidence now
  carries weak/standard/strong strength instead of a boolean-only signal.
- Exposed visual verification tool options in capability preflight and Context
  Pack facts so HTML/UI tasks can discover preview and interaction evidence
  tools without forcing a fixed execution route.
- Preserved user and runtime visual image parts in OpenAI-compatible Responses
  requests, and estimated image data URLs as bounded placeholders instead of
  counting embedded base64 as prompt text.
- Model configs now default vision input support to enabled, with an explicit
  settings-page toggle for disabling image input on text-only providers.
- Runtime intervention governance now carries non-blocking guard advisories as
  `runtime_risks`, and document/verification/capability hints use advisory
  wording instead of route-blocking language.
- Verifier retry prompts now include observed and missing verification
  modalities plus available visual verification tools, giving the model
  clearer evidence facts without forcing a fixed route.
- Run finalization now uses a pure evidence gate so missing required
  verification evidence keeps tools available instead of letting
  post-deliverable convergence enter final-answer mode too early.
- Context Runtime task lineage candidates now carry runtime-observed target,
  changed, and verified paths and rank recent real target artifacts ahead of
  failed read-only verification attempts, reducing stale continuation context.
- Verification-only runs now evaluate task-level evidence directly instead of
  requiring a newly written deliverable first, so read-only validation tasks
  can continue until required evidence modalities are satisfied.
- Preview tools now return runtime diagnostics and DOM snapshots for browser
  console errors, page errors, failed requests, visible loading states, and
  local HTML remote dependencies so models can debug visual failures from
  evidence instead of guessing.
- Preview verification now records key document/script/style resource response
  facts and feeds runtime diagnostics into verifier retry prompts, helping the
  model continue from browser evidence after a failed visual check.
- `preview.interact_page` now recovers brittle text clicks by falling back to a
  visible clickable DOM target, while preserving the original Playwright error
  and click strategy in interaction evidence.
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
