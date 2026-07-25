# Run Artifacts

Temporary artifacts created while completing one model run belong to the run,
not to an individual tool call.

This distinction matters because a useful execution commonly spans several
ToolTasks:

```text
filesystem.write_temp_file
-> shell.run_command(cwd="task_temp")
-> inspect result
-> write verified project artifact
```

Each ToolTask still has its own task ID, logs, status, and output record. Tools
invoked by the same conversation Run share one isolated artifact directory so
that a later tool can consume an earlier tool's temporary output.

Direct `/tool-tasks` API calls without a Run scope keep their existing per-ToolTask
temporary directories.

Run artifacts are not project changes and do not satisfy a requested write
deliverable. They should remain isolated from the workspace until a verified
result is explicitly written through a project write capability.

## Run Artifact Records

`runtime/artifacts.py` provides the shared `run_artifact.v1` record used by
`RunResult`, `RunEvidence`, diagnostics, and the task workbench.

This record is passive evidence. It does not choose tools, decide whether the
task is complete, block execution, or replace model judgment.

A Run Artifact can represent:

- a final workspace file written for the user;
- a draft or partial text artifact;
- a screenshot, render, preview image, or visual evidence file;
- a command/debug log;
- verification evidence such as a test, preview, or runtime check.

The compact fields are:

- `artifact_kind`: file, text_file, screenshot, command_log, verification, and
  similar concrete artifact categories.
- `role`: `final`, `draft`, `screenshot`, `preview`, `log`,
  `verification`, `intermediate`, or `artifact`.
- `path` / `url`: observable location when one exists.
- `source_tool`: the tool that produced the evidence.
- `status`: observed tool/result status.
- `can_preview`: whether the UI can reasonably expose a preview affordance.
- `can_enter_model_context`: whether the artifact is suitable to reference in
  future model context, such as an image screenshot or compact text/log fact.
- `verification_relevance`: `deliverable`, `verification`, `diagnostic`, or
  `context`.
- `metadata`: bounded details such as size, format, dimensions, validation,
  command, exit code, runtime error counts, and optional `model_context_path`
  when an artifact has a concrete image/text location that can be referenced by
  model-context bridges.

`RunResult.artifacts` remains the compatibility field for historical
write-artifact summaries. New consumers should prefer `RunResult.run_artifacts`
and `RunResult.artifact_summary`, then fall back to the legacy field.
`artifact_summary.model_context_paths` lists the bounded artifact locations that
are eligible for future model context. This is evidence only: it does not force
image injection or decide whether visual verification was sufficient.

`artifact_summary.path_index` is the compact path-level view. It merges
multiple records for the same path, such as a file that is both a final
deliverable and later verification evidence. Each entry keeps roles, artifact
kinds, source tools, statuses, verification relevance, previewability, and
model-context eligibility. Consumers should use this index when they need to
show or explain path meaning instead of reconstructing it from separate role
arrays.

`artifact_summary.preview_paths`, `verification_paths`, and
`diagnostic_paths` are bounded helper buckets derived from the same artifact
records. They are presentation and evidence aids; they do not make a path the
target deliverable and do not change task completion rules.

## Verification Freshness

Verification evidence has a time relation to produced artifacts. A screenshot,
test, preview, or query that happened before the latest observed final/draft
artifact cannot prove the current state by itself.

`verification_closure.v1` therefore exposes a nested
`verification_freshness` evidence block:

- `latest_change_event_index`: the latest Run tool-event index that produced a
  final or draft artifact, when known.
- `counts.fresh`: verification evidence observed at or after that latest
  change.
- `counts.stale`: verification evidence observed before that latest change.
- `counts.unknown`: verification evidence whose event order is not known.
- `paths.fresh`, `paths.stale`, and `paths.unknown`: bounded path buckets for
  user inspection and model-facing context.

This is still evidence only. It does not force the model to run another tool,
stop execution, or mark a task failed. It gives the model and user the concrete
fact that some evidence may no longer describe the latest artifact.

`RunEvidence.artifacts` exposes the same normalized records for diagnostics,
task history, future replay fixtures, and local evaluation. The task workbench
uses artifact roles to keep screenshots and logs visible without counting them
as changed project files.

The task workbench may expose local "open" and "copy path" actions for paths
that are explicitly present in the current Run evidence. Opening is a UI
inspection affordance only: `runtime/run_artifact_access.py` verifies that the
requested path was recorded by that Run and that the resolved local path stays
inside either a configured workspace root or the YuntaoCode local data
directory. This does not make arbitrary local files available, and it does not
feed back into task routing or completion judgment.

Browser thumbnails use the same boundary and are limited to common image
formats under the Run artifact preview size limit. Non-image artifacts can
still be opened by the local desktop/runtime action, but they are not served as
inline preview bytes.

The Workbench evidence overview is emitted by `run_workbench.v1` as
`workbench_evidence_overview.v1`. It groups the same records into deliverable,
visual, verification, and runtime-debug cards. This keeps the browser UI from
reconstructing artifact meaning on its own, while preserving the same boundary:
the overview is a presentation-only reading aid for users and contributors, not
a second completion engine.

## User Attachments Are Different

Files uploaded by a user are immutable conversation inputs, not run artifacts
and not project files. The runtime stores their bytes under its local data
directory and keeps only attachment references in conversation messages.

An attachment may be read only through an attachment capability authorized for
the current conversation run. A task can create temporary derivatives in its
run artifact directory, or explicitly write a verified output into the
workspace, but attachment storage itself is never exposed as a project path.
