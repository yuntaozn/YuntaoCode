# YuntaoCode

**Local-First AI Task Runtime**

YuntaoCode is a local-first AI task execution foundation for developers, education, and engineering work.

Rather than building yet another AI chat application, YuntaoCode focuses on making local tasks plannable, executable, pausable, recoverable, verifiable, and auditable.

Its current open-source goal is to make three execution foundations and one evidence-based experience layer explicit for AI working on real local tasks:

* **Task Runtime**: task state, plans, steps, execution, verification, recovery, and results.
* **Context Runtime**: context selection, compression, evidence boundaries, long-term memory, and a context ledger.
* **Capability Runtime**: tools, permissions, plugins, capability contracts, and local execution boundaries.
* **Experience Layer**: turns real task records into Experience Samples, Digests, and Replay Fixtures for later evaluation and capability improvement.

---

## Why YuntaoCode

YuntaoCode did not start as a product plan.

It emerged naturally from years of exploring AI engineering practices.

Instead of focusing on models themselves, we became increasingly interested in the challenges surrounding them:

* How should context be managed?
* How can long-term memory be organized?
* How can AI use tools to complete real tasks?
* How can task execution become observable, recoverable, and auditable?
* How can AI run reliably in local environments?
* How can systems remain extensible over time?

As these questions were gradually addressed, a local Runtime architecture centered on tasks began to take shape.

YuntaoCode is the result of that evolution.

It is not an answer to what the future AI terminal should look like, but an ongoing exploration.

---

## Key Features

### Runtime Foundation

YuntaoCode is not built around a tool checklist. It is organized around three execution runtime lines that can evolve over time, plus an evidence-based experience layer:

```text
Task Runtime
  Manages user goals, execution state, plans, steps, trace, verification, and recovery

Context Runtime
  Manages task context, evidence, summaries, memory, and validity boundaries

Capability Runtime
  Manages tool capabilities, permissions, confirmations, local Capability Packs, and external integrations

Experience Layer
  Turns task records into Experience Samples, Digests, and Replay Fixtures for later evaluation and capability improvement
```

The first three lines define how tasks run. The Experience Layer preserves evidence and lessons without registering AI-generated code by default or bypassing Runtime permission, verification, and manual confirmation boundaries. The model may help understand and execute tasks, but the Runtime owns state, permission boundaries, evidence, and completion checks.

### Task First

YuntaoCode treats each request as a manageable task instead of a plain chat turn:

* Task: user goal and runtime context
* Plan: visible and executable plan
* Step: current step, status, tool hints, and result
* Trace: model output, tool calls, confirmations, errors, and recovery records
* Result: final answer, change summary, verification, and remaining risks

### Local First

* Local file access
* Local code execution
* Local document processing
* User-controlled data ownership

### Capability Collaboration

Built-in capabilities include:

* Filesystem
* Shell
* Git
* Document Processing
* Conversation Attachments
* Web Access
* Preview / Visual Debug
* Memory

Tools are capability units for task execution. Local Capability Packs should first capture method skills, task templates, and context packs; stricter tool adapters or plugins are needed only when a new execution capability is truly required. Tools themselves are not the product boundary; they should enter the runtime through Capability Contracts.

### Long-Term Memory

* Automatic memory extraction
* Relevance-based retrieval
* Context compression
* Conversation history management

### Multi-Model Support

Compatible with OpenAI-style APIs:

* OpenAI
* Ollama
* Qwen
* Volcano Ark
* Volcano Agent Plan (OpenAI Compatible)
* Other OpenAI-compatible providers

### Recoverable Execution

* Task plans and stage transitions
* Tool calls, confirmations, and errors
* Pre-write backups and result verification
* Foundations for task pause, resume, replay, and audit

---

## Architecture Overview

```text
             YuntaoCode Runtime Foundation

 ┌──────────────────────────────┐
 │ runtime/core                 │
 └──────────────┬───────────────┘
                │

    ┌───────────┼───────────┐

    ▼           ▼           ▼

 Task       Context     Capability
 Runtime    Runtime     Runtime

    │           │           │

    └───────────┼───────────┘
                ▼

        Agent Strategy / Policy

                │
                ▼

        Tools / Plugins / MCP

                │

         Model Providers

 OpenAI / Ollama / Qwen / Ark
```

