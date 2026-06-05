# YuntaoCode — 云涛智能终端

**Local-First AI Task Runtime**

面向开发者、教学与工程实践的本地 AI 任务执行基座。

YuntaoCode 关注的核心不是“再做一个 AI 聊天助手”，而是让本地任务可以被计划、执行、暂停、恢复、验证和审计。

它当前最重要的开源目标，是把 AI 进入本地真实任务时必须面对的三件事做成清晰基座：

* **Task Runtime**：任务状态、计划、步骤、执行、验证、恢复和结果。
* **Context Runtime**：上下文选择、压缩、证据边界、长期记忆和上下文账本。
* **Capability Runtime**：工具、权限、插件、能力契约和本地执行边界。

---

## 为什么会有 YuntaoCode

YuntaoCode 并非从产品规划开始。

它来源于这些年对 AI 工程化实践的持续探索。

相比模型本身，我们更关注模型之外的问题：

* 如何管理上下文；
* 如何组织长期记忆；
* 如何让 AI 使用工具完成真实任务；
* 如何让任务过程可观察、可恢复、可审计；
* 如何在本地稳定运行；
* 如何保持系统长期可扩展。

随着这些问题不断被解决，一个围绕 Task 的本地 Runtime 架构逐渐形成。

YuntaoCode 就是在这样的过程中自然演化出来的。

它不是对未来 AI 终端的答案，而是一次持续进行中的探索。

---

## 核心特性

### 三层运行时（Runtime Foundation）

YuntaoCode 的底层不是一组工具清单，而是三条可以长期演进的运行时主线：

```text
Task Runtime
  管理用户目标、执行状态、计划、步骤、Trace、验证和恢复

Context Runtime
  管理任务相关上下文、证据、摘要、记忆和有效性边界

Capability Runtime
  管理工具能力、权限、确认、插件草案和外部能力接入
```

这三层共同决定一件事：模型可以参与任务判断和执行，但 Runtime 必须拥有状态、边界、证据和完成判定。

### 任务优先（Task First）

YuntaoCode 把一次请求看作一个可管理的任务，而不是一次普通聊天：

* Task：用户目标和运行上下文
* Plan：可展示、可推进的执行计划
* Step：当前步骤、状态、工具提示和结果
* Trace：模型输出、工具调用、确认、错误和恢复记录
* Result：最终回答、修改摘要、验证结果和剩余风险

### 本地优先（Local First）

* 所有文件读写均在本地完成
* 支持本地代码执行
* 支持本地文档处理
* 用户数据由用户自行掌控

### 能力协同（Capability Collaboration）

内置能力：

* Filesystem
* Shell
* Git
* Document Processing
* Web Access
* Memory

工具是任务执行的能力单元。支持通过插件扩展新的工具能力，但工具本身不是产品边界；它们需要通过 Capability Contract 接入任务运行时。

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

### 可恢复执行（Recoverable Execution）

* 记录任务计划和阶段推进
* 记录工具调用、确认和错误
* 支持写入前备份和结果验证
* 为后续任务暂停、恢复、回放和审计预留扩展能力

---

## 架构概览

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

Python Runtime 是系统核心。

Tauri 桌面端只是其中一种界面形式，Runtime 本身可以独立运行。

当前实现已经包含工具调用、计划生成、阶段推进、确认、写入备份和执行记录。下一阶段的重点是把这些能力收束成更明确的 Task / Context / Capability Runtime。

Agent Runtime 的策略层位于 `runtime/agent_strategy/`。它负责意图分类、内部 Profile、计划策略、阶段提示和执行计划生命周期，让 `conversation_runner.py` 尽量保持为编排层。

Task Model 草案见 [docs/task-model.md](docs/task-model.md)，上下文运行时规划见 [docs/context-runtime.md](docs/context-runtime.md)，能力运行时规划见 [docs/capability-runtime.md](docs/capability-runtime.md)，当前运行时基础契约见 [docs/runtime-foundation.md](docs/runtime-foundation.md)。

---

## 仓库镜像

