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
  command, exit code, and runtime error counts.

`RunResult.artifacts` remains the compatibility field for historical
write-artifact summaries. New consumers should prefer `RunResult.run_artifacts`
and `RunResult.artifact_summary`, then fall back to the legacy field.

`RunEvidence.artifacts` exposes the same normalized records for diagnostics,
task history, future replay fixtures, and local evaluation. The task workbench
uses artifact roles to keep screenshots and logs visible without counting them
as changed project files.

## User Attachments Are Different

Files uploaded by a user are immutable conversation inputs, not run artifacts
and not project files. The runtime stores their bytes under its local data
directory and keeps only attachment references in conversation messages.

An attachment may be read only through an attachment capability authorized for
the current conversation run. A task can create temporary derivatives in its
run artifact directory, or explicitly write a verified output into the
workspace, but attachment storage itself is never exposed as a project path.
