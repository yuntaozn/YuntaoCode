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
