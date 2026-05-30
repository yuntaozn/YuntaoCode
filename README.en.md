# YuntaoCode

**Local-First AI Runtime for Developers, Education and Engineering**

YuntaoCode is an open-source AI runtime evolved from real-world engineering projects.  
It is designed for long-running local AI applications, tool orchestration, memory management, and extensible workflows.

---

## Why YuntaoCode

- Built from years of practical experience: SaaS, knowledge bases, grading systems, robotics, and local AI.
- Models and tools evolve rapidly, but stable runtimes and tool collaboration are the core value.
- Suitable for developers, educational environments, and engineering experiments.

---

## Key Features

- **Local First**: All operations (files, code, documents) run locally; user data stays private.
- **Tool-Oriented Architecture**: Built-in tools: filesystem, shell, Git, document, web, memory; extensible via plugins.
- **Memory System**: Automatic memory extraction, relevance-based retrieval, context injection.
- **Multi-Model Support**: OpenAI-compatible APIs, Ollama, Qwen, Volcano Ark, etc.
- **Extensible Runtime**: Long-running AI runtime; supports controlled self-optimization strategies.

---

## Architecture


YuntaoCode Runtime
┌─────────────────────────────┐
│ Memory / Context / Tools │
│ Conversation Runner │
│ Task Scheduler │
└─────────────┬──────────────┘
│
┌───────────┼───────────┐
│ │ │
Desktop Browser API
(UI Layer / Tauri / HTTP/WebSocket)


> Runtime is Python-based; Tauri is optional UI layer.

---

## Quick Start

```bash
git clone https://github.com/yuntaozn/YuntaoCode.git
cd YuntaoCode
pip install -r requirements.txt
python -m runtime.app --host 127.0.0.1 --port 8765

Open http://127.0.0.1:8765 in your browser.

Roadmap
v0.1: Local AI chat, tools, filesystem, shell, Git, memory
v0.2: MCP support, plugin system, multi-workspace
v0.3: Knowledge base, workflow engine, autonomous tasks
v1.0: Enterprise deployment, team collaboration, plugin marketplace
Educational Usage
AI Agent training
MCP courses
RAG experiments
Local LLM deployment
Software engineering labs
License

Apache License 2.0
LICENSE