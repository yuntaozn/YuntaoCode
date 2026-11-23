# Changelog

All notable changes to YuntaoCode will be documented in this file.

The format follows Keep a Changelog style, and this project uses pre-1.0 semantic versioning while APIs are still evolving.

## [Unreleased]

### Fixed

- Frontend Run polling now reconciles a locally open stream with the sealed
  backend Run state, recovering persisted final text and process metadata when
  the end event is lost. It closes only the local receiver, releases pending
  state and timers, and cannot clear a newer stream in the same conversation.
  Panel pages now use content-hashed static URLs so cached older JavaScript
  does not survive a frontend update behind a fixed version parameter.
- Historical conversation images can now be read on demand through the
  discoverable `attachment.read_image` capability. Image reads share the
  existing conversation ID boundary and 10 MiB upload limit, and return original
  pixels through the normal visual-context bridge. History keeps attachment
  metadata without automatically resending image bytes. Attachment catalogs
  no longer recommend text extraction, and image/text mismatches return factual
  errors. Tool discovery favors more complete lexical matches so a new image
  reader does not displace matching file tools.
- Active model streams no longer stop at a fixed 300-second total deadline.
  Connection and idle limits remain bounded; incoming SSE bytes, including
  keepalives and partial frames, reset the idle clock. Background HTTP timeouts
  and other request exceptions now reach the normal error/finalization path
  instead of disappearing as an empty response. Idle diagnostics report the
  effective limit without retry advice, and consumer cancellation still cleans
  up the background fetch.
- Removed progress-based round-budget extensions. All model-selected tasks and
  tool outcomes now share one fixed resource limit of 120 rounds, preserving the
  previous absolute ceiling without a task-dependent gate at round 40. Provider
  errors, HTTP errors, and exhausted idle-timeout retries now save RunResult,
  recovery checkpoints, and assistant messages through normal finalization.
  Original transport errors and any existing writes are retained; the transport
  loop no longer decides finalization based on prior tool evidence.
- Chinese tool queries now match character pairs and rank lexical overlap by
  catalog frequency. Word-order differences such as querying file reading
  against a description phrased as reading files no longer hide real tools;
  discovery still runs only on the model's explicit query.
- Successful Runs no longer leave Tasks paused when the model omits the optional
  completion declaration. Explicit incomplete declarations remain open and are
  retained as current-attempt facts without leaking into retries. Published
  results and user stops survive event pruning and restart; finalization waits
  for a user pause to be resumed before publishing the result. Repetition audit
  records no longer include generated next-step recommendations.
- Tool-attempt errors now return factual failures without recommended actions
  or unsolicited tool lists. Repeated protocol errors return their actual code
  instead of entering a one-retry repair gate; model tool choices remain under
  the normal permission, protocol, and resource boundaries.
- Main-model final answers are preserved, including JSON examples and trailing
  text. Removed implicit completion-header parsing, secondary answer synthesis,
  task-preflight service startup, and automatic changed-file footers. Shell
  failures retain actual exit codes and stderr without generated replacement
  commands; recovery snapshots report historical state without route advice.

- Removed per-call capability-route, document-coverage, and verification-method
  advisories, including duplicate advisory-to-risk projection. Tool risks now
  carry observations without recommended actions or replacement tools, while
  preserving diagnostics, external side-effect uncertainty, and original
  permission and confirmation checks.
- Free-text tool discovery now ranks query matches instead of taking the first
  alphabetical entries. Model queries for file read/write no longer bury those
  tools behind patch and document-draft definitions.

- Initial model requests now carry one tool-discovery definition instead of
  the full tool catalog. Models explicitly search/load original schemas;
  newly connected MCP tools appear on discovery, and normal execution guards
  remain in force. Duplicate context ledgers, workspace snapshots, capability
  catalogs, and workflow appendices no longer inflate the system prompt.
  Production-request regressions cover greeting overhead, file write/read,
  external-tool dispatch, availability, permissions, and optional task updates.

- Removed pre-execution planning, plan-following prompt injection, generated
  fallback steps, automatic tool-to-step matching, and unused task-judgment
  entrypoints. Legacy planning settings cannot re-enable these paths. Chat,
  settings, and automation screens no longer expose planning-policy controls.
  Optional model-authored progress remains auditable and can be cleared.

- Run result evaluation now has one owner instead of repeated API contract
  checks. Missing delivery evidence stays partial rather than becoming a
  failure; model completion claims, execution, and verification remain separate.
  Optional task bookkeeping no longer downgrades successful tool execution.
