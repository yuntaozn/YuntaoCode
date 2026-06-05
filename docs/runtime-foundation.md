# Runtime Foundation Contract

This document records the current foundation contract for YuntaoCode as an
open-source Local-First AI Task Runtime.

The goal is to keep the base architecture clear while the project is still in
alpha. New features should build on these contracts instead of adding another
hard-coded branch in the runner.

## Runtime Lines

YuntaoCode should be read as three connected runtime lines, not as a growing
tool list:

- **Task Runtime** owns product-level tasks, plans, steps, trace, recovery,
  verification, and final results.
- **Context Runtime** owns context selection, compression, evidence, memory,
  source/trust boundaries, and context snapshots.
- **Capability Runtime** owns tool capability contracts, permissions,
  confirmations, plugin drafts, external providers, and local execution
  boundaries.

The model may propose task semantics, routing, and next actions. The runtime
owns schema, permissions, state transitions, evidence, and completion checks.

The first pure schema package for these concepts lives in `runtime/core/`.
It intentionally avoids Tornado, model-provider, filesystem, and network
dependencies so API handlers, agent strategy, tools, and UI adapters can depend
on the same foundation.

## Convergence Contract

The runtime should not decide the task strategy for the model, but it must
prevent an execution from repeating the same failed action indefinitely.

The current convergence rule is:

1. The first failure is returned to the model as real tool evidence.
2. A second identical trailing failure triggers a strategy-change
   intervention. The model must choose a materially different next action,
   such as supplying valid parameters, reading minimal missing context,
   choosing another capability, moving to verification, or truthfully
   stopping.
3. If the model receives that intervention and still repeats the identical
   failed action, the runtime stops the loop and records a stopped result.
4. Any materially different tool result or successful action resets the
   repeated-failure sequence.

This contract is deliberately narrower than task planning. It judges whether
execution is converging; it does not hard-code which strategy the model must
choose.

Successful execution also needs convergence. For write-required tasks,
verification evidence only counts when it occurs after the latest successful
write. Once the write and verification conditions are both satisfied, the
runtime moves to finalization instead of continuing to expose an open-ended
write loop.

## Task And ToolTask

YuntaoCode uses two related but different concepts:

- **Task** is the product-level user goal: plan, steps, trace, recovery, and
  final result.
- **ToolTask** is one local tool invocation: a filesystem read, shell command,
  Git operation, document export, and similar actions.

The historical `/tasks` API currently manages ToolTask records. It remains
compatible for now, but public records declare:

```json
{
  "schema_version": "0.1",
  "record_kind": "tool_task",
  "kind": "tool_task",
  "tool_id": "filesystem.scan_folder"
}
```

Future product-level tasks should not overload these tool invocation records.
They should be introduced as a separate Task model or a clearly named store.

## Run Events

Run events are the foundation for trace, audit, replay, and recovery. Persisted
events now include:

```json
{
  "schema_version": "0.1",
  "event": "tool",
  "event_name": "tool.completed"
}
```

The legacy `event` field remains for compatibility with the current frontend
streaming contract. The `event_name` field is the forward-looking, stable event
taxonomy.

Current canonical event names include:

- `run.status`
- `context.hygiene`
- `task.contract`
- `plan.decision`
- `plan.generated`
- `plan.step.updated`
- `tool.started`
- `tool.completed`
- `tool.failed`
- `confirmation.requested`
- `run.changes`
- `run.result`
- `run.completed`
- `run.failed`

## Task Contract

Before a run enters planning or tool execution, the runtime now builds a
`task_contract`.

The intended split is:

- The model judges the task semantics: goal, intent, whether a write is
  required, expected deliverables, first action, blockers, confidence, and
  whether a plan is useful.
- The runtime owns the contract shape, schema version, local security
  overrides, workspace scope, success conditions, and completion checks.

This avoids growing a large keyword router for every scenario. Keyword and
policy heuristics remain only as fallback and safety inputs; they should not be
the main product architecture.

Example:

```json
{
  "schema_version": "task_contract.v1",
  "source": "model",
  "intent": "write_required",
  "goal": "Create an HTML model viewer demo",
  "requires_write": true,
  "requires_verification": true,
  "requires_plan": false,
  "deliverables": [
    {
      "kind": "file",
      "path_hint": "model-viewer.html",
      "description": "A Three.js GLB/GLTF model viewer example"
    }
  ],
  "first_action": "write",
  "success_conditions": [
    "write_tool_success",
    "verification_tool_success",
    "final_answer_with_evidence"
  ]
}
```

The runtime can still override the model contract. For example, a user saying
"only analyze" forces a read-only contract even if the model proposes a write.
Document coverage requirements and local permission boundaries are also
runtime-owned.

## Planning And Confirmation Policies

Planning and execution confirmation are independent policy lines:

- `planning_policy`: `off`, `auto`, or `always`
- `confirmation_policy`: `conservative`, `auto`, or `aggressive`

`planning_policy` controls whether the runtime asks the model to produce and
follow an explicit plan. It does not grant permission to execute tools.

`confirmation_policy` controls the manual confirmation gate after input schema,
workspace, permission, and safety checks:

- `conservative` confirms every state-changing tool call.
- `auto` allows ordinary workspace writes and confirms privileged or unknown
  state changes such as Shell and Git commit.
- `aggressive` allows state changes inside already-authorized boundaries.

Hard guards such as workspace roots, `PathGuard`, disabled tools, and explicit
no-write instructions remain active under every policy.

## RunResult

`RunResult` is the deterministic runtime-owned summary of what happened during
a run. It is generated from tool events and change summaries, not from the
model's final prose.

