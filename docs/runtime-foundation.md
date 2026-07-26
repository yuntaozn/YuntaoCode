# Runtime Foundation Contract

This document records the current foundation contract for YuntaoCode as an
open-source Local-First AI Task Runtime.

The goal is to keep the base architecture clear while the project is still in
alpha. New features should build on these contracts instead of adding another
hard-coded branch in the runner.

## Foundation Scope

The foundation contract keeps these boundaries explicit:

- the project is a local-first AI Task Runtime, not a tool bundle, chat shell,
  MCP/CLI client, or Skill manager;
- Task, Context, Capability, and Experience are the main architecture lines;
- providers such as built-in tools, CLI, MCP, Capability Packs, and plugin
  declarations must enter the same Capability Runtime boundary;
- evidence, state, permissions, verification, and recovery must remain more
  important than adding another scenario.

## Development Direction Gate

`v0.1.0` is the fixed direction release for the runtime foundation. It is not a
promise that every scenario is stable, every provider is mature, or every future
extension path is finished.

The `main` branch now tracks `0.2.0-dev`. Before a change enters the 0.2
mainline, it should make at least one runtime boundary clearer:

- Task state, trace, recovery, verification, or result evidence;
- Context selection, compression, memory scope, source trust, or stale-context
  handling;
- Capability contracts, provider health, permissions, confirmation, artifacts,
  or evidence strength;
- Experience/evaluation records derived from selected RunEvidence without
  becoming hidden prompts, automatic capability promotion, or trusted generated
  code.
- Observation, verification, or artifact records that let the model and user see
  what actually happened.

The preferred direction is removal of hidden control, clearer observable facts,
and stronger execution records. The model owns task semantics, route choice,
self-correction, and final wording. The runtime owns protocol integrity,
permissions, local safety boundaries, persisted state, and evidence surfaces.

Changes that mainly add a scenario, product promise, marketplace idea, new tool
list, or external concept should stay outside the 0.2 mainline until real runs
show which boundary they clarify.

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
  saved user goal and schedule into a normal prepared Task/Run, and does not
  execute tools or bypass runtime permissions directly.
- **Experience Runtime** extracts reviewed task experience from Runbook and
  RunResult facts. In 0.1 it covers RunEvidence, diagnostic export,
  Experience Sample export, Evaluation Fixture, and Evaluation Report records;
  it does not control live task execution or make generated code trusted.

Ideas beyond this boundary stay out of the mainline runtime contract until real
task evidence shows which boundary they improve.

The model may propose task semantics, routing, next actions, and final wording.
The runtime owns schema, permissions, state transitions, evidence, and
observable closure facts.

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

The current convergence rule is progress-driven:

1. Each failed tool attempt is returned to the model as real execution evidence.
2. A repeated failed route inside the current no-progress window triggers an
   advisory with `execution_convergence` facts. The model may still choose the
   next route.
3. A successful or partial tool result resets the no-progress window.
4. Changing tool, arguments, or route is treated as self-correction evidence
   and expands the bounded retry budget.
5. The runtime stops only when the latest failed route repeats too many times
   in a no-progress window. This prevents an infinite loop without turning the
   runtime into a planner.

This contract is deliberately narrower than task planning. It judges whether
execution is converging; it does not hard-code which strategy the model must
choose.

Successful execution also needs convergence. For write-required tasks,
verification evidence only counts when it occurs after the latest successful
write. Once the write and verification conditions are both satisfied, the
runtime moves to finalization instead of continuing to expose an open-ended
write loop.

## User Guidance And Runtime Advisory Governance

User guidance during a run is a new user semantic source, not a runtime-chosen
strategy. Runtime advisories keep execution observable and safe while leaving
task strategy to the model.

Guidance and advisories should stay in four explicit layers:

1. **Hard safety boundary**
   - PathGuard, permission scope, user confirmation, disabled tools, unavailable
     providers, malformed arguments, provider protocol errors, and truncated
     state-changing calls.
   - These may stop or skip a tool call because the runtime cannot execute it
     safely or meaningfully.
2. **Advisory fact**
   - Capability fit, document-coverage hints, weak verification routes, repeated
     read/search patterns, degraded provider health, and preferred tools.
   - These are model-facing facts. They should not block execution or force a
     strategy by themselves.
3. **Risk evidence**
   - Non-blocking advisories and observable tool-result warnings are carried as
     `runtime_risks` so Context Pack, RunResult, diagnostics, Runbook, and
     evaluation records can audit them.
