# AGENTS.md

Guidance for AI coding agents and contributors working on YuntaoCode.

YuntaoCode is an open-source, local-first AI Task Runtime. The main value of
the project is not a single chat UI or a large tool list, but a clear
foundation for task state, planning, execution, verification, audit, recovery,
context, memory, tools, and local execution. Changes should make that
foundation easier to understand, test, and extend.

## Project Priorities

1. Keep the Task Runtime architecture clear and extensible.
2. Preserve local-first security boundaries.
3. Prefer small, testable changes over large rewrites.
4. Keep user-facing behavior stable unless the change explicitly improves it.
5. Document new extension points when adding them.
6. Prefer strengthening Task state, trace, recovery, and audit over adding new
   application scenarios.

## Architecture Map

- `runtime/conversation_runner.py`
  - Orchestrates one model/tool run.
  - Avoid adding new policy branches here when a pure helper can own the rule.
- `runtime/run_execution_state.py`
  - Owns mutable cross-round lifecycle facts such as round budgets, model
    transport counters, guidance resets, completion review, and one-response
    runtime notices that must not become durable model history.
  - It must not classify task intent, select tools, or become a hidden planner.
- `runtime/tool_call_loop.py`
  - Owns provider-facing model-round streaming facts: deltas, heartbeats,
    tool-call chunks, request budgets, provider errors, and interruption.
  - It must not decide task intent, tool routes, completion, or verification.
- `runtime/model_harness.py`
  - Owns model/provider transport adaptation before one model round is sent:
    request shape, tool payload compatibility, multimodal fallback, and
    provider-facing harness facts.
  - It must not infer user intent, select tools, choose capability routes, or
    decide whether a Run is complete.
- `runtime/model_calls.py`
  - Owns the lifecycle of auxiliary non-streaming model requests: purpose,
    timeout, heartbeat, cancellation, and audit events.
  - It must not interpret model output or decide task, plan, tool, verification,
    or completion semantics.
- `runtime/tool_execution_batch.py`
  - Executes one model-proposed tool-call batch, preserves provider response
    ordering, and returns explicit execution bookkeeping state.
  - It must not select tools or reinterpret the task contract.
- `runtime/user_guidance.py`
  - Owns user-authored guidance queued while a Run is active.
  - It must not become a hidden planner, task router, or runtime intervention
    strategy.
- `runtime/run_finalizer.py`
  - Owns post-loop RunResult construction, recovery checkpoints, final-answer
    presentation, assistant-message persistence, and the terminal done event.
  - It must not decide whether execution should continue or choose a task,
    tool, provider, or verification strategy.
- `runtime/agent_strategy/`
  - Owns agent runtime strategy.
  - `classifiers.py`: tool facts and protocol helpers;
    it must not infer user intent or execution routes.
  - `convergence.py`: repeated execution evidence from observed tool results;
    it must not stop a Run, choose a replacement route, or decide completion.
  - `conversation_task_context.py`: recent-conversation detection and task
    candidate access. It must not infer intent, write mode, document scope, or
    output-length goals from historical keywords.
  - `context_hygiene.py`: model-context cleanup before execution; keeps noisy
    history from becoming examples for the model.
  - `context_noise.py`: pure classification and summaries for historical
    tool-call markup, failure logs, and process-log noise.
  - `model_context_boundary.py`: model-facing boundary notices and historical
    task-lineage markers. It should not classify intent or decide task
    strategy.
  - `project_context.py`: Active Focus snapshots that keep task relation and
    working-object relation independent. It must not infer a focus from
    keywords or copy a historical task goal into a new task.
  - `tool_result_risks.py`: converts tool-result facts into non-blocking,
    model-facing risk evidence and audit records.
  - `profiles.py`: internal assistant profiles such as chat, analysis, coding,
    document, and paper workflows.
  - `policy.py`: request routing and deterministic planning gates.
  - `prompts.py`: factual advisory, recovery, verification, and finalization
    prompt construction.
  - `plan_tracker.py`: execution plan lifecycle helpers.
- `runtime/core/`
  - Owns product-level runtime schemas.
  - `task.py`: Task, Plan, Step, and state transition contracts.
  - `experience.py`: Experience Sample and Experience Digest contracts extracted
    from reviewed Runbook evidence.
  - `replay_fixture.py`: passive Replay Fixture records derived from selected
    Runbook evidence. This is not a plugin loader and must not register
    AI-generated code.
