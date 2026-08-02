# 架构说明

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

```

## Python sidecar

Tauri 是壳，核心边界是本地 Task Runtime。Python sidecar 可以独立运行，
也可以被桌面壳启动。

## 核心定位：Task Runtime

YuntaoCode 不应只按工具清单扩展。Filesystem、Shell、Git、文档解析、浏览器和 MCP 都是工具入口；真正需要沉淀的是本地 AI 任务运行基座。

YuntaoCode 是本地优先的 AI Task Runtime。Task、Context、Capability 和 Experience 是基础主线；MCP、CLI、内置工具、本机能力包和插件声明都是能力来源，通过统一边界接入，不各自形成独立执行体系。

当前基座应按三条执行主线加一条经验学习层理解：

```text
Task Runtime
  任务、计划、步骤、状态、Trace、验证、恢复、结果。

Context Runtime
  上下文选择、项目焦点、压缩、证据、记忆、可信度、上下文快照。

Capability Runtime
  能力契约、工具、权限、确认、插件草案、外部能力接入。

Experience Runtime
  从 Runbook / RunResult 中抽取经验样本、Replay Fixture 和 Evaluation
  记录；不直接控制当前任务执行。
```

外部能力接入进一步区分为：

```text
Plugin / Capability Catalog
  展示任务可以使用的能力，以及能力来自内置、CLI、外部适配器或 MCP。

CLI Provider
  将稳定的本地命令声明为受控能力来源，保留 command/args、依赖、权限、
  超时、产物和验证证据；它不是开放任意 shell 的替代说法。

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

0.1 架构重点：

- 定义清晰的 Task / Plan / Step / Trace 数据结构。
- 让任务状态迁移可测试。
- 让工具调用、确认、失败、验证和最终摘要进入统一 Trace。
- 让写入回退、失败重试、暂停恢复成为 Runtime 能力，而不是某个 prompt 的偶然表现。
- 让上下文来源、证据、摘要和未验证项可追踪。
- 让工具通过 Capability Contract 接入，而不是只暴露函数名。
- 区分本地文件写入与更广义的可观察状态变更，让 MCP、CAD、数据库和浏览器
  自动化通过统一的 `effects / roles / artifacts` 事实进入任务验收。
- 区分 Capability 与 Provider：任务层看能力，Runtime 层记录 provider kind
  （builtin、cli、mcp、desktop、capability_pack、external_plugin、ai_draft）和 provider
  健康状态，避免 MCP、CLI、插件各自形成独立执行体系。

Task Model 见 [task-model.md](task-model.md)，Context Runtime 见 [context-runtime.md](context-runtime.md)，Capability Runtime 见 [capability-runtime.md](capability-runtime.md)，Experience Runtime 见 [experience-runtime.md](experience-runtime.md)，Document Draft Runtime 见 [document-draft-runtime.md](document-draft-runtime.md)，当前代码层基础契约见 [runtime-foundation.md](runtime-foundation.md)。

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
  -> Model Harness
  -> Tools / Model Providers
  -> Streamed Process Trace
