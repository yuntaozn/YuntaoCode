# Runtime Foundation Contract

This document records the current foundation contract for YuntaoCode as an
open-source Local-First AI Task Runtime.

The goal is to keep the base architecture clear while the project is still in
alpha. New features should build on these contracts instead of adding another
hard-coded branch in the runner.

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

Future UI work should prefer showing facts from `RunResult` over inferring task
state from assistant text.

## Compatibility Rules

- Keep the existing streaming contract stable unless a migration path is added.
- Keep `/tasks` compatible until a product-level Task API is introduced.
- Add schema versions to persisted runtime data.
- Add tests when changing event names, result facts, task states, or tool-task
  persistence.
- Do not make AI-created plugins executable in the main Python process without
  a separate isolation and confirmation design.

## Next Foundation Work

Recommended next steps:

1. Introduce a product-level Task record separate from ToolTask.
2. Persist confirmation requests and outcomes as first-class trace events.
3. Split `conversation_runner.execute()` by controller responsibility.
4. Teach the frontend to display `RunResult` explicitly.
5. Add replay/resume semantics on top of versioned run events.
