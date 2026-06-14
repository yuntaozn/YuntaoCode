# Skill Evolution

Skill Evolution is the path from real task experience to a reusable skill. It
uses Runbook and Replay evidence, but it is not the same as source update,
plugin auto-loading, or model self-modification.

The goal is to let YuntaoCode learn from completed work without letting the
model directly change trusted runtime code.

```text
Runbook
  -> Replay Fixture
  -> Skill Candidate
  -> Skill Replay Result
  -> Skill Promotion
  -> User-enabled Skill
```

## Current 0.1 Boundary

This layer is a foundation contract only.

- It defines data structures and state transitions.
- It does not generate skill code automatically.
- It does not register plugins or edit `runtime/skills/`.
- It does not execute untrusted code in the main Runtime process.
- It requires explicit user approval before a tested candidate can become an
  enabled skill.

Source updates and desktop client updates are separate concerns. They update
the product code. Skill Evolution improves reusable task capability through
local evidence and replay verification.

## Concepts

### Runbook

A Runbook is the runtime-owned audit artifact for one Run. It records task
contract, capability snapshot, plan, tool steps, status timeline, result,
risks, failures, verification evidence, checkpoints, and replay request.

Runbook is evidence. It is not itself a skill.

### Replay Fixture

A Replay Fixture is a stable test sample extracted from a Runbook. It captures:

- source run and task lineage;
- original goal;
- task contract;
- expected artifacts;
- verification evidence from the original task.

Fixtures are how historical tasks become tests for future skills.

### Skill Candidate

A Skill Candidate is a proposed reusable capability inferred from one or more
Runbooks. It may describe:

- the task pattern it handles;
- capability IDs it expects;
- draft manifest data;
- permission and execution boundaries;
- source Runbooks and replay fixtures.

A candidate is not executable by default. It is a draft until replay results
prove that it works inside the current runtime boundary.

### Skill Replay Result

A Skill Replay Result records what happened when a candidate was tested against
one fixture. The status can be:

- `passed`
- `failed`
- `partial`
- `blocked`

Promotion should require replay evidence, not model claims.

### Skill Promotion

A Skill Promotion is a manual decision to make a tested candidate available as
a user skill. Promotion targets should stay outside built-in runtime code, such
as a future user-skill directory or controlled plugin root.

## Candidate State Machine

```text
draft
  -> testing
  -> tested
  -> enabled
  -> disabled

draft/testing/tested
  -> rejected
  -> archived

enabled/disabled
  -> testing
```

Important boundaries:

- `draft` means the candidate is only a proposal.
- `testing` means Replay is evaluating it.
- `tested` means replay evidence exists.
- `enabled` requires a manual promotion decision.
- `disabled` preserves the candidate and evidence without exposing it as an
  active skill.
- `archived` is terminal.

## Data Contract

The code skeleton lives in `runtime/core/skill_evolution.py`.

Schema versions:

- `skill_candidate.v1`
- `replay_fixture.v1`
- `skill_replay_result.v1`
- `skill_promotion.v1`

These versions are independent from the product release version and from plugin
manifest versions.

## Safe Evolution Flow

1. A task completes or partially completes.
2. The Runtime creates a Runbook.
3. The user or model proposes that the Runbook contains a reusable pattern.
4. The Runtime creates a Skill Candidate draft.
5. One or more Replay Fixtures are extracted from Runbooks.
6. The candidate is tested against fixtures through normal Task Runtime runs.
7. Replay Results are recorded with evidence and failures.
8. If readiness checks pass, the Runtime may propose Skill Promotion.
9. The user confirms promotion.
10. The enabled skill remains disableable and replay-testable.

## Non-Goals

- No automatic edits to `runtime/skills/`.
- No in-process execution of AI-generated plugin code.
- No remote marketplace or signed distribution.
- No unattended promotion from model output alone.
- No replacement for product source update.

## Relationship To Plugin Drafts

AI-built plugin drafts remain isolated under a user-controlled local data
directory. Skill Evolution can use plugin drafts as candidate artifacts in the
future, but a candidate must still pass replay tests and manual promotion before
it becomes enabled.

Plugin manifests describe capabilities. Skill Evolution describes how a
capability earns trust through real task evidence.

## 0.1 Implementation Target

For 0.1, the useful minimum is:

- data structures for candidates, fixtures, replay results, and promotions;
- Runbook-to-fixture extraction;
- on-demand sample export from a selected Run, without storing the full Runbook;
- readiness summary from replay results;
- documentation in architecture and plugin docs;
- no automatic registration path.

Later versions can add persistence, UI, and controlled execution boundaries.

## Skill Sample Export

Skill sample export is the first practical way to collect replay fixtures
across test machines without building a central service too early.

The export action should:

- start from a specific Run selected by the user;
- build a Runbook view in memory;
- export only a portable Replay Fixture and source summary;
- avoid full Runbook persistence;
- avoid file contents, model transcripts, and raw tool outputs by default;
- mark the export as manually generated and not remotely submitted.

The exported JSON is useful for sharing regression samples between local test
machines. Users must still review it before sharing because goals, paths,
artifact names, and task contracts may contain private information.

Remote sample submission is intentionally out of scope for 0.1. A future
service should add explicit consent, preview, redaction, provenance, and delete
controls before accepting user samples.

## Not A Diagnostic Export

Skill sample export is different from a diagnostic package.

- Skill sample export produces a small Replay Fixture for future Skill
  Evolution testing.
- Diagnostic export helps debug why a task behaved differently on another
  machine. It may include runtime version, environment summary, tool and MCP
  status, compact Runbook evidence, recent event summaries, and sanitized
  settings.

Do not use Skill Evolution fixtures as bug reports, and do not use diagnostic
packages as automatic replay fixtures.

## Relationship To Evaluation

Evaluation is the engineering layer that can replay selected fixtures across
models, providers, runtime versions, prompts, and local environments. It helps
answer whether a task still works and why it failed or regressed.

Skill Evolution starts after that evidence exists. A reusable skill should not
be promoted because one model described a pattern as useful; it should be
promoted only after replay and evaluation provide enough runtime-owned evidence.

For 0.1, evaluation is documented as a direction anchor in
[evaluation.md](evaluation.md). Skill Evolution should depend on Replay Fixture
and RunResult facts, not on a separate benchmark system or a public leaderboard.
