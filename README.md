# YuntaoCode — 云涛智能终端

**Local-First AI Task Runtime**

面向开发者、教学与工程实践的本地 AI 任务执行基座。

YuntaoCode 关注的核心不是“再做一个 AI 聊天助手”，而是让本地任务可以被计划、执行、暂停、恢复、验证和审计。

它当前最重要的开源目标，是把 AI 进入本地真实任务时必须面对的三条执行主线和一条经验证据层做成清晰基座：

* **Task Runtime**：任务状态、计划、步骤、执行、验证、恢复和结果。
* **Context Runtime**：上下文选择、压缩、证据边界、长期记忆和上下文账本。
* **Capability Runtime**：工具、权限、插件、能力契约和本地执行边界。
* **Experience Layer**：从真实任务记录中沉淀 Experience Sample、Digest 和 Replay Fixture，用于后续评测与能力升级。

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

### 运行时基座（Runtime Foundation）

YuntaoCode 的底层不是一组工具清单，而是三条可以长期演进的执行运行时主线，以及一条基于任务证据的经验沉淀层：

```text
Task Runtime
  管理用户目标、执行状态、计划、步骤、Trace、验证和恢复

Context Runtime
  管理任务相关上下文、证据、摘要、记忆和有效性边界

Capability Runtime
  管理工具能力、权限、确认、本机能力包和外部能力接入

Experience Layer
  从任务记录中整理 Experience Sample、Digest 和 Replay Fixture，用于后续评测和能力升级
```

前三条主线共同决定任务如何运行；Experience Layer 只沉淀证据和经验，不默认注册 AI 生成代码，也不绕过 Runtime 的权限、验证和人工确认边界。模型可以参与任务判断和执行，但 Runtime 必须拥有状态、边界、证据和完成判定。

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
* Conversation Attachments
* Web Access
* Memory

工具是任务执行的能力单元。本机能力包优先沉淀方法型 Skill、任务模板和上下文包；只有确实需要新执行能力时，才进入更严格的工具适配器或插件边界。工具本身不是产品边界；它们需要通过 Capability Contract 接入任务运行时。

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
* 火山 Agent Plan（OpenAI Compatible）
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

当前实现已经包含工具调用、计划生成、阶段推进、确认、写入备份、执行记录和经验样本导出。下一阶段的重点是把这些能力收束成更明确的 Task / Context / Capability Runtime，以及基于证据的 Experience Layer。

Agent Runtime 的策略层位于 `runtime/agent_strategy/`。它负责意图分类、内部 Profile、计划策略、阶段提示和执行计划生命周期，让 `conversation_runner.py` 尽量保持为编排层。

文档入口见 [docs/README.md](docs/README.md)。核心基座契约见 [docs/runtime-foundation.md](docs/runtime-foundation.md)，Task / Context / Capability 三条主线分别见 [docs/task-model.md](docs/task-model.md)、[docs/context-runtime.md](docs/context-runtime.md) 和 [docs/capability-runtime.md](docs/capability-runtime.md)，Experience Layer 见 [docs/experience-runtime.md](docs/experience-runtime.md)。

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

贡献新能力前，建议先阅读 [docs/README.md](docs/README.md) 中的文档地图，再根据变更类型进入 Task、Context、Capability、Experience 或插件/MCP 相关文档。

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

### 本机能力包与插件契约

当前版本提供的是内置插件能力管理：系统会按工具 ID 前缀展示 `filesystem`、`code`、`shell`、`git`、`web` 等能力分组，并支持启停和依赖状态展示。

这还不是插件市场，也不是远程更新系统。真正面向第三方扩展的插件 manifest、动态加载、权限声明和隔离机制仍属于后续基座工作。

本机能力包见 [docs/capability-packs.md](docs/capability-packs.md)，插件契约草案见 [docs/plugin-system.md](docs/plugin-system.md)。当前仓库不包含外部插件样板目录；能力扩展示例只保留在文档中，避免把实验产物误认为已内置功能。

AI 可以帮助创建本机能力包。默认应先沉淀为方法型 Skill（提示词、步骤、反例和验证清单），写入用户数据目录下的 `capability-packs/items/<pack-id>/`。工具适配器草稿必须保持隔离，完成后通过测试/依赖摘要和一次人工确认，再进入后续受控注册或启用流程。详见 [docs/capability-governance.md](docs/capability-governance.md)。

### MCP 服务目录

外部 MCP 服务源码副本、服务级参考资料和集成说明放在 `mcp-services/` 下。例如
`mcp-services/blender-mcp/` 是 Blender MCP 服务的本地参考副本，不是内置
`runtime.skills.*` 模块，也不会被 Runtime 自动导入。

MCP 服务的启停、连接状态、权限、日志、工具发现和能力绑定仍由 MCP Service
Manager 管理。默认 Blender 示例配置使用 `uvx blender-mcp` 包运行器，只有在用户
显式启用并启动服务后才会连接。

---

## 开源协作

欢迎参与开发。开始前建议阅读：

* [AGENTS.md](AGENTS.md)
* [CONTRIBUTING.md](CONTRIBUTING.md)
* [SECURITY.md](SECURITY.md)
* [CHANGELOG.md](CHANGELOG.md)
* [文档地图](docs/README.md)
* [版本与发布规则](docs/versioning.md)

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

