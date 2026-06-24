# Tool Result Risks

Tool result risks are structured facts discovered after a tool finishes. They
help the model notice important evidence without letting the runtime choose the
model's next strategy.

The protocol has four boundaries:

1. A tool reports factual output such as an integrity check.
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
      "action": "assess_before_state_change",
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

Risks are advisory by default. The model may repair the artifact, continue with
an explicit assumption, or stop and report the issue. Safety and permission
guards remain separate hard boundaries.

For large artifacts, recovery should prefer a bounded local transformation
whose tool call describes the operation rather than retransmitting the complete
artifact through model output.

When that transformation needs a temporary script or intermediate file, tools
within the same Run can exchange it through the shared Run artifact directory
described in [run-artifacts.md](run-artifacts.md).

When adding a new risk:

- Derive it from observable tool output, not inferred user intent.
- Keep the classifier pure and provider-independent.
- Use a stable risk code suitable for audit assertions.
- Do not add a runner branch solely to force one recovery strategy.
- Add tests for model transport and final audit visibility.
