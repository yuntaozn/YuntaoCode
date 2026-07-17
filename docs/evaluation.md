# Local Evaluation Foundation

This document records the 0.1 local evaluation foundation for YuntaoCode. It
is not a product plan for a standalone Local AI Evaluation platform.

YuntaoCode needs evaluation because it is a Task Runtime. Real task execution
depends on the model, provider, runtime prompts, tool contracts, context
selection, confirmation policy, local environment, and MCP/plugin availability.
Evaluation records help contributors understand that whole system.

## Position

Evaluation belongs inside YuntaoCode as a core engineering capability.

It should answer YuntaoCode-specific questions:

- Which model or provider is more reliable for this runtime?
- Did a runtime change reduce task success rate?
- Did a prompt or policy change increase repeated tool failures?
- Did a task really produce and verify the expected artifact?
- Was a failure caused by the model, provider, runtime, tool contract, local
  environment, or missing capability?
- Can local models such as Ollama, LM Studio, llama.cpp-backed servers, or
  other OpenAI-compatible providers handle selected task classes?
- How much time, token budget, and tool work did a task need?

It should not become a generic leaderboard or benchmark product.

## 0.1 Foundations

The current 0.1 work already provides the first pieces:

- **Runbook** records what happened in one Run.
- **RunEvidence** is the shared post-run fact view consumed by Runbook,
  diagnostics, Experience Sample export, Replay, and Evaluation.
- **Diagnostic Export** explains why a Run behaved differently on a specific
  machine.
- **Experience Sample Export** turns a selected Run into a reviewed sample and
  a small Replay Fixture.
- **Replay Fixture** is a passive record derived from reviewed evidence.
- **Evaluation Fixture** is a local, manually exported fixture generated from
  RunEvidence for regression/evaluation runs.
- **Evaluation Report** compares one fixture with one RunEvidence view and
  explains pass, partial, failure, or blocked outcomes without replaying the
  task.
- **RunResult** provides runtime-owned facts instead of relying on assistant
  prose.

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

This chain should stay explicit. Diagnostic packages are for debugging.
Experience samples are for reviewed learning and replay. Evaluation reports
compare behavior.

## Evaluation Scope

Evaluation should compare task execution under controlled changes:

- model or API provider;
- model request parameters;
- runtime version;
- prompt or policy version;
- capability availability;
- MCP service configuration;
- local environment differences.

The unit of evaluation is a task fixture, not a single chat prompt. A useful
fixture should include the goal, task contract, expected artifacts, relevant
capability snapshot, verification requirements, and safe replay boundaries.

## Report Facts

0.1 reports favor facts that already exist in Run events and
RunResult:

- final status: success, partial, failure, blocked, stopped;
- target artifact produced or not;
- verification evidence strength;
- tool call count and failed tool call count;
- repeated failure count;
- fallback or strategy-change interventions;
- elapsed time;
- token usage when available;
- local capability or MCP availability gaps;
- deterministic contract failures.

The report should explain why a run passed or failed. A score without evidence
is not useful for this project.

## 0.1 Boundary

For 0.1, evaluation remains local and manual:

- manual export only;
- local files only;
- user-selected samples only;
- selected RunEvidence can be exported as `evaluation_fixture.v1`;
- selected RunEvidence can be compared with a fixture as
  `evaluation_report.v1`;
- selected RunEvidence can be exported as an Experience Sample;
- no local sample registry or sample workbench in 0.1;
- no automatic collection of all tasks;
- no automatic upload;
- no public leaderboard;
- no central sample service;
- no new database dependency;
- no automatic fixture execution;
- no trusted execution of AI-generated code.

The local evaluation modules are intentionally small:

```text
runtime/evaluation/
  fixtures.py
  reports.py
```
