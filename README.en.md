# YuntaoCode

**Local-First AI Runtime for Developers, Education and Engineering**

YuntaoCode is a Local-First AI Runtime focused on context management, long-term memory, tool collaboration, and local execution.

Rather than building yet another AI chat application, YuntaoCode explores how AI systems can operate, evolve, and collaborate with tools in a long-running local environment.

---

## Why YuntaoCode

YuntaoCode did not start as a product plan.

It emerged naturally from years of exploring AI engineering practices.

Instead of focusing on models themselves, we became increasingly interested in the challenges surrounding them:

* How should context be managed?
* How can long-term memory be organized?
* How can AI effectively use tools?
* How can different capabilities work together?
* How can AI run reliably in local environments?
* How can systems remain extensible over time?

As these questions were gradually addressed, an independent Runtime architecture began to take shape.

YuntaoCode is the result of that evolution.

It is not an answer to what the future AI terminal should look like, but an ongoing exploration.

---

## Key Features

### Local First

* Local file access
* Local code execution
* Local document processing
* User-controlled data ownership

### Tool Collaboration

Built-in capabilities include:

* Filesystem
* Shell
* Git
* Document Processing
* Web Access
* Memory

Additional tools can be integrated through the plugin system.

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

### Evolution-Oriented Design

* Tool execution tracking
* Result recording
* Experience accumulation
* Foundations for future workflow optimization and self-improvement mechanisms

---

## Architecture Overview

```text
                YuntaoCode Runtime

 ┌──────────────────────────────┐
 │ Conversation Runner          │
 └──────────────┬───────────────┘
                │

    ┌───────────┼───────────┐

    ▼           ▼           ▼

 Context     Memory      Tools

                             │

          ┌──────────────────┼──────────────────┐

          ▼                  ▼                  ▼

      Filesystem          Shell               Git

                             ...

                │

         Model Providers

 OpenAI / Ollama / Qwen / Ark
```

The Python Runtime is the core of the system.

The Tauri desktop application is only one possible interface layer. The Runtime itself can operate independently.

---

## Quick Start

### Clone Repository

```bash
git clone https://github.com/yuntaozn/YuntaoCode.git

cd YuntaoCode
```

### Install Dependencies

```bash
pip install -r requirements.txt
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

npm install

npm run build:windows
```

---

## Extension Guide

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

---

## Philosophy

YuntaoCode is not trying to become the most powerful AI assistant.

Instead, we focus on:

* Runtime stability
* Tool collaboration
* Long-term memory organization
* Local execution and user control
* Continuous evolution

We believe that models will continue to change, but a stable, open, and extensible Runtime will remain valuable.

---

## Roadmap

### v0.1

* [x] Local AI Chat
* [x] Tool Calling
* [x] Filesystem
* [x] Shell
* [x] Git
* [x] Memory

### v0.2

* [ ] MCP Support
* [ ] Plugin System
* [ ] Multi-Workspace
* [ ] Tool Marketplace

### v0.3

* [ ] Local Knowledge Base
* [ ] Workflow Engine
* [ ] Autonomous Tasks

### v1.0

* [ ] Enterprise Deployment
* [ ] Team Collaboration
* [ ] Plugin Marketplace

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

Current Version: **0.1.0**

Status: **Active Development**

Before v1.0:

* APIs may change
* Plugin interfaces may evolve
* Runtime architecture will continue to improve

---

## License

Apache License 2.0

See the LICENSE file for details.
