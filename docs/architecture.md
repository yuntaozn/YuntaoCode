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

Task Model 草案见 [task-model.md](task-model.md)，Context Runtime 规划见 [context-runtime.md](context-runtime.md)，Capability Runtime 规划见 [capability-runtime.md](capability-runtime.md)，当前代码层基础契约见 [runtime-foundation.md](runtime-foundation.md)。

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
- `profiles.py`：内部执行 Profile，例如直接问答、项目分析、代码修改、文档工作流、论文工作流。
- `policy.py`：请求路由和计划执行开关；确定性规则只承担安全边界与模型不可用时的回退，不替模型决定任务目标和执行策略。
- `prompts.py`：阶段提示、修复提示、最终回答提示等 prompt 构建。
- `plan_tracker.py`：执行计划的提取、归一化、推进和收尾。

新增能力时优先扩展这些模块，而不是继续向 `conversation_runner.py`
主循环里堆分支。`conversation_runner.py` 应尽量保持为编排层：
它负责串起上下文压缩、计划、模型流、工具调用、确认机制和最终消息落库。

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
