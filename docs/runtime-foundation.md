# Runtime Foundation Contract

This document records the current foundation contract for YuntaoCode as an
open-source Local-First AI Task Runtime.

The goal is to keep the base architecture clear while the project is still in
alpha. New features should build on these contracts instead of adding another
hard-coded branch in the runner.

## 0.1 Closeout Principle

YuntaoCode 0.1 is a runtime direction release, not a stability promise and not
a claim that every future scenario is already solved.

The closeout goal is to make the foundation legible:

- the project is a local-first AI Task Runtime, not a tool bundle, chat shell,
  MCP/CLI client, or Skill manager;
- Task, Context, Capability, and Experience are the main architecture lines;
- providers such as built-in tools, CLI, MCP, Capability Packs, and future
  plugins must enter the same Capability Runtime boundary;
- evidence, state, permissions, verification, and recovery must remain more
  important than adding another scenario;
- every near-term change should answer whether it helps 0.1 close out.

If a change does not clarify task state, context boundaries, capability
contracts, evidence, recovery, audit, or the Experience path, it should be
treated as post-0.1 unless there is a direct user-facing defect.

## Runtime Lines

YuntaoCode should be read as a layered runtime, not as a growing tool list.
The three execution-facing lines are:

- **Task Runtime** owns product-level tasks, plans, steps, trace, recovery,
  verification, and final results.
- **Context Runtime** owns context selection, compression, evidence, memory,
  source/trust boundaries, and context snapshots.
- **Capability Runtime** owns tool capability contracts, permissions,
  confirmations, Capability Packs, external providers, and local execution
  boundaries.

Above them is an evidence-learning layer:

- **Automation Runtime** sits above Task Runtime as a trigger layer. It turns a
  saved user goal and schedule into a normal Task/Run, and does not execute
  tools or bypass runtime permissions directly.
- **Experience Runtime** extracts reviewed task experience from Runbook and
  RunResult facts. It prepares selected samples and digests for Replay,
  Evaluation, and future Skill Evolution, but it does not control live task
  execution or make generated code trusted.
- **Skill / Capability Evolution** turns evaluated experience into candidate
  skills, task templates, or capability drafts. It is evidence-driven and must
  not silently register generated code as trusted runtime capability.
- **Self-Iteration Lab** is a future boundary for improving YuntaoCode itself
  through isolated clones, regression fixtures, diagnostics, and human merge
  decisions. It is not direct model self-modification of the trusted runtime.

The model may propose task semantics, routing, and next actions. The runtime
owns schema, permissions, state transitions, evidence, and completion checks.

The first pure schema package for these concepts lives in `runtime/core/`.
It intentionally avoids Tornado, model-provider, filesystem, and network
dependencies so API handlers, agent strategy, tools, and UI adapters can depend
on the same foundation.

Operational persistence is accessed through runtime Store classes rather than
direct file reads. Run and RunEvent history now uses SQLite behind `RunStore`;
the remaining JSON stores and incremental SQLite direction are documented in
[persistence-model.md](persistence-model.md).

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

The `/tasks` API manages product-level Tasks. Individual local tool invocation
records use `/tool-tasks` and declare:

```json
{
  "schema_version": "0.1",
  "record_kind": "tool_task",
  "kind": "tool_task",
  "tool_id": "filesystem.scan_folder"
}
```

Product Tasks are persisted separately from ToolTasks and reference one or more
Runs. Each replay or recovery attempt creates another Run under the same Task.

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

`runtime/run_trace.py` builds a compact `run_trace_summary.v1` view from the
persisted event stream. This is the shared audit surface for Runbook,
diagnostic export, and future Evaluation/Replay work. It does not replace the
stored events and does not include raw tool outputs or file contents; it keeps
event families, canonical names, counts, terminal status, result status, and a
sanitized timeline.

`runtime/run_evidence.py` builds `run_evidence.v1`, the unified fact view for
post-run consumers. RunEvidence gathers the Run metadata, task contract,
trace summary, capability evidence, capability snapshot, plan, tool steps,
completion decisions, result, verification evidence, failures, checkpoints,
recovery summary, and a manual replay seed. Runbook, diagnostic export,
Experience Sample export, Replay, and future Evaluation should consume
RunEvidence instead of each parsing persisted events separately.

