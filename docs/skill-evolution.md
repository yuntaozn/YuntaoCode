# Skill Candidate Contracts

This document records the passive 0.1 data contracts for reusable-skill
candidates. It is not a roadmap and not an automatic evolution system.

0.1 keeps these records as local, reviewable artifacts only:

- `ReplayFixture`
- `SkillCandidate`
- `SkillReplayResult`
- `SkillPromotion`

The code skeleton lives in `runtime/core/skill_evolution.py`.

## 0.1 Boundary

These contracts do not:

- generate skill code automatically;
- register plugins or edit `runtime/skills/`;
- execute untrusted code in the main Runtime process;
- inject exported samples into model context;
- promote a candidate from model output alone.

They exist so reviewed Runbook / RunEvidence material can be represented in a
stable schema without changing trusted runtime behavior.

## Data Chain

```text
RunEvidence
  -> Experience Sample
  -> Replay Fixture
  -> Skill Candidate
  -> Skill Replay Result
  -> Skill Promotion
```

In 0.1 this chain is passive. A record may be exported, inspected, tested, or
archived, but it does not make a new capability trusted by itself.

## Concepts

### Replay Fixture

A Replay Fixture is a stable sample extracted from reviewed task evidence. It
captures source run lineage, the original goal, task contract, expected
artifacts, and verification evidence.

### Skill Candidate

A Skill Candidate is a proposed reusable pattern. It may describe the task
pattern, expected capability IDs, permissions, source evidence, and replay
fixtures. It is not executable by default.

### Skill Replay Result

A Skill Replay Result records what happened when a candidate was checked
against one fixture. The status can be `passed`, `failed`, `partial`, or
`blocked`.

### Skill Promotion

A Skill Promotion is a manual record that a tested candidate may be made
available to the user. Promotion is still outside trusted built-in runtime code.

## Current Boundary

- No automatic edits to product source code.
- No in-process execution of AI-generated plugin code.
- No remote marketplace or signed distribution.
- No unattended promotion.
- No replacement for source update, diagnostics, or evaluation reports.

## Relationship To 0.1 Runtime

Experience Sample export and Evaluation Fixture / Report records are the
implemented 0.1 surfaces. Skill Candidate contracts remain schema-level
artifacts and do not change trusted runtime behavior.
