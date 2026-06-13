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
- `runtime/agent_strategy/`
  - Owns agent runtime strategy.
  - `classifiers.py`: intent, tool, progress, and stage classification helpers.
  - `conversation_task_context.py`: follow-up task inheritance from conversation
    history, including previous write/document context and output-length goals.
  - `context_hygiene.py`: model-context cleanup before execution; keeps noisy
    history from becoming examples for the model.
  - `tool_result_risks.py`: converts tool-result facts into non-blocking,
    model-facing risk evidence and audit records.
  - `profiles.py`: internal assistant profiles such as chat, analysis, coding,
    document, and paper workflows.
  - `policy.py`: request routing and deterministic planning gates.
  - `prompts.py`: stage and intervention prompt construction.
  - `plan_tracker.py`: execution plan lifecycle helpers.
- `runtime/core/`
  - Owns product-level runtime schemas.
  - `task.py`: Task, Plan, Step, and state transition contracts.
  - `skill_evolution.py`: Skill Candidate, Replay Fixture, Replay Result, and
    Promotion data contracts. This is not a plugin loader and must not register
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
  - `task-model.md`: task, plan, step, trace, recovery, and template direction.
  - `run-artifacts.md`: shared temporary artifacts across ToolTasks in one Run.
  - `persistence-model.md`: operational data boundaries and SQLite direction.
  - `skill-evolution.md`: Runbook-to-Replay-to-Skill Candidate direction.

## Task Runtime Rules

- Treat tools as capabilities used by tasks, not as the product architecture.
- New work should clarify one of: Task Model, lifecycle, trace, recovery,
  verification, template, or tool capability boundaries.
- Skill Evolution work should preserve the chain Runbook -> Replay Fixture ->
  Skill Candidate -> Replay Result -> manual Promotion, and must not make
  AI-generated code executable in the trusted runtime by default.
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
- Stage sequences and round limits should flow through profiles instead of
  ad-hoc branches in the runner.
- Model-context cleanup belongs in `runtime/agent_strategy/context_hygiene.py`.
  Do not remove visible chat history to fix model pollution; sanitize only the
  model-facing context and keep audit records intact.
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
pytest
python -m py_compile runtime/api/conversations.py runtime/conversation_runner.py
node --check runtime/panel/static/panel.js
node --check runtime/panel/static/i18n.js
```

For strategy changes, run:

```bash
pytest tests/test_agent_strategy.py tests/test_agent_strategy_behaviour.py
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
- `docs/plugin-system.md` for plugin direction.
- `docs/versioning.md` for product release version synchronization and
  independent compatibility-version boundaries.
- `SECURITY.md` for boundary or permission changes.
- `CHANGELOG.md` for user-visible changes.

## When In Doubt

Prefer making the runtime easier to reason about. A contribution that extracts a
policy into a tested helper, clarifies a boundary, or documents an extension
point is often more valuable than adding another feature on top of unclear
foundations.