The model can still write a user-facing answer, but `RunResult` is the source of
truth for:

- successful writes
- failed writes
- changed paths
- verification tool calls
- test/build/check tool calls
- execution risks
- contract failures
- max-round stops

Example:

```json
{
  "schema_version": "0.1",
  "kind": "run_result",
  "status": "partial",
  "counts": {
    "tool_events": 2,
    "write_successes": 1,
    "write_failures": 1,
    "verification_successes": 0,
    "failures": 1
  },
  "risks": ["partial_write_failure", "write_not_verified"]
}
```

For code and HTML/script tasks, directory listings or file-existence probes
such as `dir`, `ls`, `Get-Item`, or `os.listdir` are not treated as tests. They
may help diagnose state, but they do not prove the generated code runs.
`RunResult` distinguishes content-level verification from test/build/check
commands and reports `test_not_observed` when code was written without a
successful test, syntax check, build, or lint command.

Preview reads are not enough to prove a code artifact is runnable. A truncated
`filesystem.read_text_preview` result does not satisfy post-write verification.
HTML artifacts also pass a lightweight integrity check: full-document writes
that are visibly truncated or accidentally escaped as `&lt;html&gt;` text are
rejected before overwrite, and invalid HTML integrity evidence cannot satisfy
verification.

Long-running service commands such as `python -m http.server`, `npm run dev`,
or similar development servers are not treated as ordinary verification
commands. When they appear in a post-write verification context, the runtime
records `invalid_verification_method` and keeps the task result partial instead
of waiting for a server command to time out and treating the whole write as a
hard failure.

Future UI work should prefer showing facts from `RunResult` over inferring task
state from assistant text.

When `RunResult.status` is `partial` or `failure`, the runtime replaces
accumulated model narration with a deterministic, evidence-based final answer.
Intermediate text emitted before a structured tool call is process narration,
not a trustworthy completion claim.

Short follow-up requests should be interpreted against recent task context
before the runtime selects an execution profile. The model proposes whether a
follow-up continues an existing task; the runtime still owns permissions,
required write/verification evidence, and completion status. This avoids
treating concise requests such as an incremental artifact change as isolated
chat messages.

## Context Runtime

Context is a runtime resource, not just chat history. It should track:

- task goals and hard constraints;
- context source and trust level;
- tool-verified evidence;
- summaries and memory;
- unresolved, stale, or unverified facts;
- recovery context after failures.

## Context Hygiene

The conversation UI and run audit keep the full visible history. The model
context is allowed to be cleaner than that history.

Before a run enters model execution, the runtime now applies a context hygiene
pass. This pass is intentionally separate from token-limit compression:

- context hygiene handles polluted history, failed process logs, textual tool
  markers, incomplete artifacts, and recovery facts;
- context compression handles oversized but otherwise trustworthy history.

The current hygiene rule is conservative:

1. Preserve the latest user message exactly.
2. Preserve normal user/assistant history.
3. Collapse older assistant messages that contain failed textual tool-call
   markers or deterministic failure summaries into neutral recovery facts.
4. Keep UI history and persisted run events unchanged.
5. Record a `context_hygiene` report when cleanup happens so future strategy
   changes can be audited and tested.

This layer is expected to evolve. Future work can add task summaries, evidence
snapshots, source trust levels, memory selection, stale fact detection, and
recovery checkpoints without turning the conversation runner into another
policy branch pile.

Initial schemas are defined in `runtime/core/context.py`:

- `ContextRecord`
- `EvidenceRecord`
- `ContextSnapshot`

Design notes live in [context-runtime.md](context-runtime.md).

## Capability Runtime

Tools, built-in skills, future plugins, and MCP servers should enter the task
runtime through capability contracts. A capability contract describes input
schema, permissions, output artifacts, whether a tool is long-running or
retry-safe, and whether confirmation is required.

Initial schemas are defined in `runtime/core/capability.py`:

- `PermissionSet`
- `CapabilityContract`

Design notes live in [capability-runtime.md](capability-runtime.md).

## Temporary Artifacts

One-off analysis scripts, probe files, intermediate JSON, and other files that
should not become project artifacts belong to a task-scoped temporary directory.

The runtime provides that directory to tools through `ToolContext.temp_dir`.
Models should use `filesystem.write_temp_file` for temporary scripts and pass
`cwd="task_temp"` or `use_task_temp=true` to `shell.run_command` when executing
them.

Temporary files are local task artifacts. They must not satisfy a user-facing
write contract, and they should not be reported as project changes. Real project
outputs still need explicit write tools such as `code.edit_file`,
`code.replace_text`, `filesystem.write_file`, or document export tools.

## Compatibility Rules

- Keep the existing streaming contract stable unless a migration path is added.
- Keep `/tasks` compatible until a product-level Task API is introduced.
- Add schema versions to persisted runtime data.
- Add tests when changing event names, result facts, task states, or tool-task
  persistence.
- Do not make AI-created plugins executable in the main Python process without
  a separate isolation and confirmation design.
- Prefer cross-platform tool contracts over shell-specific assumptions. When a
  command must run on multiple platforms, use `command` plus `args` instead of
  embedding shell-specific syntax.

## Next Foundation Work

Recommended next steps:

1. Introduce a product-level Task record separate from ToolTask.
2. Make context snapshots and evidence records available to compression and
   resume flows.
3. Map ToolSpec metadata into CapabilityContract.
4. Persist confirmation requests and outcomes as first-class trace events.
5. Split `conversation_runner.execute()` by controller responsibility.
6. Teach the frontend to display `RunResult` explicitly.
7. Add replay/resume semantics on top of versioned run events.
