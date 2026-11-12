# Tool Result Risks

Tool result risks are structured facts discovered around a tool call. They help
the model notice important evidence without letting the runtime choose the
model's next strategy.

The protocol has four boundaries:

1. A tool reports factual output such as an integrity check, stderr, image
   metadata, or an external-call failure.
2. `runtime/agent_strategy/tool_result_risks.py` converts relevant facts into
   non-blocking `runtime_risks`.
3. The conversation runtime sends those risks back to the model and records
   them in the tool event.
4. `RunResult` includes the risk codes in the final audit record.

Example:

```json
{
  "runtime_risks": [
    {
      "code": "artifact_integrity_invalid",
      "severity": "warning",
      "source": "filesystem.read_file",
      "blocking": false,
      "issues": ["html appears escaped as text"]
    }
  ]
}
```

Another common case is a shell command that exits with code `0` while stderr
contains exception-like output. The command result is still recorded exactly as
the tool returned it, but the runtime adds `shell_stderr_warning` so the model
does not treat that command as clean verification evidence.

Pre-execution capability-route, document-coverage, and verification-strategy
advisories are removed. The execution guard checks enabled/available tools,
required inputs, and capability-draft write boundaries; PathGuard and operation
confirmation remain enforced by their original execution layers. Task contracts
and preflight records stay auditable without generating per-call route advice.

Risk records carry observations, source, diagnostic codes, and non-blocking
status. They do not carry `action`, `suggested_tools`, or duplicated
`suggested_calls`. Original tool diagnostics remain in the output. Legacy
`runtime_advisories` are not projected back into a new model-facing payload;
stored historical Run events remain available for audit.

Risks are advisory by default. The model may repair the artifact, continue with
an explicit assumption, or stop and report the issue. Safety and permission
guards remain separate hard boundaries.

External-call failures retain `side_effects=unknown` and
`rollback_observed=false`: failure alone does not establish rollback. The model
can inspect the same capability or choose another action from observed state.

When adding a new risk:

- Derive it from observable tool output, not inferred user intent.
- Keep the classifier pure and provider-independent.
- Use a stable risk code suitable for audit assertions.
- State observed facts without prescribing a tool, route, or next action.
- Do not add a runner branch solely to force one recovery strategy.
- Add tests for model transport and final audit visibility.