RunEvidence is an evidence layer, not a strategy layer. It must not execute
tools, silently promote generated code, alter model context, or decide whether
a future run should retry, replay, or change strategy.

`runtime/run_workbench.py` builds `run_workbench.v1`, the user-facing workbench
view derived from RunEvidence. It presents run status, task contract facts,
artifacts, verification, risks, failures, completion decisions, plan steps,
timeline, capability state, and recovery actions in a compact UI-ready shape.
It is a presentation layer, not a second evidence source; RunEvidence and
RunResult remain the runtime-owned truth.

Current canonical event names include:

- `run.status`
- `run.guidance`
- `run.completion_decision`
- `context.hygiene`
- `capability.snapshot`
- `task.contract`
- `plan.decision`
- `plan.generated`
- `plan.step.updated`
- `tool.started`
- `tool.completed`
- `tool.failed`
- `tool.partial`
- `tool.updated`
- `tool.waiting_confirmation`
- `confirmation.requested`
- `checkpoint.created`
- `run.changes`
- `run.result`
- `run.completed`
- `run.failed`

Lower-level tool-call submission, temporary-file handling, and structured
write protocol details live in [tool-protocol.md](tool-protocol.md). This
foundation document keeps only the product-level Task/Run distinction.

## Pause, Resume, Replay, And Runbook

YuntaoCode 0.1 treats pause/resume/replay as Run-level foundation features.
This keeps them close to the persisted event trace while the product-level
Task store is still being separated from historical ToolTask records.

- `POST /runs/{run_id}/actions` with `{"action": "pause"}` marks the run as
  paused through a persisted `run.status` event with `status="paused"`. The
  active executor pauses at safe boundaries before the next model round or
  tool call.
- `{"action": "resume"}` records `status="resumed"` and releases the active
  executor.
- `{"action": "runbook"}` builds a deterministic runbook from persisted run
  events: task contract, capability snapshot, plan, tool steps, status
  timeline, result, risks, and failures.
- `{"action": "evidence"}` returns the full `run_evidence.v1` view for a Run.
- `{"action": "workbench"}` returns the UI-oriented `run_workbench.v1` view
  built from RunEvidence, so the task history can show artifacts,
  verification, risks, failures, plan steps, and timeline without parsing raw
  events in the frontend.
- `{"action": "export_evaluation_fixture"}` returns a local
  `evaluation_fixture_export.v1` artifact built from RunEvidence. It does not
  execute replay or submit anything remotely.
- `{"action": "evaluate_fixture", "fixture": {...}}` compares the current
  RunEvidence with a selected `evaluation_fixture.v1` and returns an
  `evaluation_report.v1`. It does not execute replay, call a model, call tools,
  or promote skills.
- `{"action": "replay"}` creates a new prepared Run under the same Task and
  returns a replay request artifact. It does not execute tools until the user
  explicitly starts the prepared Run.

Run lineage is explicit through `task_id`, `parent_run_id`, `source_run_id`,
`attempt`, and `resume_from_checkpoint_id`.

Completed or partial Runs persist a recovery `ContextSnapshot` and
`Checkpoint`. A recovered Run receives bounded runtime facts, evidence, and
unresolved risks from the checkpoint instead of replaying the full failed
conversation as instructions.

Runbook and Replay also provide the evidence base for future Experience and
Skill Evolution work. In that path, a Runbook can become an Experience Sample,
selected samples can become Replay Fixtures, a Skill Candidate can be tested
against fixtures, and only replay evidence plus manual promotion can make the
candidate available as a user skill. See [experience-runtime.md](experience-runtime.md)
and [skill-evolution.md](skill-evolution.md).

Completion decisions are completion-loop evidence. After a completion
self-review prompt, the runtime records the model's observable choice: continue
with tools, produce a final-answer candidate, repair malformed tool-call
protocol, or make no observable decision. This event does not force a route; it
exists so the Workbench, Replay, and Evaluation can inspect how a run attempted
to close.

## Diagnostic Export

Diagnostic export is separate from Skill Evolution. It helps compare task
behavior across machines and should be generated only when the user asks for a
specific Run diagnostic package.