- `runtime/api/`
  - Tornado API handlers and streaming endpoints.
- `runtime/tool_event_presentation.py`
  - Owns tool progress snapshots, frontend output previews, and compact
    tool payloads sent back into the model context.
- `runtime/persistence.py`
  - Owns shared mechanics for the current document-file backend.
  - Store classes remain the runtime-facing repository boundary; do not add
    direct operational-data file reads in API, strategy, or runner code.
- `runtime/run_repository.py`
  - Owns JSON compatibility and SQLite persistence for Run/RunEvent history.
  - Keep lifecycle and event-driven state transitions in `RunStore`, not SQL.
- `runtime/skills/`
  - Local tools. Keep file, shell, Git, and export boundaries explicit.
- `providers/`
  - Incubating provider packages that should stay runtime-agnostic where
    possible. YuntaoCode should consume them through thin adapters such as
    `runtime.skills.desktop`, so they can later become CLI, HTTP, MCP, or
    standalone packages.
  - `desktop_observation/`: read-only local desktop observation. It may produce
    `desktop_state.v1` and `visual_evidence.v1`; it must not introduce click,
    typing, hotkey, focus, window control, or process-control behavior.
- `mcp-services/`
  - External MCP service source/reference trees and service-specific notes.
  - Do not treat files here as built-in `runtime.skills.*` modules or
    auto-loaded plugins.
- `runtime/panel/`
  - The current product UI. It is vanilla JavaScript by design for now.
- `desktop-shell/`
  - Desktop wrapper. The Python runtime should still work independently.
- `docs/`
  - Architecture, plugin, and protocol notes for contributors.
  - `README.md`: documentation map and placement rules.
  - `task-model.md`: task, plan, step, trace, recovery, and template direction.
  - `model-harness.md`: model transport adaptation boundary; use it for
    provider/model quirks instead of adding policy branches to the runner.
  - `run-artifacts.md`: shared temporary artifacts across ToolTasks in one Run.
  - `persistence-model.md`: operational data boundaries and SQLite direction.
  - `experience-runtime.md`: Experience Sample / Digest layer for reviewed Run
    evidence.
  - `evaluation.md`: local evaluation records for selected task fixtures; not a
    standalone benchmark product.

## Task Runtime Rules

- Treat tools as capabilities used by tasks, not as the product architecture.
- Keep capability providers, MCP services, prompt-methodology Skill Packs, and
  Runtime features separate. Do not register a new default `runtime/skills/`
  module unless it satisfies the built-in capability standard in
  `docs/capability-runtime.md`.
- New work should clarify one of: Task Model, lifecycle, trace, recovery,
  verification, template, or tool capability boundaries.
- Replay and experience work should stay passive and evidence-backed. It must
  not make AI-generated code executable in the trusted runtime by default.
- Evaluation work should start from selected task fixtures and RunResult
  evidence. Do not add automatic task collection, remote upload, or public
  leaderboard behavior without an explicit product and privacy design.
- Do not add a new scenario by hard-coding another branch in the runner.
- A task-oriented change should include tests for state transitions, plan/step
  behavior, tool result handling, or recovery behavior.
- Keep task events understandable enough for a user to audit what happened and
  precise enough for tests to assert.

## Agent Runtime Rules

- The UI exposes one unified terminal. Do not reintroduce user-facing assistant
  modes unless there is a product decision to do so.
- Internal profiles belong in `runtime/agent_strategy/profiles.py`.
- Plan and routing decisions belong in `runtime/agent_strategy/policy.py`.
- Profiles describe model task contracts. Do not turn them into fixed stage
  sequences, tool routes, or profile-specific round budgets.
- Model-context cleanup belongs in `runtime/agent_strategy/context_hygiene.py`.
  Do not remove visible chat history to fix model pollution; sanitize only the
  model-facing context and keep audit records intact.
- Historical noise classification belongs in
  `runtime/agent_strategy/context_noise.py`; boundary wording and task-lineage
  markers belong in `runtime/agent_strategy/model_context_boundary.py`.
  Keep both layers advisory and model-facing. They must not become hidden task
  routers or blockers.
- Follow-up task inheritance belongs in
  `runtime/agent_strategy/conversation_task_context.py`; API handlers should
  not reimplement previous-task scanning rules.
