# Local Replay And Evaluation Direction

This document anchors the evaluation direction for YuntaoCode. It is a
foundation note, not a product plan for a standalone Local AI Evaluation
platform.

YuntaoCode needs evaluation because it is a Task Runtime. Real task execution
depends on the model, provider, runtime prompts, tool contracts, context
selection, confirmation policy, local environment, and MCP/plugin availability.
Evaluation should help contributors understand that whole system.

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

## Existing Foundations

The current 0.1 work already provides the first pieces:

- **Runbook** records what happened in one Run.
- **Diagnostic Export** explains why a Run behaved differently on a specific
  machine.
- **Experience Sample Export** turns a selected Run into a reviewed sample and
  a small Replay Fixture.
- **Replay Fixture** can later become a stable sample for regression testing.
- **RunResult** provides runtime-owned facts instead of relying on assistant
  prose.

The direction is:

```text
Run
  -> Diagnostic Export
  -> Experience Sample Export
  -> Replay Fixture
  -> Evaluation Report
  -> Skill Evolution
```

This chain should stay explicit. Diagnostic packages are for debugging.
Experience samples are for reviewed learning and replay. Evaluation reports
compare behavior. Skill Evolution decides whether a reusable capability has
enough evidence to be promoted.

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

## Metrics Direction

Early reports should favor facts that already exist in Run events and
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

For 0.1, evaluation remains a direction anchor:

- manual export only;
- local files only;
- user-selected samples only;
- no automatic collection of all tasks;
- no automatic upload;
- no public leaderboard;
- no central sample service;
- no new database dependency;
- no automatic skill promotion;
- no trusted execution of AI-generated code.

The current priority is to keep diagnostic export, Experience Sample export,
Runbook, Replay Fixture, and RunResult coherent enough that evaluation can be
added later without changing the foundation again.

## Future Shape

A later implementation can add a small local evaluation layer:

```text
runtime/evaluation/
  fixtures.py
  runner.py
  metrics.py
  report.py
```

That layer should replay selected fixtures through normal Task Runtime
execution and produce local JSON or Markdown reports. It should not bypass
normal capability contracts, permission checks, context hygiene, or result
verification.

UI and automation can come after the command-line or internal API path proves
useful in real project testing.

## Relationship To Skill Evolution

Evaluation and Skill Evolution are related but not the same.

Evaluation asks whether a runtime/model/provider combination can complete a
selected task fixture.

Skill Evolution asks whether repeated evidence is strong enough to turn a
task pattern into a reusable skill candidate and, eventually, a manually
promoted skill.

Both should use Replay Fixture evidence. Neither should trust model claims
without runtime-owned RunResult facts.