* GitHub 主仓库：[https://github.com/yuntaozn/YuntaoCode](https://github.com/yuntaozn/YuntaoCode)
* Gitee 国内镜像：[https://gitee.com/yuntaozn/YuntaoCode](https://gitee.com/yuntaozn/YuntaoCode)

Gitee 仓库主要用于国内访问、克隆和下载。Issue、Pull Request 和长期协作入口建议优先使用 GitHub。

---

## 快速开始

### 克隆项目

GitHub：

```bash
git clone https://github.com/yuntaozn/YuntaoCode.git

cd YuntaoCode
```

国内访问较慢时可使用 Gitee 镜像：

```bash
git clone https://gitee.com/yuntaozn/YuntaoCode.git

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
python -m runtime.app --host 127.0.0.1 --port 8765
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
node --check runtime/panel/static/panel.js
node --check runtime/panel/static/settings.js
node --check runtime/panel/static/plugins.js
node --check runtime/panel/static/i18n.js
```

Tauri 壳验证：

```bash
powershell -ExecutionPolicy Bypass -File scripts/prepare_tauri_check.ps1
cargo check --manifest-path desktop-shell/src-tauri/Cargo.toml
```

`cargo check` 需要 Tauri `externalBin` 和 Windows 图标路径存在；上面的脚本会生成检查用 sidecar 占位文件，并确认图标路径存在。正式打包仍使用 `npm run build:windows` 构建真实 sidecar。

桌面应用图标位于 `desktop-shell/src-tauri/icons/icon.ico`，建议提交正式 `.ico` 文件。检查脚本只会在该文件缺失时生成临时图标。

Windows 如果没有 `python` 命令，可以使用 Python Launcher：

```powershell
python -m runtime.app --host 127.0.0.1 --port 8765
```

---

## 扩展指南

### 理解任务模型

贡献新能力前，建议先阅读 [docs/task-model.md](docs/task-model.md)、[docs/context-runtime.md](docs/context-runtime.md)、[docs/capability-runtime.md](docs/capability-runtime.md) 和 [docs/runtime-foundation.md](docs/runtime-foundation.md)。

项目当前不鼓励优先堆叠应用场景。更推荐的贡献方向是：

* 让任务状态更清晰；
* 让计划、步骤和工具结果更容易测试；
* 让失败恢复、写入回退和执行审计更稳定；
* 让某个工具或技能成为可复用的任务能力。

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

### 插件与插件契约

当前版本提供的是内置插件能力管理：系统会按工具 ID 前缀展示 `filesystem`、`code`、`shell`、`git`、`web` 等能力分组，并支持启停和依赖状态展示。

这还不是插件市场，也不是远程更新系统。真正面向第三方扩展的插件 manifest、动态加载、权限声明和隔离机制仍属于后续基座工作。

插件契约草案见 [docs/plugin-system.md](docs/plugin-system.md)。当前仓库不包含外部插件样板目录；能力扩展示例只保留在文档中，避免把实验产物误认为已内置功能。

AI 可以帮助创建插件草稿，但草稿必须写入隔离目录。完成后通过测试/依赖摘要和一次人工确认，再进入后续受控注册或启用流程。详见 [docs/capability-governance.md](docs/capability-governance.md)。

---

## 开源协作

欢迎参与开发。开始前建议阅读：

* [AGENTS.md](AGENTS.md)
* [CONTRIBUTING.md](CONTRIBUTING.md)
* [SECURITY.md](SECURITY.md)
* [CHANGELOG.md](CHANGELOG.md)

请不要提交 API Key、本地对话记录、用户数据、打包产物或 `node_modules`。

---

## 项目理念

YuntaoCode 并不试图构建“最强大的 AI 助手”。

相比追逐某一个模型或框架，我们更关注：

* Task 的生命周期是否清楚；
* 执行过程是否可观察、可暂停、可恢复；
* 工具调用是否有边界、有确认、有记录；
* 结果是否能被验证、回滚和复盘；
* 模型替换后，任务执行体系是否仍然成立。

我们相信：

未来的模型会不断变化，

但稳定、开放、可扩展的 Task Runtime 仍然具有长期价值。

---

## Roadmap

### Phase 1：Runtime Foundation

目标：先把 Task / Context / Capability 三条运行时主线做清楚，而不是继续堆功能清单。

* [ ] Task Model：任务、计划、步骤、状态、结果和元数据
* [ ] Task Lifecycle：created、running、waiting、failed、completed、cancelled
* [ ] Task Trace：模型输出、工具调用、确认、错误、验证和最终摘要
* [ ] Task Recovery：暂停、恢复、失败重试、写入回退
* [ ] Task Audit：可读的执行记录和可测试的状态迁移
* [ ] Context Runtime：上下文选择、证据、压缩快照、记忆边界
* [ ] Capability Runtime：能力契约、权限、确认、产物和验证规则

### Phase 2：Reusable Capabilities

目标：把工具变成可复用的任务能力。

* [ ] 稳定的工具协议和参数规范
* [ ] 模块化技能注册
* [ ] Runtime Extension Contract：插件 Manifest、权限声明、依赖声明和任务产物规范
* [ ] AI 自建插件草稿隔离、测试摘要和人工确认注册流程
* [ ] 文档解析、代码分析、Git、Shell 等能力的任务化封装
* [ ] MCP 作为外部工具接入方式，而不是核心定位本身

### Phase 3：Task Templates

目标：沉淀可复用的任务模板，而不是只沉淀 prompt。

* [ ] 代码修改任务模板
* [ ] 项目审查任务模板
* [ ] 文档处理任务模板
* [ ] 论文/资料分析任务模板
* [ ] 任务模板导入、导出和版本管理

### Phase 4：Ecosystem

目标：在 Task Runtime 稳定后再扩展生态。

* [ ] 多工作区和长期任务
* [ ] 本地知识库 / RAG 接口
* [ ] 可选插件索引和签名分发
* [ ] 团队同步与企业部署
* [ ] 稳定 Runtime API 和插件兼容性

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
