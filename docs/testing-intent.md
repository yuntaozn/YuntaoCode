# Testing Intent

This document calibrates the intent of the current test suite for the 0.1
closeout. The goal is not to reduce the number of tests. The goal is to keep
tests aligned with YuntaoCode as a local-first AI Task Runtime.

## 0.1 Test Goal

Tests should protect runtime contracts, not historical implementation accidents.

For 0.1, a good test usually protects one of these foundations:

- Task, Run, Plan, Step, lifecycle, recovery, replay, or audit state.
- Tool-call protocol, validation, aliases, confirmation, and execution guards.
- Capability contracts, provider boundaries, provider health, and preflight
  evidence.
- Context hygiene, memory boundaries, context compression, and follow-up task
  inheritance.
- RunEvidence, RunResult, verification strength, result synthesis, and user
  facing completion truth.
- Persistence boundaries, migration, startup recovery, and cross-platform
  settings paths.
- Built-in tool safety: PathGuard, write/delete boundaries, shell execution,
  document processing, attachments, web access, and temporary artifacts.

Tests should not freeze a temporary workaround unless it has been generalized
into a runtime contract.

## Current Calibration

The current suite is not too large for the project stage. The latest audit
counted about 69 test files and 14k test lines against about 48k runtime source
lines. That is a reasonable ratio for a project whose main value is runtime
state, permissions, verification, recovery, and audit.

The suite currently has four useful layers:

- **Core contract tests** protect schema and state boundaries. Examples:
  `test_core_runtime.py`, `test_task_contract.py`, `test_run_store.py`,
  `test_run_events.py`, `test_run_result.py`, `test_run_evidence.py`,
  `test_tool_event_roles.py`, and `test_capability_evidence.py`.
- **Capability and tool boundary tests** protect provider identity, permission,
  confirmation, protocol validation, and cross-platform safety. Examples:
  `test_tool_registry.py`, `test_tool_execution_guard.py`,
  `test_capability_preflight.py`, `test_capability_router.py`,
  `test_cli_provider_manager.py`, `test_mcp_protocol.py`,
  `test_mcp_service_manager.py`, `test_security.py`,
  `test_filesystem_tool.py`, `test_code_tool.py`, and `test_shell_tool.py`.
- **Context and strategy tests** protect model-facing context hygiene and the
  extracted strategy helpers. Examples: `test_context_hygiene.py`,
  `test_context_manager.py`, `test_conversation_task_context.py`,
  `test_agent_strategy.py`, and `test_agent_strategy_behaviour.py`.
- **Experience and operational tests** protect diagnostics, samples,
  evaluation, plugins, settings, automation, and update behavior. Examples:
  `test_diagnostic_export.py`, `test_experience_sample_export.py`,
  `test_evaluation_fixture.py`, `test_evaluation_report.py`,
  `test_plugins_api.py`, `test_settings_policies.py`,
  `test_automation_store.py`, and `test_source_update.py`.

## High-Signal Areas

These areas should stay well covered during 0.1 closeout:

- `Task Contract -> Tool Events -> RunResult`: this is the main truth chain for
  deciding whether a task actually completed.
- `Capability Snapshot -> Preflight -> Guard -> Tool Execution`: this keeps
  MCP, CLI, built-in tools, and future providers under one runtime boundary.
- `Context Hygiene -> Follow-up Inheritance`: this prevents previous failed
  runs or stale goals from becoming hidden instructions.
- `RunStore -> RunEvent -> Recovery`: this lets the UI and diagnostics explain
  what happened after long tasks, pauses, restarts, and failures.
- `Tool Alias -> Tool Protocol`: this protects the runtime from model output
  format variants without making every variant a new tool.

## Tests To Keep, But Watch

Some tests are useful but can become too rigid if extended carelessly.

- `test_agent_strategy.py` is intentionally large because it fences many pure
  strategy helpers extracted from the runner. Keep it for 0.1, but put new
  tests into more focused modules when the target helper already has a home.
- `test_task_contract.py` and `test_document_contract_guard.py` protect the
  important boundary between model-declared task intent and runtime-owned
  safety. Avoid adding exact prompt wording assertions unless the wording is
  itself a user-visible contract.
- `test_tool_aliases.py` is a compatibility boundary for common model tool-name
  variants. Add aliases only when the variant is broad and recurring, not when
  one model made a one-off mistake.
- Document and long-task tests should protect deliverable roles, verification,
  chunking, and evidence, not a specific document scenario or a specific model
  phrasing.

## When To Add A Test

Add a test when the behavior is part of the runtime foundation:

- A state transition should remain valid across refactors.
- A tool or provider must not bypass permission or confirmation.
- A task should not be marked complete without evidence.
- A model-output variant should be normalized by a general protocol rule.
- A long task should remain observable, recoverable, and auditable.
- A cross-platform path, settings, or command behavior could break silently.

Prefer testing pure helpers, store boundaries, and tool contracts before testing
Tornado handlers or UI glue.

## When To Rewrite Or Remove A Test

Rewrite or remove a test when it only protects a historical accident:

- It asserts exact internal prompt prose that is not a contract.
- It exists only because one model once produced one malformed phrase, and the
  fix is not a general normalization rule.
- It freezes a temporary file name, line count, UI label, or retry sequence that
  should remain flexible.
- It duplicates a stronger test at the Task Contract, Capability, RunResult, or
  Tool Protocol layer.
- It makes a new capability hard to evolve even though the runtime boundary is
  still respected.

Do not remove a symptom regression immediately if it is the only evidence for a
known user-facing failure. First move the behavior into a general contract test,
then remove the narrow symptom test.

## New Test Placement

Use these defaults:

- `tests/test_core_runtime.py` for pure runtime schemas.
- `tests/test_task_contract.py` for model-declared task intent, continuity, and
  runtime guidance.
- `tests/test_tool_event_roles.py` for deliverable, verification, artifact, and
  evidence role classification.
- `tests/test_run_result.py` for final completion truth, risk synthesis, and
  verification strength.
- `tests/test_capability_preflight.py` and `tests/test_capability_router.py`
  for capability snapshots, advisories, provider boundaries, and routing.
- `tests/test_tool_execution_guard.py`, `tests/test_tool_call_protocol.py`, and
  `tests/test_tool_aliases.py` for protocol validation and safe normalization.
- `tests/test_context_hygiene.py` and
  `tests/test_conversation_task_context.py` for context sanitation and
  follow-up inheritance.
- `tests/test_agent_strategy.py` only when adding or changing a pure helper in
  `runtime/agent_strategy/classifiers.py`, `prompts.py`, `policy.py`,
  `profiles.py`, or `plan_tracker.py`.

## 0.1 Closeout Rule

Before adding a test, ask:

> Does this test help 0.1 close out by clarifying task state, context boundary,
> capability contract, evidence, recovery, audit, or completion truth?

If the answer is no, record the scenario in a diagnostic sample or issue first
instead of hardening it into the test suite.
