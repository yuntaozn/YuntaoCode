# 架构草案

## 核心分工

```text
Tauri 桌面壳
  - 登录状态展示
  - 文件和目录选择
  - 本地任务面板
  - 日志和结果预览
  - 启动、停止 Python sidecar

Python Tornado sidecar
  - 本地工具注册
  - 任务执行和日志流
  - 本地文件安全边界
  - 本地模型 Provider 和 API Key 配置
  - 本地项目对话记录
  - 文档、代码、浏览器等技能

后台服务
  - 账号、权限和组织级授权验证
  - 后续可提供团队同步能力
```

## 为什么先做 Python sidecar

Tauri 是壳，真正的产品壁垒是本地技能运行时。先把 Python sidecar 独立跑通，可以降低新技术栈风险，也方便后续接入 Tauri、命令行或 Web 调试面板。

## 核心定位：Task Runtime

YuntaoCode 不应只按工具清单扩展。Filesystem、Shell、Git、文档解析、浏览器和 MCP 都是工具入口；真正需要沉淀的是本地 AI 任务运行基座。

当前基座应按三条运行时主线理解：

```text
Task Runtime
  任务、计划、步骤、状态、Trace、验证、恢复、结果。

Context Runtime
  上下文选择、压缩、证据、记忆、可信度、上下文快照。

Capability Runtime
  能力契约、工具、权限、确认、插件草案、外部能力接入。
```

外部能力接入进一步区分为：

```text
Plugin / Capability Catalog
  展示任务可以使用的能力，以及能力来自内置、外部适配器或 MCP。

MCP Service Manager
  管理 MCP 配置、进程、传输、连接状态、日志和权限。

MCP Protocol Adapter
    完成握手、工具发现、调用和结果归一化，再将工具注册到 Capability Runtime。
```

MCP 进程运行不等于协议已连接。只有协议适配器完成握手并发现工具后，
对应能力才可以进入模型上下文。详见 [mcp-services.md](mcp-services.md)。
当前 stdio MCP 会话已经接通这条链路；Streamable HTTP 与 legacy SSE
仍只提供配置和可达性检查，尚未建立协议会话。

仓库中的 `mcp-services/` 目录只用于放置 MCP 服务源码副本、第三方参考资料
和服务级集成说明。它不属于 `runtime/skills/` 内置能力目录，Runtime 也不会
自动从该目录导入代码。MCP 服务是否启用、如何启动、哪些工具进入模型上下文，
仍由 MCP Service Manager 和 Capability Runtime 决定。

其中 Task Runtime 是用户目标的执行主线：

```text
Task
  -> Plan
  -> Step
  -> Tool / Model Execution
  -> Verification
  -> Trace / Audit
  -> Recovery
```

短期架构重点：

- 定义清晰的 Task / Plan / Step / Trace 数据结构。
- 让任务状态迁移可测试。
- 让工具调用、确认、失败、验证和最终摘要进入统一 Trace。
- 让写入回退、失败重试、暂停恢复成为 Runtime 能力，而不是某个 prompt 的偶然表现。
- 让上下文来源、证据、摘要和未验证项可追踪。
- 让工具通过 Capability Contract 接入，而不是只暴露函数名。
- 区分本地文件写入与更广义的可观察状态变更，让 MCP、CAD、数据库和浏览器
  自动化通过统一的 `effects / roles / artifacts` 事实进入任务验收。

Task Model 草案见 [task-model.md](task-model.md)，Context Runtime 规划见 [context-runtime.md](context-runtime.md)，Capability Runtime 规划见 [capability-runtime.md](capability-runtime.md)，Document Draft Runtime 见 [document-draft-runtime.md](document-draft-runtime.md)，当前代码层基础契约见 [runtime-foundation.md](runtime-foundation.md)。

## 当前运行边界

- 只监听 `127.0.0.1`。
- 工具只能访问启动参数 `--workspace` 指定的目录。
- 当前没有开放任意 shell 执行接口。
- 模型 Key 和对话记录保存在本机用户配置目录，不写入项目目录。

## Agent Runtime 策略层

当前界面保持一个统一终端，但 Runtime 内部需要区分不同类型任务：

```text
User Request
  -> Model Task Understanding
  -> Capability Router
  -> Agent Profile / Planning Policy
  -> Task / Plan / Step
  -> Conversation Runner
  -> Tools / Model Providers
  -> Streamed Process Trace
```

这层策略目前集中在 `runtime/agent_strategy/`：

- `classifiers.py`：意图分类、工具分类、进度观察和阶段判断。
- `capability_router.py`：能力契约、模型路由提案和提案验证。
- `conversation_task_context.py`：根据对话历史判断追问是否继承上一轮任务、
  写入上下文、文档输出上下文和字数目标。
- `profiles.py`：内部执行 Profile，例如直接问答、项目分析、代码修改、外部能力执行、文档工作流、论文工作流。
- `policy.py`：请求路由和计划执行开关；确定性规则只承担安全边界与模型不可用时的回退，不替模型决定任务目标和执行策略。
- `prompts.py`：阶段提示、修复提示、最终回答提示等 prompt 构建。
- `plan_tracker.py`：执行计划的提取、归一化、推进和收尾。

新增能力时优先扩展这些模块，而不是继续向 `conversation_runner.py`
主循环里堆分支。`conversation_runner.py` 应尽量保持为编排层：
它负责串起上下文压缩、计划、模型流、工具调用、确认机制和最终消息落库。
工具事件的前端预览、进度摘要和回填给模型的压缩 payload 由
`runtime/tool_event_presentation.py` 负责，避免 API Handler 直接承载展示规则。

后续演进方向是让第一层任务理解更多交给模型，Runtime 负责能力目录与执行契约：

```text
Model proposes and may revise: goal + capability + tool + expected artifacts
Runtime validates: protocol integrity, known capability, permission, confirmation, trace, execution evidence
```

Capability Router 草案见 [capability-router.md](capability-router.md)。

模型提出的目标、预期产物和路径属于任务理解声明，不是运行时强制锁定的目标。
Runtime 可以审计“声明与结果是否一致”，但不应因为路径提示或预先计划阻止模型
根据执行证据调整策略。只有权限、路径边界、确认和完整工具协议属于硬执行边界。

## 扩展原则

- 用户侧保持统一终端，内部通过 Profile 区分执行策略。
- 基建优先级高于功能清单：先让 Task、Context、Capability 三条 Runtime 主线清楚。
- 新增任务类型先补 Profile / Policy / Prompt / Plan 测试，再接入主循环。
- 工具权限、安全确认和路径边界留在执行层，不由 prompt 或 UI 文案代替。
- 前端过程记录应展示 Runtime 的真实执行轨迹，而不是隐藏计划、推理、工具事件。
