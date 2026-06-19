# Experience Runtime

Experience Runtime is the layer between raw task evidence and Skill Evolution.
It lets YuntaoCode learn from real runs without turning every run into a skill,
prompt rule, plugin, or runtime patch.

## Position

YuntaoCode should keep these layers separate:

```text
Task Runtime
  Executes user goals, records plans, tool events, verification, and RunResult.

Context Runtime
  Selects, cleans, compresses, and scopes facts that enter model context.

Capability Runtime
  Manages tools, MCP services, permissions, confirmations, and capability health.

Experience Runtime
  Extracts reviewed task experience from Runbook/RunResult evidence.

Evaluation / Skill Evolution
  Replays selected fixtures and promotes only evidence-backed reusable patterns.
```

Experience Runtime is not another execution controller. It does not decide the
current task strategy, bypass permission checks, or make generated code trusted.

## Why This Layer Exists

Skill Evolution is useful only when it is backed by evidence. Jumping directly
from "a task happened" to "create a skill" creates three problems:

- normal task traces become hidden prompt rules;
- failed or machine-specific behavior can pollute later tasks;
- users may think an exported sample is already a reliable capability.

Experience Runtime keeps the learning path slower and clearer:

```text
Runbook
  -> Experience Sample
  -> Experience Digest
  -> Replay Fixture
  -> Evaluation Result
  -> Skill Candidate
  -> Skill Promotion
```

The first two records preserve and summarize experience. They do not grant new
runtime capability.

## Concepts

### Experience Sample

An Experience Sample is a compact, portable task experience extracted from one
Runbook. It includes:

- source run and task lineage;
- original goal;
- task contract;
- RunResult facts;
- verification evidence;
- risks and unresolved issues.

It excludes full model transcripts, full tool outputs, file contents, API keys,
and complete Runbook logs by default.

### Experience Digest

An Experience Digest is a reviewed summary across one or more samples. It can
describe:

- a repeated task pattern;
- when the pattern applies;
- which capabilities were useful;
- what evidence is required;
- common failure modes.

A digest is still not an active skill. It is a candidate input for evaluation
or Skill Evolution.

### Replay Fixture

A Replay Fixture is a testable sample derived from experience. It should be
stable enough to run against future runtime, model, provider, or capability
changes.

## Current 0.1 Boundary

For 0.1, this layer should stay intentionally small:

- manual export only;
- user-selected runs only;
- no automatic collection of all tasks;
- no remote upload;
- no central sample service;
- no automatic skill generation;
- no automatic skill promotion;
- no in-process execution of AI-generated code;
- no hidden prompt injection from exported samples.

The current compatibility export may still be named "skill sample" in older
API paths, but the stable concept is an **Experience Sample plus Replay
Fixture**.

## Data Contract

The initial pure schemas live in `runtime/core/experience.py`:

- `ExperienceSample`
- `ExperienceDigest`

Schema versions:

- `experience_sample.v1`
- `experience_digest.v1`

These versions are independent from the product release version, plugin
manifest versions, and Skill Evolution schema versions.

## Relationship To Context

Experience is not memory by default.

An exported sample or digest must not silently enter the next model context.
If a future feature wants to use a digest as model guidance, it should go
through Context Runtime with explicit source, trust, freshness, and workspace
scope.

## Relationship To Capability

Experience can mention capability IDs and failure modes, but it cannot enable
or disable capabilities. Capability availability, MCP health, permissions, and
confirmation gates remain owned by Capability Runtime.

## Relationship To Skill Evolution

Skill Evolution starts after enough experience and replay evidence exists.

An Experience Digest may become a Skill Candidate draft, but only Replay
Results and a manual Promotion decision can make a candidate user-enabled. See
[skill-evolution.md](skill-evolution.md).

## Future Work

Useful next steps after 0.1:

1. Add a local view for selected Experience Samples.
2. Add an explicit "create digest from selected samples" action.
3. Let Evaluation replay selected fixtures and report regressions.
4. Allow manually promoted digests to become Skill Candidate drafts.
5. Keep every promotion reversible, inspectable, and replay-testable.