4. **User guidance**
   - A running user message is recorded as `guidance` and may interrupt the
     current model stream at a safe point.
   - The runtime re-orients the model with the new user text and existing run
     facts. It does not prescribe the next route.
   - Older stream or diagnostic readers may still see
     `runtime_intervention` compatibility fields. New runtime code should use
     User Guidance terminology and `guidance_count`.

This means a document translation hint should say that a temporary script may
weaken coverage, progress, resumability, and verification evidence. It should
not say that the model is forbidden to choose that route. If the model chooses a
different safe strategy, the runtime should judge the actual artifact and
verification evidence, not the route label.

`tool_attempt_observation.v1` is the shared record for a model-proposed tool
call that did not run. It covers malformed JSON, non-object arguments, missing
required fields, unknown tool names, truncated tool calls, unavailable
capability services, disabled tools, safety boundaries, and user-cancelled
local actions. The record keeps `reason` and `message` for compatibility, but
also carries a bounded input summary, missing fields, available tool hints when
useful, and model-facing repair options.

This observation is not a task verdict. It says only that one attempted action
was not executed by the runtime. The model should use the fact to decide whether
to resend valid parameters, choose another visible tool, gather missing context,
start or refresh a dependency, verify existing output, ask the user, or stop
honestly. Large write-like attempts are reported as evidence that incremental
write/edit routes are usually more reliable, but the runtime does not forbid the
model from choosing a different safe route.

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
diagnostic export, and evaluation fixture/report records. It does not replace the
stored events and does not include raw tool outputs or file contents; it keeps
event families, canonical names, counts, terminal status, result status, and a
sanitized timeline.

`runtime/run_evidence.py` builds `run_evidence.v1`, the unified fact view for
post-run consumers. RunEvidence gathers the Run metadata, task contract,
trace summary, capability evidence, capability snapshot, plan, tool steps,
completion decisions, result, verification evidence, failures, checkpoints,
recovery summary, and a manual replay seed. Runbook, diagnostic export,
Experience Sample export, and evaluation records consume
RunEvidence instead of each parsing persisted events separately.

RunEvidence is an evidence layer, not a strategy layer. It must not execute
tools, silently promote generated code, alter model context, or decide whether
a run should retry, replay, or change strategy.

`runtime/run_workbench.py` builds `run_workbench.v1`, the user-facing workbench
view derived from RunEvidence. It presents run status, task contract facts,
an audit summary, changed paths, artifacts, verification, risks, failures,
completion decisions, context evidence, visual context evidence, plan steps,
timeline, capability state, and recovery actions in a compact UI-ready shape.
It is a presentation layer, not a second evidence source; RunEvidence and
RunResult remain the runtime-owned truth.

Current canonical event names include:

- `run.status`
- `run.guidance`
- `run.completion_decision`
- `context.hygiene`
- `context.pack`
- `context.visual`
- `context.workspace_snapshot`
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
  built from RunEvidence, so the task history can show audit counts, changed
  paths, context evidence, visual context evidence, artifacts, verification,
  risks, failures, plan steps, and timeline without parsing raw events in the
  frontend.
- `{"action": "export_evaluation_fixture"}` returns a local
  `evaluation_fixture_export.v1` artifact built from RunEvidence. It does not
  execute replay or submit anything remotely.
- `{"action": "evaluate_fixture", "fixture": {...}}` compares the current
  RunEvidence with a selected `evaluation_fixture.v1` and returns an
  `evaluation_report.v1`. It does not execute replay, call a model, call tools,
  or promote new capabilities.
- `{"action": "replay"}` creates a new prepared Run under the same Task and
  returns a replay request artifact. It does not execute tools until the user
  explicitly starts the prepared Run.

Run lineage is explicit through `task_id`, `parent_run_id`, `source_run_id`,
`attempt`, and `resume_from_checkpoint_id`.

Completed or partial Runs persist a recovery `ContextSnapshot` and
`Checkpoint`. A recovered Run receives bounded runtime facts, evidence, and
unresolved risks from the checkpoint instead of replaying the full failed
conversation as instructions.

Runbook and Replay provide the evidence base for 0.1 experience and evaluation
records. A selected RunEvidence view can be exported as an Experience Sample,
and selected evidence can be represented as Evaluation Fixture / Report records.
These records are passive artifacts; they do not register trusted capabilities
or execute generated code.

