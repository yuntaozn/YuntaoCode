# YuntaoCode

**Local-First AI Task Runtime**

YuntaoCode is a local-first AI task execution foundation for developers, education, and engineering work.

Rather than building yet another AI chat application, YuntaoCode focuses on making local tasks plannable, executable, pausable, recoverable, verifiable, and auditable.

Its current open-source goal is to make three foundations explicit for AI working on real local tasks:

* **Task Runtime**: task state, plans, steps, execution, verification, recovery, and results.
* **Context Runtime**: context selection, compression, evidence boundaries, long-term memory, and a context ledger.
* **Capability Runtime**: tools, permissions, plugins, capability contracts, and local execution boundaries.

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

YuntaoCode is not built around a tool checklist. It is organized around three runtime lines that can evolve over time:

```text
Task Runtime
  Manages user goals, execution state, plans, steps, trace, verification, and recovery

Context Runtime
  Manages task context, evidence, summaries, memory, and validity boundaries

Capability Runtime
  Manages tool capabilities, permissions, confirmations, plugin drafts, and external integrations
```

Together, these layers define the core boundary: the model may help understand and execute tasks, but the Runtime owns state, permission boundaries, evidence, and completion checks.

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
* Memory

Tools are capability units for task execution. Additional tools can be integrated through the plugin system, but tools themselves are not the product boundary; they should enter the runtime through Capability Contracts.

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

The current implementation already includes tool calling, plan generation, stage progression, confirmation, pre-write backups, and execution records. The next focus is to consolidate these capabilities into clearer Task, Context, and Capability Runtime foundations.

The Agent Runtime strategy layer lives in `runtime/agent_strategy/`. It owns intent classification, internal profiles, planning policy, stage prompts, and execution-plan lifecycle helpers so that `conversation_runner.py` can remain an orchestration layer.

See the Task Model draft in [docs/task-model.md](docs/task-model.md), the Context Runtime plan in [docs/context-runtime.md](docs/context-runtime.md), the Capability Runtime plan in [docs/capability-runtime.md](docs/capability-runtime.md), the Document Draft Runtime in [docs/document-draft-runtime.md](docs/document-draft-runtime.md), and the current runtime foundation contract in [docs/runtime-foundation.md](docs/runtime-foundation.md).

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

Before contributing a new capability, read [docs/task-model.md](docs/task-model.md), [docs/context-runtime.md](docs/context-runtime.md), [docs/capability-runtime.md](docs/capability-runtime.md), [docs/document-draft-runtime.md](docs/document-draft-runtime.md), and [docs/runtime-foundation.md](docs/runtime-foundation.md).

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

### Plugins and Plugin Contract

The current version provides built-in plugin capability management. It groups tools by ID prefix, such as `filesystem`, `code`, `shell`, `git`, and `web`, and displays enablement and dependency status.

This is not a plugin marketplace or remote update system. The third-party manifest, dynamic loading, permission declarations, and isolation model remain future foundation work.

See the extension contract draft in [docs/plugin-system.md](docs/plugin-system.md). The repository does not include external plugin sample directories at this stage; capability extension examples stay in documentation so experimental artifacts are not mistaken for built-in features.

AI may help create plugin drafts, but drafts must stay isolated. After completion, test/dependency summaries plus one manual confirmation can move the draft into a future controlled registration or enablement path. See [docs/capability-governance.md](docs/capability-governance.md).

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

Goal: make the Task, Context, and Capability runtime lines clear before expanding the feature list.

* [x] Task Model foundation: ProductTask, Run, ToolTask, state, results, and lineage
* [x] Run Lifecycle foundation: running, waiting_confirmation, paused, resumed, completed, failed, stopped
* [ ] Task Trace: model output, tool calls, confirmations, errors, verification, and final summary
* [x] Run Recovery foundation: pause, resume, Runbook, and Replay Request
* [x] Recovery Context foundation: Checkpoint, Context Snapshot, and explicitly started Replay Runs
* [ ] Deeper Task Recovery: retry, write rollback, and policy-controlled automatic replay execution
* [ ] Task Audit: readable execution records and testable state transitions
* [ ] Context Runtime: context selection, evidence, compression snapshots, and memory boundaries
* [ ] Capability Runtime: capability contracts, permissions, confirmations, artifacts, and verification rules

### Phase 2: Reusable Capabilities

Goal: turn tools into reusable task capabilities.

* [ ] Stable tool protocol and parameter conventions
* [ ] Modular skill registration
* [ ] Runtime Extension Contract: plugin manifest, permissions, dependencies, and task artifact conventions
* [ ] AI-built plugin draft isolation, test summaries, and manual registration confirmation
* [ ] Task-oriented wrappers for document parsing, code analysis, Git, and Shell
* [ ] MCP as an external tool integration path, not the core positioning itself

### Phase 3: Task Templates

Goal: preserve reusable task templates instead of prompt fragments only.

* [ ] Code modification task template
* [ ] Project review task template
* [ ] Document processing task template
* [ ] Paper/research analysis task template
* [ ] Task template import, export, and versioning

### Phase 4: Ecosystem

Goal: expand the ecosystem after the Task Runtime stabilizes.

* [ ] Multi-workspace and long-running tasks
* [ ] Local knowledge base / RAG interfaces
* [ ] Optional plugin index and signed distribution
* [ ] Team sync and enterprise deployment
* [ ] Stable Runtime API and plugin compatibility

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
