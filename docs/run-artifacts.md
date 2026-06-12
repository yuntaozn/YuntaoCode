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

Direct `/tasks` API calls without a Run scope keep their existing per-ToolTask
temporary directories.

Run artifacts are not project changes and do not satisfy a requested write
deliverable. They should remain isolated from the workspace until a verified
result is explicitly written through a project write capability.

## User Attachments Are Different

Files uploaded by a user are immutable conversation inputs, not run artifacts
and not project files. The runtime stores their bytes under its local data
directory and keeps only attachment references in conversation messages.

An attachment may be read only through an attachment capability authorized for
the current conversation run. A task can create temporary derivatives in its
run artifact directory, or explicitly write a verified output into the
workspace, but attachment storage itself is never exposed as a project path.