Completion decisions are completion-loop evidence. After a completion
self-review prompt, the runtime records the model's observable choice: continue
with tools, produce a final-answer candidate, repair malformed tool-call
protocol, or make no observable decision. This event does not force a route; it
exists so the Workbench, Replay, and Evaluation can inspect how a run attempted
to close.

`completion_evidence_pack.v1` is the model-facing fact package used by that
self-review prompt. It groups RunResult, compact Run facts, legacy artifacts,
typed Run artifacts, artifact summary, verification evidence, verification
closure, visual verification summary, runtime debug audit, capability evidence,
recent ToolTask progress, risks, failures, and previous completion decisions.
The pack is evidence-only: it does not decide completion, rank tools, force
fallback, or block the model from changing strategy. The model remains
responsible for deciding whether to continue with tools, verify or repair, ask
the user for a missing boundary, or produce a final answer from the observed
evidence. The pack also carries an explicit presentation budget: structural
evidence preserves high-priority facts such as final artifacts, verification
closure, tool progress, failures, and risk records, while repetitive paths and
long rendered prompt text are bounded before they enter the next model round.

Run result presentation follows the same boundary. User-facing notices are
derived from observed facts such as writes, failures, verification gaps,
round-budget exhaustion, and risk codes. They should describe evidence and
continuation basis, not prescribe a fixed strategy or replace the model's
completion judgment. Model-backed result synthesis uses the same RunResult
facts to write a final user-facing answer; it is a bounded presentation pass,
not a second execution run or a new completion judge. The current user request
is passed as a request-reference context rather than a raw tail slice: it keeps
bounded request head/tail text, explicit request marker lines, and referenced
files, paths, or URLs so early goals and late constraints can both remain
visible without letting the original prompt override RunResult evidence.

## Diagnostic Export

Diagnostic export helps compare task behavior across machines and should be
generated only when the user asks for a specific Run diagnostic package.

The diagnostic package is a compact, sanitized JSON artifact. It may include
runtime version, operating-system and executable availability, sanitized model
and provider settings, tool and MCP capability status, Run summary, compact
Runbook evidence, and recent event summaries. It must not include API keys,
full file contents, full model transcripts, or the complete Runbook/event log
by default.

Diagnostic exports are manual local downloads in 0.1. They are not persisted by
the Runtime and are not submitted to any service.

## Experience And Evaluation Foundation

Experience and evaluation records are part of the 0.1 foundation. They are
local artifacts for selected Runs, not a separate product line and not an
automatic learning system.

The 0.1 evidence chain is:

```text
Run
  -> RunEvidence
  -> Diagnostic Export
  -> Experience Sample Export
  -> Replay Fixture
  -> Evaluation Fixture
  -> Evaluation Report
```

Diagnostic Export is for debugging a specific Run on a specific machine.
Experience Sample Export is for saving a reviewed sample from selected
RunEvidence. Evaluation Fixture and Evaluation Report records make selected
evidence comparable without replaying or collecting tasks automatically.

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

Experience and Evaluation remain local, manual foundations in 0.1. There is
no automatic task collection, upload, public leaderboard, central sample
service, automatic fixture execution, or trusted execution of AI-generated
code.

## Task Contract

Before a run enters planning or tool execution, the runtime now builds a
`task_contract`.

The intended split is:

- The model judges the task semantics: goal, intent, whether a write is
  required, whether observable state must change, expected deliverables, first
  action, non-binding execution advisories, confidence, and whether a plan is
  useful.
- The runtime owns the contract shape, schema version, local security
  overrides, workspace scope, success conditions, and observable closure facts.

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
Conversation history is exposed as bounded task candidates by
`runtime/agent_strategy/conversation_task_context.py` and `task_lineage.py`.
The runtime does not infer a previous write mode, document workflow, or output
length from keywords. Continuity is applied only after the model explicitly
references a candidate and declares `continue` or `revise`.

Contract evolution after the initial judgment belongs in
`runtime/agent_strategy/contract_evolution.py`. That layer handles explicit
follow-up continuity without turning observed tool effects into new semantic
requirements. Tool writes and paths remain Run evidence; they do not rewrite
the declared target. The base `task_contract` module owns schema normalization,
not scenario routing.

Deliverable paths are soft hints by default. A successful artifact of the same
declared kind may use another path and still satisfy the contract; the path
deviation is recorded in `RunResult`. Use `path_policy="exact"` only when the
user explicitly requires the precise path.