The diagnostic package is a compact, sanitized JSON artifact. It may include
runtime version, operating-system and executable availability, sanitized model
and provider settings, tool and MCP capability status, Run summary, compact
Runbook evidence, and recent event summaries. It must not include API keys,
full file contents, full model transcripts, or the complete Runbook/event log
by default.

Diagnostic exports are manual local downloads in 0.1. They are not persisted by
the Runtime and are not submitted to any service.

## Replay And Evaluation Direction

Replay and evaluation are engineering capabilities of YuntaoCode, not a
separate product line in 0.1. They exist to help contributors compare real task
execution across models, providers, runtime versions, prompts, local
environments, and capability availability.

The foundation chain is:

```text
Run
  -> RunEvidence
  -> Diagnostic Export
  -> Experience Sample Export
  -> Replay Fixture
  -> Evaluation Fixture
  -> Evaluation Report
  -> Skill Evolution
  -> Self-Iteration Lab
```

Diagnostic Export is for debugging a specific Run on a specific machine.
Experience Sample Export is for creating a reviewed sample that can later
become a small replayable fixture. Evaluation should compare those fixtures
under controlled runtime or model changes and produce evidence-based reports.
Skill Evolution should only build on that evidence after replay proves a
pattern is stable.

Reusable task templates, Capability Packs, MCP capability bindings, and external
extension contracts are supporting artifacts in this chain. They should not be
described as the product's main roadmap by themselves, because that makes the
project look like a traditional tool/plugin aggregation layer instead of an AI
Task Runtime that can learn from evidence.

The first local fixture shape now exists as `evaluation_fixture.v1`, exported
manually from a selected RunEvidence view. It captures task goal, task
contract, expected artifacts, verification requirements, capability evidence,
baseline counts, and replay seed boundaries. It is not a runner and does not
collect tasks automatically.

The first local report shape now exists as `evaluation_report.v1`. It compares
one selected fixture with one observed RunEvidence view. Result status and
target artifacts are blocking checks; capability drift, verification strength,
verification modality, failure-count drift, and new risks are warning checks.
This keeps reports useful for regression analysis without turning baseline
capability usage into live execution policy.

For 0.1, Experience and Evaluation remain local, manual foundations. There is
no automatic task collection, upload, public leaderboard, central sample
service, automatic fixture execution, or trusted execution of AI-generated
code. Design notes live in [evaluation.md](evaluation.md).

## Task Contract

Before a run enters planning or tool execution, the runtime now builds a
`task_contract`.

The intended split is:

