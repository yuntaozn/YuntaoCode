# Experience Runtime

Experience Runtime is the 0.1 layer for exporting reviewed evidence from real
runs without turning every run into a skill, prompt rule, plugin, or runtime
patch.

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
  Extracts reviewed task experience from RunEvidence and RunResult evidence.
```

Experience Runtime is not another execution controller. It does not decide the
current task strategy, bypass permission checks, or make generated code trusted.

## Why This Layer Exists

Jumping directly from "a task happened" to "create a reusable capability"
creates three problems:

- normal task traces become hidden prompt rules;
- failed or machine-specific behavior can pollute later tasks;
- users may think an exported sample is already a reliable capability.

Experience Runtime keeps the learning path slower and clearer:

```text
RunEvidence
  -> Runbook
  -> Experience Sample
  -> Experience Digest
  -> Replay Fixture
  -> Evaluation Result
```

The first two records preserve and summarize experience. They do not grant new
runtime capability.

## Concepts

### Experience Sample

An Experience Sample is a compact, portable task experience extracted from one
reviewed RunEvidence/Runbook view. It includes:

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

A digest is still not an active skill and does not change runtime behavior.

### Replay Fixture

A Replay Fixture is a testable sample derived from experience. It should be
stable enough to compare selected runtime, model, provider, or capability
changes when the user explicitly exports it.

## Current 0.1 Boundary

For 0.1, this layer should stay intentionally small:

- manual export only;
- user-selected runs only;
- no automatic collection of all tasks;
- no local sample registry or sample workbench in 0.1;
- no remote upload;
- no central sample service;
- no automatic skill generation;
- no automatic skill promotion;
- no in-process execution of AI-generated code;
- no hidden prompt injection from exported samples.

The current compatibility export may still be named "skill sample" in older
API paths, but the stable concept is an **Experience Sample plus Replay
Fixture**.

Experience material is exported as explicit local artifacts instead of being
saved into a runtime-managed sample registry. This keeps the 0.1 surface small
and reviewable.

## Data Contract

The initial pure schemas live in `runtime/core/experience.py`:

- `ExperienceSample`
- `ExperienceDigest`

Schema versions:

- `experience_sample.v1`
- `experience_digest.v1`

These versions are independent from the product release version and plugin
manifest versions.

## Relationship To Context

Experience is not memory by default.

An exported sample or digest must not silently enter the next model context.
Any use of a digest as model guidance must go through Context Runtime with
explicit source, trust, freshness, and workspace scope.

## Relationship To Capability

Experience can mention capability IDs and failure modes, but it cannot enable
or disable capabilities. Capability availability, MCP health, permissions, and
confirmation gates remain owned by Capability Runtime.
