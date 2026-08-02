# YuntaoCode

**Local-First AI Task Runtime**

面向本地 AI 工程实践的任务执行基座。

YuntaoCode 关注的核心不是“再做一个 AI 聊天助手”，而是让本地任务可以被计划、执行、暂停、恢复、验证和审计。

当前代码围绕三条执行主线和一条经验证据层组织：

* **Task Runtime**：任务状态、计划、步骤、执行、验证、恢复和结果。
* **Context Runtime**：上下文选择、压缩、证据边界、长期记忆、上下文账本和审计视图。
* **Capability Runtime**：工具、权限、插件、能力契约和本地执行边界。
* **Experience Layer**：从真实任务记录中沉淀 RunEvidence、Experience Sample、Replay Fixture、Evaluation Fixture 和诊断包。

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

它不是对 AI 终端形态的最终答案，而是一次持续进行中的工程探索。

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
  从任务记录中整理 RunEvidence、Experience Sample、Replay Fixture、Evaluation Fixture 和诊断包
```

前三条主线支撑任务运行；Experience Layer 只沉淀证据和经验，不默认注册 AI 生成代码，也不绕过 Runtime 的权限、验证和人工确认边界。模型负责理解目标、选择策略并书写结论，Runtime 负责保存状态、边界、证据和可审计的收束事实。

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
* Preview / Visual Debug
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

* 记录任务计划、模型判断和执行进展
* 记录工具调用、确认和错误
* 支持写入前备份和结果验证
* 为任务暂停、恢复、回放和审计提供基础记录

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

当前实现已经包含工具调用、模型决定的计划、确认、写入备份、执行记录、上下文快照、上下文审计和经验样本导出。Runtime 不再用预设角色阶段驱动任务，而是把任务目标、可见能力和运行事实交给模型持续判断；系统只负责安全、协议、状态、证据和审计边界。

Agent Runtime 的策略层位于 `runtime/agent_strategy/`。它负责模型任务契约、内部 Profile 描述、计划策略、事实提示和执行计划生命周期，让 `conversation_runner.py` 尽量保持为编排层。

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

贡献新能力时，优先检查这些当前边界：

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

当前版本提供的是能力来源管理：系统会按工具 ID 前缀展示 `filesystem`、`code`、`shell`、`git`、`web`、`preview` 等内置能力分组，并支持启停和依赖状态展示。这些分组不是已安装的第三方插件。

Plugin 在 YuntaoCode 中定义为可版本化、可分发的能力包容器，可包含 Skill、Capability Pack、MCP/CLI provider 描述和受控扩展声明。安装、审查、启用与实际执行彼此独立；当前只建立 manifest 和本机安装状态的数据契约，不提供动态加载、插件市场或远程自动更新。

本机能力包见 [docs/capability-packs.md](docs/capability-packs.md)，插件契约草案见 [docs/plugin-system.md](docs/plugin-system.md)。当前仓库不包含外部插件样板目录；能力扩展示例只保留在文档中，避免把实验产物误认为已内置功能。

AI 可以帮助创建本机能力包。默认应先沉淀为方法型 Skill（提示词、步骤、反例和验证清单），写入用户数据目录下的 `capability-packs/items/<pack-id>/`。工具适配器草稿必须保持隔离；0.1 不把草稿自动注册为可信运行时能力。详见 [docs/capability-governance.md](docs/capability-governance.md)。

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

模型会持续变化，

但稳定、开放、可扩展的 Task Runtime 仍然具有长期价值。

---

## 当前开发线

当前开发版本：0.2.0-dev

`v0.1.0` 已作为第一个公开预览版本固定。`main` 分支从这里开始进入
0.2.0 开发；0.1.x 只用于修复已发布安装包或已发布源码中的明显问题。

## 已发布的 0.1 实现快照

0.1 的意义不是功能完整、场景覆盖或稳定版承诺，而是把本地 AI Task Runtime 的基础边界跑通。当前代码已经实现的基础能力：

* Task Model：ProductTask、Run、ToolTask、状态、结果和运行血缘
* Run Lifecycle：running、waiting_confirmation、paused、resumed、completed、failed、stopped
* Task Trace：RunEvent、canonical event_name、工具调用、确认、错误、验证、结果和最终摘要预览
* Run Recovery：暂停、恢复、Runbook、Replay Request、Checkpoint、Context Snapshot
* Task Audit：RunEvidence、RunWorkbench、完成自审证据包、执行审计摘要、运行调试审计、任务记录 UI 和状态迁移测试
* Context Runtime：Context Pack / Ledger / Audit、上下文卫生、任务血缘、记忆边界、视觉证据/验证摘要和恢复快照
* Capability Runtime：ToolSpec 元数据、Capability Preflight、权限、确认、产物、Provider 和验证证据
* Provider 边界：内置工具、MCP、CLI、Capability Pack 和插件声明都通过 Capability Runtime 接入
* Automation Runtime 基础：触发器、任务模板、轻量 scheduler、并发边界、配置页和普通 prepared Run 转换契约
* Extension Contract 基础：插件 / MCP / CLI / Capability Pack 边界、权限声明、依赖声明和任务产物规范
* Experience / Evaluation 基础：RunEvidence、Experience Sample Export、Replay Fixture、Evaluation Fixture、Evaluation Report 和诊断包

## 0.2 开发方向判定

0.2.0 的主线不是继续扩大工具清单，而是增强 Observation / Verification /
Artifact Runtime：让模型能看到更多执行事实、基于证据判断差距，并把任务产物
沉淀成可审计对象。

近期新增或调整应先回答：

* 是否让 Task / Context / Capability / Experience 中的一条主线更清楚；
* 是否减少 Runtime 替模型判断任务语义、执行路线或最终结论；
* 是否增强观察、状态、证据、验证、产物、恢复、审计或权限边界；
* 是否能通过测试、诊断包或真实任务记录验证效果；
* 是否避免把某个场景、工具、MCP、CLI、插件或 Skill 变成新的独立执行体系。

如果一个改动只是扩展场景、追逐概念或增加工具清单，而不能让以上边界更清楚，它不应进入 0.2 主线。

开发中仍可以运行聚焦自检：

```bash
python scripts/check_01_readiness.py
```

这只检查版本、文档、核心编译、前端语法和关键 Runtime 测试，不替代真实任务冒烟。0.2 期间它仍作为基础回归卫生检查保留。

---

## License

Apache License 2.0

See LICENSE for details.