- Repeated failures, reads, and write recovery no longer inject extra system
  strategy prompts. Task updates can send only changed fields, including a
  completion-only update, while permission and protocol checks remain enforced.

- MCP inline images now reach the main model as image attachments instead of
  serialized base64 text. Audit records preserve source references, bounded
  pixel observations, and actual transport receipt or fallback without claiming
  visual review passed. Failed external calls explicitly retain uncertainty
  about partial side effects and rollback.

- Rejected stream requests no longer persist user messages or strand conversation
  reservations. Setup cancellation releases ownership, and disconnected streams
  keep background runs controllable until execution ends.
- Finalized Runs retain late events as audit envelopes without reopening Tasks
  or replacing published results. Explicit stops survive late tool results and
  duplicate finalization.
- Invalid structured call indices and malformed provider chunks reject the
  complete round batch with bounded protocol recovery. Task declarations use
  their advertised schema and reject invalid nested requirements atomically.

### Added

- Run results separate execution termination, goal completion, and verification.
  Undeclared or unclosed goals remain unconfirmed instead of inheriting success
  from a tool probe. Native task declarations can record completion and plan
  progress with checked references to observed tool tasks.
- Tool evidence is independent of frontend previews, preserving complete path
  and diagnostic arrays while referencing inline media through the original
  ToolTask. Main-model rounds now have durable protocol summaries without
  duplicating prompt or reasoning text.
- Task storage enforces state transitions and current-attempt ownership;
  terminal task replays create linked new Tasks. Text-call compatibility is
  explicit per model/provider, excludes reasoning and prose examples, and
  leaves ordinary answer content intact.

- The disabled Blender MCP example now selects the official Blender Lab server
  from a versioned source, with matching inspection and screenshot policies.
  Existing connections keep their provider until explicitly migrated. Generic
  MCP stdio reads support bounded image responses above 64 KiB, and official
  render-to-path tools retain write confirmation despite upstream read-only hints.

- End-to-end scripted Run scenarios around the real
  `ConversationRunExecutor`, `ToolCallLoop`, `ToolExecutionBatch`, and
  `RunFinalizer`, covering verified completion and model-selected route
  recovery without replacing the runtime with a second test-only loop.
- Observable lifecycle records for auxiliary non-streaming model calls,
  including result synthesis, with
  purpose, timeout, heartbeat, cancellation, and audit events without
  exposing prompts or turning transport failure into a task verdict.
- Runs now enter the main execution model without a separate task-contract
  interpretation call. Optional `runtime.update_task` declarations record task
  and plan state inside the same model/tool loop, without granting permissions
  or counting as executed deliverables.
- User guidance preserves its original text without rejudging the task or
  automatically interrupting plans. Recent user requests and assistant promises
  retain their roles; answer-only turns remain available as lineage evidence.
- Arbitrary Blender code execution no longer implies a delivered artifact or
  observed external-state change. Existing preset success claims are migrated
  conservatively while retaining confirmation and connection configuration.
- Model rounds ending with `tool_calls` without a usable call now receive one
  bounded protocol retry and report an error if the payload remains missing,
  instead of treating earlier successful reads as task success. Result
  synthesis also correctly adapts settings to the auxiliary-call interface.

- Auditable memory selection in Context Runtime: relevant global/workspace
  memories now enter task-contract and planning Context Packs with source IDs,
  trust, freshness, and workspace scope instead of being hidden in the base
  system prompt.
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

- Model settings now accept an OpenAI-compatible address and optional key in the add-model form. Models can reuse a saved connection, and advanced model options are available in the editor.
- The main execution loop no longer inserts automatic completion self-review
  rounds. Completion remains with the execution model, while missing evidence
  stays visible in RunResult and recovery records. Write-task round budgets now
  extend only for material progress, repeated read-range notices are one-shot,
  and a synthesized final answer is included before final status is frozen.
  Result synthesis receives an answer-independent execution snapshot, avoiding
  false failure wording caused solely by the not-yet-generated final answer.
  Obsolete completion-review state, API prompt plumbing, and strategy gates
  have been removed; legacy model-declared assessments remain passive audit
  input only.
- Built-in ToolSpec registrations now provide complete capability and task-role
  metadata. Tool events persist declared artifacts separately from observed
  artifacts, and role classification uses provider contracts while isolating
  tool-ID rules to historical-event compatibility.

- Windows sidecar builds are consoleless by default from every supported build
  entry point; console builds now require an explicitly named diagnostic
  command. Browser-native confirmation windows were also replaced by one
  shared in-app dialog across the panel.

