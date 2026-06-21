# Automation Runtime

Automation is the trigger layer above YuntaoCode's normal Task Runtime.

It answers one question:

> When should a normal Task be created from a saved user goal?

It must not become a second execution engine. An automation does not call tools
directly, does not bypass permissions, and does not mark work complete by
itself. Every triggered action becomes a normal Task/Run and uses the same
planning, confirmation, trace, verification, recovery, and audit path as a
manually started task.

## Position

```text
Automation
  -> Trigger
  -> Task Template
  -> Run
  -> Run Events
  -> RunResult
```

The boundary is intentionally small for 0.1:

- Automation owns trigger definitions and task templates.
- Task Runtime owns execution and lifecycle state.
- Context Runtime owns what facts enter the model context.
- Capability Runtime owns tool availability, permissions, confirmations, and
  capability health.

## 0.1 Contract

The initial pure schemas live in `runtime/core/automation.py`:

- `Automation`
- `AutomationTrigger`
- `AutomationTaskTemplate`
- `AutomationRun`

Schema versions:

- `automation.v1`
- `automation_trigger.v1`
- `automation_task_template.v1`
- `automation_run.v1`

These schemas are pure data contracts. The current implementation also has a
local `AutomationStore`, `/automations` API handlers, and a configuration page
that can create a prepared normal Run. It still does not start timers, spawn
background processes, call models, or execute tools by itself.

## Trigger Types

The first trigger kinds are:

- `manual`: a saved task template that the user starts explicitly;
- `once`: a one-time scheduled run;
- `interval`: a fixed interval check;
- `daily`: a daily wall-clock run;
- `weekly`: a weekly wall-clock run.

File watchers, OS event monitors, and continuous computer monitoring are
outside the 0.1 boundary. They need a separate privacy, resource, and
cross-platform design.

## Task Template

An automation task template stores the same user-facing execution inputs a
manual task would use:

- natural-language goal;
- workspace;
- model;
- planning policy;
- confirmation policy;
- access scope.

When triggered, the template becomes a normal Run request seed. The scheduler
must not translate the template into direct tool calls.

## Concurrency

The initial concurrency policies are:

- `skip_if_running`: do not create another Run while one is active;
- `queue_next`: allow a scheduler to queue a later Run;
- `allow_parallel`: allow concurrent Runs.

The default should be `skip_if_running`, because most local-first automations
touch a workspace and should avoid overlapping writes.

## Confirmation And Safety

Automation cannot weaken safety boundaries.

If a triggered task writes files, runs shell commands, commits Git changes, or
touches external MCP/application state, the normal confirmation policy still
applies. The user should be able to pause or disable an automation at any time.

## UI Direction

The first UI should be simple:

- automation list;
- enabled/paused state;
- trigger summary;
- workspace and task goal;
- last result and next run;
- actions: run now, pause/resume, edit, delete, view recent Runs.

The UI should not expose a separate "automation result" as if it replaced
RunResult. The authoritative execution record remains the linked Run.

## Not In 0.1

Do not add these until the basic trigger-to-Run chain is stable:

- system-wide watchers;
- remote automation sync;
- automatic remote sample upload;
- arbitrary script hooks;
- hidden background tool execution;
- automatic repair loops outside Task Runtime;
- a second task log separate from Run events.

## Implementation Path

1. Keep the schema pure and tested.
2. Add local persistence through a Store boundary when the UI needs editing.
3. Add API handlers for CRUD and manual trigger.
4. Add a lightweight scheduler that only creates normal Runs.
5. Surface linked Run history and RunResult in the automation UI.
6. Consider OS-level startup or desktop integration only after the local
   scheduler proves stable.