- The model judges the task semantics: goal, intent, whether a write is
  required, whether observable state must change, expected deliverables, first
  action, blockers, confidence, and whether a plan is useful.
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
  "requires_state_change": true,
  "requires_verification": true,
  "requires_plan": false,
  "deliverables": [
    {
      "kind": "file",
      "path_hint": "model-viewer.html",
      "path_policy": "hint",
      "description": "A Three.js GLB/GLTF model viewer example"
    }
  ],
  "first_action": "write",
  "success_conditions": [
    "target_deliverable_success",
    "target_deliverable_verification",
    "final_answer_with_evidence"
  ]
}
```

Follow-up requests declare a `scope_relation`. `continue` and `revise` keep
the previous task's semantic target while the model changes execution strategy
or quality requirements. `replace` and `new` establish a different target.
The runtime preserves a compact `continuity_anchor` for continued/revised
tasks, preventing an intermediate fallback from silently becoming the next
turn's product goal.
Conversation-history inheritance is implemented in
`runtime/agent_strategy/conversation_task_context.py` so follow-up routing,
previous write context, document export context, and inherited output-length
goals can be tested without Tornado handlers.

Contract evolution after the initial judgment belongs in
`runtime/agent_strategy/contract_evolution.py`. That layer handles follow-up
continuity, explicit execute-follow-up inheritance, and runtime promotion when
plan or tool facts reveal a stricter write target. The base `task_contract`
module should keep owning schema normalization and hard constraints, not every
runtime fact that can strengthen a contract.

Deliverable paths are soft hints by default. A successful artifact of the same
declared kind may use another path and still satisfy the contract; the path
deviation is recorded in `RunResult`. Use `path_policy="exact"` only when the
user explicitly requires the precise path.

Tool identity and task role are intentionally separate. `tool_id` tells the
runtime whether a call can change local state, so it is used for permission,
safety, and confirmation gates. A `tool_event` is interpreted inside the current
task contract as evidence, draft, temporary artifact, target deliverable, or
verification. Run completion is based on whether the declared target
deliverable role was satisfied, not on a fixed list of tool IDs.

`requires_write` specifically means that a local file artifact must be created
or modified. `requires_state_change` covers the wider class of observable
changes, including files, Blender/CAD scenes, browser sessions, databases, and
other external applications. An external-state task can therefore set
`requires_state_change=true` and `requires_write=false`.

These fields are completion requirements, not permission toggles. If a request
is ambiguous, the model may still choose a state-changing repair strategy unless
the user or runtime has set a hard no-write boundary. In that case `RunResult`
records the observed write separately from target deliverable satisfaction
instead of treating the task contract as an execution lock.

Tool providers may declare `effects`, `roles`, and `artifacts`. Successful tool
results carry these facts into the event trace, allowing the runtime to audit
external-state deliverables without hard-coding provider tool IDs.
Tool progress snapshots, frontend previews, and compact model-facing tool
payloads are presentation mechanics owned by `runtime/tool_event_presentation.py`;
they should not decide whether a task succeeded.

Result convergence is role-aware. A failed target-deliverable action can block
the Run, a failed required verification can degrade it to partial, and a failed
auxiliary/evidence action remains auditable without automatically overriding a
satisfied task goal. Failures that are followed by a successful replacement
deliverable or sufficient verification are recorded as recovered.

Verification is evidence with strength, not only a boolean tool role. Providers
may declare `verification_strength` as `weak`, `standard`, or `strong`.
Task contracts require `standard` evidence by default when
`requires_verification=true`; coarse inspection may therefore support the
summary without proving the requested outcome. `RunResult` records all
verification evidence, its strength, whether it satisfied the contract, and
role-aware failure impacts.

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
- successful target deliverables, including external-state changes
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

Optional model-initiated local writes are not treated as contract failures when
the task did not require a write. If such a write has no observed verification,
`RunResult` records `optional_write_not_verified` and the UI can present the
result as modified-but-unverified without blocking the model's chosen strategy.

Future UI work should prefer showing facts from `RunResult` over inferring task
state from assistant text.

Tool-result risks are advisory runtime facts discovered after a tool finishes.
They help the model notice evidence without letting the runtime choose a fixed
repair strategy. The risk pipeline is documented in
[tool-result-risks.md](tool-result-risks.md).

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

Memory has a hard scope boundary. Global memory is limited to user-level
preferences, communication style, identity, and cross-project habits. Workspace
memory carries project-specific facts and is selected only when the current run
uses the same `workspace_id`. Automatic extraction promotes only clear
user-level facts into global memory; project facts require explicit
workspace-scoped saving.

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

Current runtime-level capability guards:

- each run records a `capability_snapshot` event after `task_contract`;
- the snapshot includes available tools, unavailable tools, capability groups,
  and external-state effects declared by ToolSpec or MCP tool policies;
- `capability_preflight` blocks tasks that explicitly target external
  application state when no available capability reports
  `external_state_change`;
- when a target capability is declared for an external-state task, the model's
  visible state-changing tools are restricted to that capability boundary;
- execution still performs a second guard before running a tool, so malformed
  native/tool-call variants cannot silently fall back to shell scripts or file
  generation outside the preflight boundary.

Tool execution guards have a stable pre-confirmation order for a resolved tool:
plugin enablement, service availability, capability fallback boundary, required
input fields, AI-built Capability Pack boundary, document contract boundary, and
runtime verification method checks. A guard failure returns a deterministic
reason and message before manual confirmation is requested.

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

1. Refine product-level Task lifecycle and task-level cancellation.
2. Connect context snapshots to compression and longer-running resume flows.
3. Map ToolSpec metadata into CapabilityContract.
4. Persist confirmation requests and outcomes as first-class trace events.
5. Split `conversation_runner.execute()` by controller responsibility.
6. Teach the frontend to display `RunResult` explicitly.
7. Add checkpoint rollback and policy-controlled unattended Runbook execution.
8. Connect selected Experience Samples to local Replay/Evaluation without
   automatic collection or promotion.