```

这层策略目前集中在 `runtime/agent_strategy/`：

- `classifiers.py`：工具事实分类、进度观察和协议辅助；不承担用户意图或执行路线判断。
- `capability_router.py`：能力契约、模型路由提案和提案验证。
- `conversation_task_context.py`：判断是否存在近期任务上下文，并暴露 Task Lineage
  候选；候选按字段区分用户原话、旧模型目标/总结和 Runtime 观察事实，只有模型显式
  引用 candidate 后，Runtime 才允许应用连续任务锚点。
- `project_context.py`：把任务关系与当前工作对象关系分开，生成当前任务理解、
  Runtime 可审计的 Active Focus Snapshot，不替模型选择目标。
- `profiles.py`：模型任务契约可选的内部 Profile 描述，例如直接问答、项目分析、代码修改、外部能力执行、文档工作流、论文工作流；Profile 不生成固定阶段序列。
- `policy.py`：只处理用户显式的计划开关；自动模式由模型任务契约或模型计划判断器决定，不使用关键词和请求长度路由。
- `prompts.py`：运行事实提示、修复建议、验证建议和最终回答提示等 prompt 构建；提示不替模型指定工具路线。
- `plan_tracker.py`：执行计划的提取、归一化、推进和收尾。

新增能力时优先扩展这些模块，而不是继续向 `conversation_runner.py`
主循环里堆分支。`conversation_runner.py` 应尽量保持为编排层：
它负责串起上下文压缩、计划、模型循环、工具执行和确认机制。
`runtime/run_execution_state.py` 集中保存跨轮次生命周期事实，包括轮次预算、
模型传输计数、插话复位、完成自审和停滞观察。它只是显式状态容器，不根据这些
事实推断任务意图，也不选择工具或执行路线。
`runtime/tool_call_loop.py` 负责单轮模型流协议，把内容与推理增量、heartbeat、
工具调用参数片段、请求预算、模型错误和插话中断整理成可审计事实；它不判断
任务意图、工具路线、完成状态或验证策略。
`runtime/model_harness.py` 位于 `ToolCallLoop` 与模型 provider client 之间，
只处理 provider/model 的请求形态、工具/视觉/推理字段和传输级降级；它不选择
任务、工具、能力路线或完成条件。模型差异优先沉淀到 Harness，而不是回流到
`conversation_runner.py`。
`runtime/tool_execution_batch.py` 执行模型已经提出的一个工具调用批次，维护
侦察签名、写入修复状态和读取范围等执行账本，并保证所有 tool response 先于
运行时事实提示返回模型；它不替模型选工具或改写任务契约。
`runtime/run_finalizer.py` 在模型/工具循环结束后，把已观察事实收束为
`RunResult`、恢复 Checkpoint、最终答复、摘要 Context Pack、持久化消息和
`done` 事件；它不判断是否继续循环，也不替模型选择任务、工具或验证路线。
工具事件的前端预览、进度摘要和回填给模型的压缩 payload 由
`runtime/tool_event_presentation.py` 负责，避免 API Handler 直接承载展示规则。

当前原则是让第一层任务理解更多交给模型，Runtime 负责能力目录与执行契约：

```text
Model proposes and may revise: goal + capability + tool + expected artifacts
Runtime validates: protocol integrity, known capability, permission, confirmation, trace, execution evidence
```

Capability Router 草案见 [capability-router.md](capability-router.md)。

模型提出的目标、预期产物和路径属于当前任务理解，不是运行时强制锁定的目标。
Runtime 可以审计“声明与结果是否一致”，但不应因为路径提示或预先计划阻止模型
根据执行证据调整策略。只有权限、路径边界、确认和完整工具协议属于硬执行边界。
完成收束也应基于任务证据而不是文件类型：写入和外部状态任务观察目标产物，只读
分析和回答型任务观察证据工具结果；随后由模型基于 RunResult 事实自审是否继续或
收束。模型选择收束时通过首行短记录 `completion_self_assessment.v1` 明确声明目标
是否闭合、剩余工作和验证边界，用户可见答复仍是普通 Markdown；Runtime 不从自然
语言总结里猜测完成语义，只把该声明与工具证据状态做单向一致性合并：模型可以把
表面成功降为部分完成，但不能把缺少产物或
验证的 Runtime 结果升级为成功。最终 `RunResult` 同时保留 `evidence_status` 和
`completion_assessment`，使任务状态、最终答复和审计证据保持一致。

## 扩展原则

- 用户侧保持统一终端，内部通过 Profile 区分执行策略。
- 基建优先级高于功能清单：先让 Task、Context、Capability 三条执行主线和 Experience 学习层清楚。
- 新增任务类型先补 Profile / Policy / Prompt / Plan 测试，再接入主循环。
- 工具权限、安全确认和路径边界留在执行层，不由 prompt 或 UI 文案代替。
- 前端过程记录应展示 Runtime 的真实执行轨迹，而不是隐藏计划、推理、工具事件。