- A valid final answer from the execution model remains the canonical
  user-facing answer even when `RunResult` is partial, failed, or stopped.
  Result synthesis is now reserved for missing or protocol-invalid final
  content; evidence status and risks remain separate audit facts.
- Runtime repair, convergence, and read-range notices now
  have a one-response model-context lifecycle. A successful model response
  consumes them, while transport errors retain them for retry, preventing stale
  execution advice from accumulating across later routes and final review.
- The model's observable choice remains authoritative for loop control: tool
  calls continue execution, while an ordinary final answer ends the loop.
  Runtime verification gaps stay in `RunResult` and audit evidence.
- Legacy model-declared `completion_self_assessment.v1` headers remain
  passively readable. `RunResult` preserves Runtime evidence status separately
  and does not let a model declaration upgrade missing evidence.
- Conversation persistence now keeps bounded summaries of Context Packs and
  capability evidence instead of duplicating the full RunEvent audit payload in
  every assistant message.
- Main development now targets `0.2.0-dev` after the fixed `v0.1.0` public
  preview tag. The 0.2 direction is anchored around Observation, Verification,
  and Artifact Runtime rather than a broader tool or scenario list.
- Provider-facing model-round streaming now runs through a dedicated
  `ToolCallLoop` boundary. It records deltas, heartbeats, request budgets,
  tool-call chunks, provider errors, and runtime-guidance interruption without
  choosing task semantics or execution routes. A first idle timeout now
  performs the retry already described by the UI; a second consecutive timeout
  stops the run.
- Model-proposed tool calls now run through a dedicated `ToolExecutionBatch`
  boundary with explicit recon, write-repair, and read-range state. All tool
  responses in a batch are appended before runtime recovery advisories, keeping
  provider tool-call message ordering valid without constraining model choice.
- Post-loop result handling now runs through a dedicated `RunFinalizer`
  boundary. It builds RunResult and recovery evidence, persists the final
  assistant message, and publishes the terminal event without deciding task
  strategy or whether the model/tool loop should continue.
- Cross-round lifecycle facts now live in an explicit `RunExecutionState`
  instead of scattered runner locals. Round budgets, guidance resets,
  transient model-context notices, and transport counters
  share one tested state contract that does not choose model strategy. Repeated
  execution evidence remains a pure `ExecutionConvergence` concern.
- Removed an unreachable target-deliverable-gap prompt path and its unused
  strategy-change classifier instead of carrying dead intervention policy into
  the new lifecycle state.
- Desktop sidecar build dependencies now use the `pyproject.toml` `build`
  optional dependency group; the duplicate `requirements-build.txt` entrypoint
  has been removed.
- Windows desktop sidecar builds now use an isolated Python environment, clean
  stale outputs before packaging, stop on native command failures, and keep
  cargo-check placeholders out of the release build path.

- Context compression now validates cached summaries against a digest of the
  durable source-message prefix instead of reusing an index into dynamically
  sanitized history. Model-facing task-lineage facts preserve all bounded
  candidates, Active Focus and task facts precede broad workspace context, and
  execute-style follow-ups no longer bypass model task-contract judgment.

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
- Completion evidence packs preserve observed and missing verification
  modalities, visual/debug evidence, tool failures, and risks for audit and
  finalization without driving a verifier-retry control path.
- Removed the verification-gap counter and tool-disabled final-answer phase.
- Consolidated repeated-execution handling into `ExecutionConvergence` evidence;
  removed the overlapping ProgressObserver counter and obsolete
  `no_progress_budget_exhausted` stop-state path.
  Fresh task evidence remains available to the main execution model without an
  inserted completion-review round; an ordinary answer ends the loop while
  unresolved verification remains visible in RunResult.
- Context Runtime task lineage candidates now carry runtime-observed target,
  changed, and verified paths and rank recent real target artifacts ahead of
  failed read-only verification attempts, reducing stale continuation context.
- Verification-only runs evaluate task-level evidence directly instead of
  requiring a newly written deliverable first, then leave continuation or
  honest evidence-bounded closure to the main execution model.
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
- Stabilized the streaming confirmation bar so long status text no longer changes action-button height.
- Added a conversation-level execution-confirmation selector and live waiting status that distinguishes connection heartbeat, recent progress, and repeated tool failures.
- Reduced soft runtime steering by making execution-stage prompts status-only and limiting malformed/dangling/progress correction prompts to one retry.
- Shifted planning, progress, write-repair, duplicate-read, and post-write nudges toward reminder/audit events instead of additional model-facing strategy prompts.
- Count verification evidence only after the latest successful write, while
  leaving the continue/finalize decision to the main execution model.
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
