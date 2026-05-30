# YuntaoCode — 云涛智能终端

**Local-First AI Runtime for Developers, Education and Engineering**

面向开发者、教学与工程实践的本地 AI Runtime。

YuntaoCode 专注于上下文管理、长期记忆、工具协同与本地运行能力，探索 AI 在终端环境中的长期运行与持续演进。

---

## 为什么会有 YuntaoCode

YuntaoCode 并非从产品规划开始。

它来源于这些年对 AI 工程化实践的持续探索。

相比模型本身，我们更关注模型之外的问题：

* 如何管理上下文；
* 如何组织长期记忆；
* 如何让 AI 使用工具；
* 如何让不同能力协同工作；
* 如何在本地稳定运行；
* 如何保持系统长期可扩展。

随着这些问题不断被解决，一个独立的 Runtime 架构逐渐形成。

YuntaoCode 就是在这样的过程中自然演化出来的。

它不是对未来 AI 终端的答案，而是一次持续进行中的探索。

---

## 核心特性

### 本地优先（Local First）

* 所有文件读写均在本地完成
* 支持本地代码执行
* 支持本地文档处理
* 用户数据由用户自行掌控

### 工具协同（Tool Collaboration）

内置能力：

* Filesystem
* Shell
* Git
* Document Processing
* Web Access
* Memory

支持通过插件扩展新的工具能力。

### 长期记忆（Memory）

* 自动记忆提取
* 相关性检索
* 上下文压缩
* 对话历史管理

### 多模型支持

兼容 OpenAI API 协议：

* OpenAI
* Ollama
* 通义千问
* 火山方舟
* 其它兼容 OpenAI API 的模型服务

### 持续演进能力

* 记录工具调用过程
* 记录执行结果
* 支持经验沉淀
* 为未来工作流优化与自我改进机制预留扩展能力

---

## 架构概览

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

Python Runtime 是系统核心。

Tauri 桌面端只是其中一种界面形式，Runtime 本身可以独立运行。

---

## 快速开始

### 克隆项目

```bash
git clone https://github.com/yuntaozn/YuntaoCode.git

cd YuntaoCode
```

### 安装依赖

```bash
python -m pip install -r requirements.txt
```

如果你只想安装 Runtime 核心与测试依赖：

```bash
python -m pip install -e ".[dev]"
```

### 启动 Runtime

```bash
python -m runtime.app \
    --host 127.0.0.1 \
    --port 8765
```

浏览器访问：

```text
http://127.0.0.1:8765
```

### 打包桌面版

```bash
cd desktop-shell

npm ci

npm run build:windows
```

---

## 开发与验证

推荐在提交变更前至少运行：

```bash
python -m pip install -e ".[dev]"
pytest
python scripts/smoke_core.py
```

桌面前端验证：

```bash
npm --prefix desktop-shell ci
npm --prefix desktop-shell run build:ui
node --check desktop-shell/src/main.js
```

Tauri 壳验证：

```bash
powershell -ExecutionPolicy Bypass -File scripts/prepare_tauri_check.ps1
cargo check --manifest-path desktop-shell/src-tauri/Cargo.toml
```

`cargo check` 需要 Tauri `externalBin` 和 Windows 图标路径存在；上面的脚本只生成检查用占位文件，正式打包仍使用 `npm run build:windows` 构建真实 sidecar。

Windows 如果没有 `python` 命令，可以使用 Python Launcher：

```powershell
py -3.11 -m runtime.app --host 127.0.0.1 --port 8765
```

---

## 扩展指南

### 添加新工具

在 `runtime/skills/` 下创建模块：

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

### 添加新 API

在 `runtime/api/` 下创建 Handler，并在 `runtime/app.py` 注册路由。

### 插件系统状态

当前版本已经有基于工具 ID 前缀的插件分组、启停和依赖状态展示。

真正面向第三方扩展的插件 manifest、动态加载、权限声明和隔离机制仍属于 v0.2 重点工作。

插件协议草案见 [docs/plugin-system.md](docs/plugin-system.md)。

---

## 开源协作

欢迎参与开发。开始前建议阅读：

* [CONTRIBUTING.md](CONTRIBUTING.md)
* [SECURITY.md](SECURITY.md)
* [CHANGELOG.md](CHANGELOG.md)

请不要提交 API Key、本地对话记录、用户数据、打包产物或 `node_modules`。

---

## 项目理念

YuntaoCode 并不试图构建“最强大的 AI 助手”。

相比追逐某一个模型或框架，我们更关注：

* Runtime 的稳定性；
* 工具之间的协同能力；
* 长期记忆的组织方式；
* 本地化运行与用户控制权；
* 系统的持续演进能力。

我们相信：

未来的模型会不断变化，

但稳定、开放、可扩展的 Runtime 仍然具有长期价值。

---

## Roadmap

### v0.1

* [x] Local AI Chat
* [x] Tool Calling
* [x] Filesystem
* [x] Shell
* [x] Git
* [x] Memory

### v0.1.1

* [ ] 开源协作流程
* [ ] CI 与自动化测试
* [ ] 安全文档与问题模板
* [ ] 安装与构建文档修正

### v0.2

* [ ] MCP Support
* [ ] Plugin Manifest
* [ ] Dynamic Plugin Loading
* [ ] Plugin Permission Model
* [ ] Multi Workspace

### v0.3

* [ ] Local Knowledge Base
* [ ] Workflow Engine
* [ ] Autonomous Tasks

### v0.4

* [ ] Tool Marketplace
* [ ] Signed Plugin Distribution
* [ ] Release Packaging

### v1.0

* [ ] Stable Runtime API
* [ ] Stable Plugin Compatibility
* [ ] Enterprise Deployment
* [ ] Team Collaboration
* [ ] Plugin Marketplace

---

## 教育与实验场景

YuntaoCode 同样适用于：

* AI Agent 实训
* MCP 教学
* RAG 实验
* 本地大模型部署实验
* 软件工程课程
* AI 工程化实践课程

---

## 项目状态

当前版本：0.1.0

状态：Active Development

在 v1.0 之前：

* API 可能发生变化
* 插件接口可能调整
* Runtime 架构将持续优化

---

## License

Apache License 2.0

See LICENSE for details.