- Tool result previews and model-facing tool payload compaction belong in
  `runtime/tool_event_presentation.py`.
- Prompt text belongs in `runtime/agent_strategy/prompts.py`.
- Plan lifecycle changes belong in `runtime/agent_strategy/plan_tracker.py`.
- Keep extracted strategy helpers pure when possible. Avoid filesystem,
  network, Tornado request, or model-provider dependencies in these helpers.
- Add focused tests for every new classifier, policy, profile, prompt, or plan
  tracker behavior.

## Safety Rules

- Default runtime access is local: `127.0.0.1` plus configured workspace roots.
- Do not bypass `PathGuard`, write confirmation, shell confirmation, Git
  confirmation, or export confirmation flows.
- Do not add broad filesystem or shell access without an explicit permission
  model and tests.
- Do not commit API keys, local conversation data, user files, generated
  packages, or `node_modules`.
- Token enforcement and CORS hardening are known pre-1.0 work items. Changes in
  this area should include tests and update `SECURITY.md`.

## Cross-platform Rules

- Runtime core paths, settings, task state, run history, attachments, memory,
  tool registration, HTTP APIs, and the vanilla frontend should work on
  Windows, macOS, and Linux.
- Built-in tools should prefer cross-platform Python and `pathlib` behavior.
  Shell tools should prefer `command + args` and must not assume PowerShell,
  bash, `cp`, `rm`, `Copy-Item`, or platform package managers are available.
- Platform-specific adapters are acceptable for optional capabilities such as
  opening folders, Office/LibreOffice conversion, browsers, desktop shell, and
  MCP binaries, but missing dependencies must degrade only that capability and
  return a clear diagnostic.
- New default `runtime/skills/` capabilities should document cross-platform
  behavior or explain why they are platform-specific optional capabilities.

## Frontend Rules

- Preserve the streaming contract: user message, run event, status/heartbeat,
  reasoning/content deltas, tool events, final replacement, and done/error.
- Prevent duplicate submissions for a single composer action.
- Keep reasoning, process history, and final answer metadata available in the
  message state.
- Vanilla JavaScript is acceptable at the current stage. If splitting files,
  prefer feature modules over introducing a framework without a broader UI plan.
- After frontend changes, run syntax checks and manually verify the main chat
  flow when possible.

## Tests And Validation

Run the checks that match your change:

```bash
python scripts/sync_release_version.py --check
python scripts/check_doc_encoding.py
python scripts/check_01_readiness.py
pytest
python -m py_compile runtime/api/conversations.py runtime/conversation_runner.py runtime/run_execution_state.py runtime/tool_call_loop.py runtime/tool_execution_batch.py runtime/run_finalizer.py
node --check runtime/panel/static/panel.js
node --check runtime/panel/static/i18n.js
```

For strategy changes, run:

```bash
pytest tests/test_agent_strategy.py
```

For desktop shell changes, run:

```bash
npm --prefix desktop-shell run build:ui
node --check desktop-shell/src/main.js
powershell -ExecutionPolicy Bypass -File scripts/prepare_tauri_check.ps1
cargo check --manifest-path desktop-shell/src-tauri/Cargo.toml
```

## Documentation

Update the relevant docs when behavior or extension points change:

- `README.md` / `README.en.md` for public-facing usage and architecture.
- `docs/architecture.md` for runtime architecture decisions.
- `docs/context-runtime.md` for Context Runtime boundaries, model-context
  hygiene, task lineage, snapshots, memory scope, and Context Pack direction.
- `docs/document-encoding.md` for UTF-8 documentation rules and encoding
  checks.
- `docs/plugin-system.md` for plugin direction.
- `docs/versioning.md` for product release version synchronization and
  independent compatibility-version boundaries.
- `SECURITY.md` for boundary or permission changes.
- `CHANGELOG.md` for user-visible changes.

Documentation files should be UTF-8 without BOM. On Windows PowerShell, read
Chinese documentation with `Get-Content <path> -Encoding UTF8`; do not assume a
document is corrupted just because default terminal decoding shows mojibake.

## When In Doubt

Prefer making the runtime easier to reason about. A contribution that extracts a
policy into a tested helper, clarifies a boundary, or documents an extension
point is often more valuable than adding another feature on top of unclear
foundations.