Tool identity and task role are intentionally separate. `tool_id` tells the
runtime whether a call can change local state, so it is used for permission,
safety, and confirmation gates. A `tool_event` is interpreted inside the current
task contract as evidence, draft, temporary artifact, target deliverable, or
verification. Run completion is based on task-role evidence, not on a fixed list
of tool IDs.

The finalization gate is also task-role aware. Write and external-state tasks
enter completion self-review after the target deliverable appears. Read-only
analysis and answer-evidence tasks have no file or external object to observe,
so successful evidence-gathering tools can enter the same completion self-review
loop. In both cases the gate is evidence feedback: the model decides whether to
continue, verify, repair, or finish.

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

The runtime records contract gaps as evidence, but it should not turn ordinary
task-language heuristics into hidden routing locks. Explicit local permission
boundaries, confirmation policy, and safety checks remain runtime-owned.

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

UI work should prefer showing facts from `RunResult` over inferring task state
from assistant text.

Tool-result risks are advisory runtime facts discovered after a tool finishes.
They help the model notice evidence without letting the runtime choose a fixed
repair strategy. The risk pipeline is documented in
[tool-result-risks.md](tool-result-risks.md).

`verification_closure.v1` is the Run-level verification evidence package. It
combines verification records, visual verification, debug audit, artifact
roles, missing modalities, and risk codes into one compact fact view. It is
evidence-only: it does not choose a verification route, block execution, or
decide that a task is complete. Its purpose is to let the model and the user
see the current evidence coverage and remaining gaps before the model decides
whether to verify, revise, ask, or finish honestly.

The closure also carries `verification_freshness` facts derived from Run tool
event order. A verification record, screenshot, preview, or debug check that
occurred before the latest observed final/draft artifact is marked stale;
evidence with unknown event order stays unknown. This freshness fact is
model-facing evidence, not a hidden route: the model still decides whether to
verify again, revise, ask, or stop honestly.

When `RunResult.status` is `partial` or `failure` and the model did not provide
a usable final answer, the runtime presents a deterministic fact summary. It is
a fallback audit view, not a model-authored completion claim. Intermediate text
emitted before a structured tool call is process narration, not a trustworthy
completion claim.

Short follow-up requests should be interpreted against recent task context
before the runtime selects an execution profile. The model proposes whether a
follow-up continues an existing task; the runtime still owns permissions,
required write/verification evidence, and observable completion facts. This avoids
treating concise requests such as an incremental artifact change as isolated
chat messages.

## Context Runtime

Context is a runtime resource, not just chat history. It should track:

- task goals and explicit user constraints;
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
5. Record a `context_hygiene` report when cleanup happens so strategy changes
   can be audited and tested.

0.1 keeps this layer focused on explicit context records and hygiene reports;
unimplemented context features stay out of the foundation contract.

Initial schemas are defined in `runtime/core/context.py`:

- `ContextRecord`
- `EvidenceRecord`
- `ContextSnapshot`

Design notes live in [context-runtime.md](context-runtime.md).

## Capability Runtime

Tools, built-in skills, plugin declarations, and MCP servers should enter the task
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
- `capability_preflight` reports readiness facts and advisories for tasks that
  appear to target external application state, missing services, degraded tools,
  or uncertain visual verification routes;
- `task_route_evidence.v1` records the model-declared route proposal derived
  from Task Contract `capability_ids` or explicit `route_proposals`, validates
  it against the current capability snapshot, and exposes the result as
  evidence-only facts for the model, diagnostics, Runbook, and evaluation;
- when a target capability is declared for an external-state task, the runtime
  presents visible capability, provider, readiness, and evidence facts, while
  leaving route selection to the model unless a separate safety/permission
  boundary applies;
- new runs use `capability_preflight.v2`, which carries advisory
  `readiness_issues` and `route_hint` metadata instead of legacy
  route-control fields;
- execution still performs a second guard before running a tool, so malformed
  native/tool-call variants cannot silently fall back to shell scripts or file
  generation outside the declared safety and permission boundary.

Tool execution guards have a stable pre-confirmation order for a resolved tool:
plugin enablement, service availability, required input fields, capability
fallback advisory, AI-built Capability Pack boundary, document contract
advisory, and runtime verification method checks. A hard guard failure returns
a deterministic reason and message before manual confirmation is requested;
advisory guards are recorded as risk evidence without hiding the tool route
from the model.

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
