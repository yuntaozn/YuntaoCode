# YuntaoCode

**YuntaoCode Intelligent Terminal** — A local AI assistant for developers and office workers.

Developed by [Shenyang Yuntao Intelligent Technology Co., Ltd.](mailto:wutaoplay@outlook.com). Built on Tauri + Python sidecar architecture, deeply integrating LLM capabilities with local files, code, documents and terminal.

> [中文版](README.md)

## Features

- **Local First**: File I/O, code editing and document processing all run on the user's machine — data never leaves the device
- **Smart Conversations**: Streaming chat + multi-turn tool calling with memory management and context compression
- **Tool Ecosystem**: Built-in skills for file system, code editing, Shell, Git, document processing and web browsing, with plugin extensibility
- **Memory System**: Auto-extracts long-term memories from conversations, injects context with relevance filtering
- **Multi-Model Support**: Compatible with OpenAI API protocol — supports Volcengine, Qwen, Ollama and more

## Quick Start

### Development Mode

```powershell
cd YuntaoCode
pip install -r requirements.txt
python -m runtime.app --host 127.0.0.1 --port 8765 --workspace D:\code
```

Open `http://127.0.0.1:8765/` in your browser to use the local panel.

### Desktop Packaging

```powershell
cd desktop-shell
npm install
npm run build:windows
```

## Architecture

YuntaoCode's Python Runtime is built on Tornado. Unlike frameworks oriented toward standard API services, Tornado is better suited as a local async runtime — powering WebSocket streaming, tool dispatch, file system access, shell execution and plugin extensions.

```text
yuntaocode/
  runtime/                 Python Tornado local runtime
    app.py                 Server entry point
    config.py              Runtime configuration
    conversation_runner.py Conversation execution loop
    memory_store.py        Memory persistence store
    memory_service.py      Memory relevance filtering
    memory_extractor.py    Auto memory extraction from conversations
    tool_registry.py       Tool registry center
    context_manager.py     Context compression
    security.py            Path security boundaries
    api/                   HTTP / WebSocket interfaces
    skills/                Local skills (filesystem/code/shell/git/web/document/memory)
  desktop-shell/           Tauri desktop shell
  docs/                    Architecture and tool protocol documentation
  requirements.txt         Python runtime dependencies
```

## Extension Guide

### Adding a New Tool

Create a module under `runtime/skills/`, define a handler and ToolSpec, then register in `runtime/skills/__init__.py`:

```python
from runtime.tool_registry import ToolRegistry, ToolSpec

def my_tool_handler(args, context):
    # context contains settings, path_guard, etc.
    return {"result": "..."}

def register_my_tools(registry: ToolRegistry):
    registry.register(
        ToolSpec(id="my.tool", name="My Tool", description="...", input_schema={...}),
        my_tool_handler,
    )
```

### Adding a New API

Create a handler under `runtime/api/`, extend `ApiHandler`, then register the route in `runtime/app.py`.

## Project Info

| Item | Description |
|------|-------------|
| Name | YuntaoCode (Intelligent Terminal) |
| Company | Shenyang Yuntao Intelligent Technology Co., Ltd. |
| Email | wutaoplay@outlook.com |
| Version | 0.1.0 |
| License | Apache License 2.0 |

## License

[Apache License 2.0](LICENSE)

Copyright 2024-2026 Shenyang Yuntao Intelligent Technology Co., Ltd.
