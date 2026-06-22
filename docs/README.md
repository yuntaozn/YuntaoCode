# YuntaoCode Documentation Map

This directory is organized by runtime layer. Start here when deciding where a
new architecture note belongs.

## Foundation

- [runtime-foundation.md](runtime-foundation.md) is the current foundation
  contract. It summarizes the runtime lines, run events, task contract,
  convergence, RunEvidence, RunResult, context, capability, temporary
  artifacts, and next foundation work.
- [architecture.md](architecture.md) is the higher-level architecture sketch
  for the sidecar, desktop shell, unified terminal, and agent strategy layer.
- [versioning.md](versioning.md) defines the product release version and
  independent compatibility-version boundaries.
- [persistence-model.md](persistence-model.md) describes operational data
  ownership and the JSON-to-SQLite direction.

## Task Runtime

- [task-model.md](task-model.md) describes Task, Plan, Step, Trace, Recovery,
  Template, Task Contract, and route/capability relationships.
- [run-artifacts.md](run-artifacts.md) describes shared temporary artifacts
  across ToolTasks in one Run.
- [automation-runtime.md](automation-runtime.md) describes Automation as a
  trigger layer that creates normal Tasks/Runs instead of a separate execution
  engine.

## Context Runtime

- [context-runtime.md](context-runtime.md) describes context selection,
  trust/source boundaries, snapshots, memory scope, and phase-aware context.

## Capability Runtime

- [capability-runtime.md](capability-runtime.md) is the main capability
  contract document for built-in tools, permissions, confirmation, plugins,
  and cross-platform behavior.
- [capability-router.md](capability-router.md) describes model route proposals
  and capability validation.
- [tool-protocol.md](tool-protocol.md) records the lower-level tool-call
  protocol, temporary-file boundary, and code-write protocol.
- [tool-result-risks.md](tool-result-risks.md) records advisory tool-result
  risk evidence and how it reaches RunResult.

## Extensions And External Providers

- [plugin-system.md](plugin-system.md) describes the early extension contract,
  external plugin direction, Capability Packs, and plugin boundaries.
- [capability-packs.md](capability-packs.md) describes global user-data-level
  method skills, task templates, context packs, and tool adapter drafts.
- [capability-governance.md](capability-governance.md) is the current focused
  note for AI-built capability governance and the boundary between method
  skills and executable tool adapters.
- [mcp-services.md](mcp-services.md) describes MCP service lifecycle,
  connection/protocol state, probing, diagnostics, and capability exposure.
- [document-draft-runtime.md](document-draft-runtime.md) describes the document
  draft helper layer for long document generation.

## Experience, Evaluation, And Evolution

- [experience-runtime.md](experience-runtime.md) describes Experience Sample
  and Experience Digest as the layer between Runbook evidence and replay.
- [evaluation.md](evaluation.md) anchors local replay/evaluation plus
  `evaluation_fixture.v1` and `evaluation_report.v1` as engineering
  capabilities, not a separate benchmark product.
- [skill-evolution.md](skill-evolution.md) describes Replay Fixture, Skill
  Candidate, Replay Result, and manual Promotion.

## Placement Rules

- Put cross-layer summaries in `runtime-foundation.md`; move detailed behavior
  into the layer-specific document.
- Put executable tool/provider boundaries in `capability-runtime.md` or an
  extension document, not in Skill Evolution.
- Put model-context selection, compression, and memory scope in
  `context-runtime.md`.
- Put learning-from-runs behavior in `experience-runtime.md` first; only move
  to `skill-evolution.md` after replay/evaluation evidence matters.
- Avoid adding a new document for a single rule unless it is likely to become a
  stable extension point.