The Python Runtime is the core of the system.

The Tauri desktop application is only one possible interface layer. The Runtime itself can operate independently.

The current implementation already includes tool calling, plan generation, stage progression, confirmation, pre-write backups, execution records, and experience sample export. The next focus is to consolidate these capabilities into clearer Task, Context, and Capability Runtime foundations plus an evidence-based Experience Layer.

The Agent Runtime strategy layer lives in `runtime/agent_strategy/`. It owns intent classification, internal profiles, planning policy, stage prompts, and execution-plan lifecycle helpers so that `conversation_runner.py` can remain an orchestration layer.

Start from the documentation map in [docs/README.md](docs/README.md). The core foundation contract is [docs/runtime-foundation.md](docs/runtime-foundation.md), the Task / Context / Capability lines are described in [docs/task-model.md](docs/task-model.md), [docs/context-runtime.md](docs/context-runtime.md), and [docs/capability-runtime.md](docs/capability-runtime.md), and the Experience Layer is described in [docs/experience-runtime.md](docs/experience-runtime.md).

---

## Repository Mirrors

* GitHub main repository: [https://github.com/yuntaozn/YuntaoCode](https://github.com/yuntaozn/YuntaoCode)
* Gitee mirror for China access: [https://gitee.com/yuntaozn/YuntaoCode](https://gitee.com/yuntaozn/YuntaoCode)

The Gitee repository is mainly provided for faster cloning and downloads in China. Issues, pull requests, and long-term collaboration should preferably use GitHub.

---

## Quick Start

### Clone Repository

GitHub:

```bash
git clone https://github.com/yuntaozn/YuntaoCode.git

cd YuntaoCode
```

Gitee mirror:

```bash
git clone https://gitee.com/yuntaozn/YuntaoCode.git

cd YuntaoCode
```

### Install Dependencies

```bash
python -m pip install -r requirements.txt
```

If you only need the core runtime and test dependencies:

```bash
python -m pip install -e ".[dev]"
```

### Start Runtime

```bash
python -m runtime.app \
    --host 127.0.0.1 \
    --port 8765
```

Open your browser:

```text
http://127.0.0.1:8765
```

### Build Desktop Application

```bash
cd desktop-shell

npm ci

npm run build:windows
```

---

## Development & Verification

Before submitting changes, run at least:

```bash
python -m pip install -e ".[dev]"
pytest
python scripts/smoke_core.py
```

Desktop frontend checks:

```bash
npm --prefix desktop-shell ci
npm --prefix desktop-shell run build:ui
node --check desktop-shell/src/main.js
node --check runtime/panel/static/panel.js
node --check runtime/panel/static/settings.js
node --check runtime/panel/static/plugins.js
node --check runtime/panel/static/i18n.js
```

Tauri shell check:

```bash
powershell -ExecutionPolicy Bypass -File scripts/prepare_tauri_check.ps1
cargo check --manifest-path desktop-shell/src-tauri/Cargo.toml
```

`cargo check` needs the Tauri `externalBin` and Windows icon paths to exist. The script above creates a check-only sidecar placeholder and verifies the icon path. Release packaging still uses `npm run build:windows` to build the real sidecar.

The desktop app icon lives at `desktop-shell/src-tauri/icons/icon.ico`. Commit the real `.ico` file; the check script only creates a temporary icon when that file is missing.

On Windows, if `python` is not available on PATH, use Python Launcher:

```powershell
python -m runtime.app --host 127.0.0.1 --port 8765
```

---

## Extension Guide

### Understand the Task Model

Before contributing a new capability, start with the documentation map in [docs/README.md](docs/README.md), then follow the Task, Context, Capability, Experience, plugin, or MCP document that matches the change.

At this stage, the project does not prioritize piling up application scenarios.
More valuable contributions are changes that:

* make task state clearer;
* make plans, steps, and tool results easier to test;
* make failure recovery, write rollback, and execution audit more stable;
* turn a tool or skill into a reusable task capability.

### Add a New Tool

Create a module under `runtime/skills/`:

```python
from runtime.tool_registry import ToolRegistry, ToolSpec

def my_tool_handler(args, context):
    return {"result": "..."}

def register_my_tools(registry: ToolRegistry):
    registry.register(
        ToolSpec(
            id="my.tool",
            name="My Tool",
            description="...",
            input_schema={}
        ),
        my_tool_handler,
    )
```

### Add a New API

Create a Handler under `runtime/api/` and register it in `runtime/app.py`.

### Capability Packs and Plugin Contract

The current version provides capability-source management. It groups built-in tools by ID prefix, such as `filesystem`, `code`, `shell`, `git`, `web`, and `preview`, and displays enablement and dependency status. These groups are not installed third-party plugins.

A Plugin in YuntaoCode is a versioned, distributable package that may contain Skills, Capability Packs, MCP/CLI provider descriptors, and future controlled extensions. Installation, review, enablement, and execution are independent states. The current foundation defines manifest and local installation-state contracts only; dynamic loading, a marketplace, and remote auto-update remain out of scope.

See [docs/capability-packs.md](docs/capability-packs.md) for local Capability Packs and the extension contract draft in [docs/plugin-system.md](docs/plugin-system.md). The repository does not include external plugin sample directories at this stage; capability extension examples stay in documentation so experimental artifacts are not mistaken for built-in features.

AI may help create local Capability Packs. By default, it should first distill method skills: prompts, steps, counterexamples, and verification checklists under `capability-packs/items/<pack-id>/` in the user data directory. Tool adapter drafts must stay isolated. After completion, test/dependency summaries plus one manual confirmation can move the draft into a future controlled registration or enablement path. See [docs/capability-governance.md](docs/capability-governance.md).

### MCP Services Directory

External MCP service source copies, service-level reference material, and
integration notes live under `mcp-services/`. For example,
`mcp-services/blender-mcp/` is a local reference copy of the Blender MCP
service. It is not a built-in `runtime.skills.*` module and is not imported by
the Runtime automatically.

MCP service enablement, connection state, permissions, logs, tool discovery, and
capability bindings remain owned by the MCP Service Manager. The default
Blender example uses the explicit `uvx blender-mcp` package runner and connects
only after the user enables and starts the service.

---

## Open Source Collaboration

Contributions are welcome. Please read:

* [AGENTS.md](AGENTS.md)
* [CONTRIBUTING.md](CONTRIBUTING.md)
* [SECURITY.md](SECURITY.md)
* [CHANGELOG.md](CHANGELOG.md)
* [Documentation map](docs/README.md)
* [Versioning and release rules](docs/versioning.md)

Do not commit API keys, local conversation data, user data, packaged binaries, or `node_modules`.

---

## Philosophy

YuntaoCode is not trying to become the most powerful AI assistant.

Instead, we focus on:

* whether the Task lifecycle is clear;
* whether execution is observable, pausable, and recoverable;
* whether tool calls have boundaries, confirmations, and records;
* whether results can be verified, rolled back, and reviewed;
* whether the task execution system still works after replacing the model.

We believe that models will continue to change, but a stable, open, and extensible Task Runtime will remain valuable.

---

## Roadmap

### Phase 1: Runtime Foundation

Goal: stabilize the Task, Context, Capability, and Evidence foundations. YuntaoCode's value is not the number of tools it ships with, but whether tasks can be executed, observed, recovered, verified, and reviewed.

* [x] Task Model foundation: ProductTask, Run, ToolTask, state, results, and lineage
* [x] Run Lifecycle foundation: running, waiting_confirmation, paused, resumed, completed, failed, stopped
* [x] Task Trace foundation: RunEvent, canonical event_name, tool calls, confirmations, errors, verification, results, and final-answer previews
* [x] Run Recovery foundation: pause, resume, Runbook, and Replay Request
* [x] Recovery Context foundation: Checkpoint, Context Snapshot, and explicitly started Replay Runs
* [x] Task Audit foundation: RunEvidence, RunWorkbench, run audit summary, task-history UI, and state-transition tests
* [x] Context Runtime minimum loop: Context Pack / Ledger, context hygiene, task lineage, memory boundaries, visual evidence, and recovery snapshots
* [x] Capability Runtime minimum loop: ToolSpec metadata, Capability Preflight v2, permissions, confirmations, artifacts, providers, and verification evidence
* [x] Automation Runtime foundation: triggers, task templates, concurrency boundary, configuration UI, and normal Run conversion contract
* [x] MCP Service Lifecycle foundation: service configuration, start / restart actions, protocol connection, tool discovery, diagnostics, and capability binding
* [x] Runtime Extension Contract foundation: plugin / MCP / CLI / Capability Pack boundaries, permissions, dependencies, and task artifact conventions

### Phase 2: Experience And Evaluation Loop

Goal: let YuntaoCode learn from real task evidence by producing auditable samples, replayable fixtures, and comparable evaluation reports. This does not mean every task becomes a skill, and it is not a public benchmark or data-collection system.

* [x] RunEvidence: a unified fact view for one run
* [x] Experience Runtime foundation: Experience Sample, Experience Digest, and the data boundary between Runbook and Replay
* [x] Evaluation Fixture / Report foundation: selected RunEvidence can become a fixture and be compared with another run
* [x] Experience Sample Export: manually export an experience sample from selected RunEvidence
* [ ] Experience Sample file import, validation, annotation, and comparison
* [ ] Replay Runner: replay selected fixtures through the normal Task Runtime
* [ ] Deeper Evaluation Reports: compare models, providers, runtime versions, capability availability, and failure causes
* [ ] Experience Digestion: summarize stable patterns, applicability boundaries, and counterexamples from multiple samples

### Phase 3: Skill / Capability Evolution

Goal: let AI propose skill candidates, task templates, or capability drafts from experience and evaluation evidence, then prove them through isolation, replay, verification, and explicit user enablement. A Skill is not just a prompt note, and a Plugin is not trusted code by default; both must earn trust through the evidence chain.

* [ ] Experience Digest to Skill Candidate flow
* [ ] Task Template Candidate: reusable task structure learned from successful runs and failure counterexamples
* [ ] AI-built Capability / Plugin Draft isolation, test summary, and enablement boundary
* [ ] Candidate Replay: candidates must pass selected fixture replay/evaluation
* [ ] Manual Promotion: users explicitly enable promoted capabilities
* [ ] Capability versioning, compatibility, rollback, and deprecation policy

### Phase 4: Self-Iteration Lab

Goal: let YuntaoCode help improve its own Runtime inside isolated clones, test suites, diagnostic reports, and human merge boundaries. This is controlled self-iteration, not direct model edits to trusted runtime code.

* [ ] Runtime Self-Diagnostic: locate foundation issues from failed tasks, diagnostics, and evaluation reports
* [ ] Runtime Sandbox / clone: generate, test, and verify improvement proposals in an isolated environment
* [ ] Fixture Regression Suite: use selected task fixtures to detect runtime regressions
* [ ] Source Update Proposal: AI-generated code-change proposals with evidence, test results, and risk summaries
* [ ] Human Merge Boundary: human review, merge, release, and rollback
* [ ] Optional ecosystem: plugin indexes, signed distribution, team sync, and enterprise deployment only after the evolution loop is stable

---

## Education & Research

YuntaoCode can also be used for:

* AI Agent Training
* MCP Education
* RAG Experiments
* Local LLM Deployment
* Software Engineering Courses
* AI Engineering Practice

---

## Project Status

Current Development Version: **0.1.0**

Status: **Active Development**

Before v1.0:

* APIs may change
* Plugin interfaces may evolve
* Runtime architecture will continue to improve

---

## License

Apache License 2.0

See the LICENSE file for details.