### 0.1 收口目标：Runtime Direction Release

0.1 不是稳定版，也不是“已经可以扩展所有场景”的完成版。它的目标是先把 YuntaoCode 的方向、边界和基础框架说清楚：

* YuntaoCode 不是工具集合、聊天壳、MCP/CLI 客户端或 Skill 管理器。
* 它的核心定位是本地优先的 AI Task Runtime。
* 0.1 优先收束 Task / Context / Capability / Experience 四条主线。
* MCP、CLI、内置工具、Capability Pack 和未来插件都应作为 Provider 接入 Capability Runtime，而不是各自形成一套执行体系。
* 文档、代码、自动化、评测、Skill Evolution 和自我迭代都可以在基座上继续深化，但不压进 0.1 作为“必须完成的一切”。

近期每一次调整都应先问一句：它是否帮助 0.1 收口？如果只是追逐新概念或新增场景，而不能让方向、状态、证据、能力边界更清楚，就应先放到后续阶段。

### Phase 1：Runtime Foundation

目标：先把 Task / Context / Capability / Evidence 四条基础线打稳。YuntaoCode 的价值不来自工具数量，而来自任务能被执行、观察、恢复、验证和复盘。

* [x] Task Model 基础：ProductTask、Run、ToolTask、状态、结果和运行血缘
* [x] Run Lifecycle 基础：running、waiting_confirmation、paused、resumed、completed、failed、stopped
* [ ] Task Trace：模型输出、工具调用、确认、错误、验证和最终摘要
* [x] Run Recovery 基础：暂停、恢复、Runbook、Replay Request
* [x] Recovery Context 基础：Checkpoint、Context Snapshot、显式启动的 Replay Run
* [ ] Task Audit：可读的执行记录和可测试的状态迁移
* [ ] Context Runtime：上下文选择、证据、压缩快照、记忆边界
* [ ] Capability Runtime：能力契约、权限、确认、产物和验证规则
* [x] Automation Runtime 基础：触发器、任务模板、并发边界、配置页和普通 Run 转换契约
* [ ] MCP Service Lifecycle：服务配置、启动策略、协议连接、工具发现、诊断和能力绑定
* [ ] Runtime Extension Contract：插件 Manifest、权限声明、依赖声明和任务产物规范

### Phase 2：Experience And Evaluation Loop

目标：让 YuntaoCode 从真实任务中留下可审计证据，提取经验样本，形成可回放、可比较、可评测的任务样本。不是把每一次任务都自动变成 skill，也不是收集用户数据做排行榜。

* [x] RunEvidence：统一的运行事实视图
* [x] Experience Runtime 基础：Experience Sample、Experience Digest、Runbook / Replay 之间的数据边界
* [x] Evaluation Fixture / Report 基础：从选定 RunEvidence 生成样本并比较结果
* [x] Experience Sample Export：从选定 RunEvidence 手动导出经验样本
* [ ] Experience Sample 文件导入、校验、标注和对比
* [ ] Replay Runner：通过正常 Task Runtime 回放选定样本
* [ ] Evaluation Report 深化：模型、Provider、Runtime 版本、能力可用性和失败原因对比
* [ ] 经验消化机制：从多个样本总结稳定模式、适用边界和反例

### Phase 3：Skill / Capability Evolution

目标：让 AI 基于经验和评测证据提出候选技能、任务模板或能力草稿，并经过隔离、回放、验证和人工启用。Skill 不是一份提示词说明书，Plugin 也不是默认可信代码；它们都必须从证据链中获得信任。

* [ ] Experience Digest 到 Skill Candidate 的生成流程
* [ ] Task Template Candidate：从成功任务和失败反例中沉淀可复用任务结构
* [ ] AI 自建 Capability Pack 隔离目录、导出、测试摘要和启用边界
* [ ] Candidate Replay：候选能力必须通过选定 fixture 的回放评测
* [ ] Manual Promotion：用户确认后才进入可启用能力列表
* [ ] 能力版本、兼容性、回滚和废弃策略

### Phase 4：Self-Iteration Lab

目标：让 YuntaoCode 在隔离分身、测试集、诊断报告和人工合并边界内辅助改进自己的 Runtime。这里关注的是“可控自我迭代”，不是让模型直接修改可信主运行时代码。

* [ ] Runtime Self-Diagnostic：从失败任务、诊断包和评测报告定位基座问题
* [ ] Runtime Sandbox / 分身：独立环境中生成、测试和验证改进方案
* [ ] Fixture Regression Suite：用选定任务样本验证 Runtime 改动是否退化
* [ ] Source Update Proposal：AI 生成带证据的代码变更建议、测试结果和风险摘要
* [ ] Human Merge Boundary：人工审查、合并、发布和回滚
* [ ] 可选生态：插件索引、签名分发、团队同步和企业部署只在进化闭环稳定后推进

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

当前开发版本：0.1.0

状态：Active Development

在 v1.0 之前：

* API 可能发生变化
* 插件接口可能调整
* Runtime 架构将持续优化

---

## License

Apache License 2.0

See LICENSE for details.
