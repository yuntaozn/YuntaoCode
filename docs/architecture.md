# 架构说明

## Frontend Run State Reconciliation

前端流连接与后台 Run 生命周期分别记录。正常 `done` 与轮询确认的已封存终态
使用同一条最终消息展示路径；当流结束事件丢失或接收连接悬挂时，前端读取对应
Run 的 `done`/`interrupted` 终态及持久对话，保留最终原文、推理和工具过程，清除
本地 pending、计时器和发送占用。这个过程只关闭本地接收连接，不发送 Run 停止
或重试操作；查询失败、`result` 中间阶段及仍在执行的 Run 都不能被推断为已结束。
异步恢复前后核对原 stream 对象，避免旧请求清理覆盖同一对话的新运行。

Panel HTML 由 Tornado 模板渲染，HTML 保持 `no-store`，JS/CSS 使用 `static_url`
生成内容指纹。资源内容更新后获得新 URL，避免固定版本参数把旧执行界面长期缓存。

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

模型调用边界进一步分为两类：主执行循环由 `ToolCallLoop` 处理流式响应、
工具调用和心跳；用户直接请求的非流式回复等调用由
`runtime/model_calls.py` 统一记录目的、耗时、超时、取消和审计事件。后者只
管理调用生命周期，不解释任务语义，也不替模型决定执行路线。

模型可见工具由 `runtime/tool_discovery.py` 按显式查询加载。首轮仅发送发现入口，
模型选择查询词或工具 ID 后，后续轮次携带相应原始 schema；执行仍通过
`ToolExecutionBatch` 与 `TaskRunner`。目录刷新能反映新连接的 MCP，不通过用户
关键词或辅助模型预选能力。完整能力快照、工作区快照和 Context Ledger 保留在
审计记录中，不作为默认 system 上下文重复发送。

执行前 Guard 只承担可用性、参数和草稿写入边界，不按任务契约生成路线建议。
工具风险投影保留结果事实与稳定诊断码，不选择下一步工具、验证方法或恢复路线。
权限和操作确认仍由原有执行层检查，任务交付与验证证据由 RunResult 汇总。

协议与工具错误只返回观测事实，不携带推荐方法或替代工具清单；主模型可自行
继续调用或结束。无效批次不执行，统一轮次预算是资源上限。任务预检不启动服务，
服务生命周期由显式管理配置负责。收尾持久化主模型原文，不剥离答案首行 JSON、
不调用第二个模型补写答案，也不向正文追加文件清单；变更和错误保留为独立审计。

模型轮次采用 `terminal_profile.py` 配置的统一资源上限，默认 120 轮，等于此前
40 轮初始预算的三倍绝对上限。移除依据任务类型、成功读取、写入或“进展”延长
预算的门槛；发现工具、状态声明、失败及正常执行都计入相同上限。
传输层只报告 Provider 错误和空闲超时，不读取已有工具证据来决定是否收尾。
错误或重试耗尽仍进入 `RunFinalizer`，保存原始错误、已有变更和恢复点；主模型
已经输出的文本保持原样，不因传输失败触发另一个模型补写。
流式请求以实际收到的数据判断空闲，默认空闲上限 240 秒、连接上限 20 秒；
持续收到数据时不因请求累计到 300 秒而截断。后台请求异常先进入错误事件再
结束流，不能作为普通结束信号静默丢失；用户取消仍清理后台请求。

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

当前界面保持一个统一终端。任务理解、路线与计划由同一个主执行模型持续负责；Runtime 记录其声明和工具事实：

```text
User Request
  -> Conversation Runner / Model Harness
  -> Main Execution Model <-> Tools
  -> Optional Task / Plan / Step Declarations
  -> Runtime Validation / Streamed Process Trace
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
- `policy.py`：把模型声明的任务语义映射到内部 Profile，不生成前置规划阶段。
- `runtime/task_state_control.py`：接收主执行模型可选的任务与计划声明，仅更新审计状态，不执行外部操作、不授予权限。
- `prompts.py`：运行事实提示、修复建议、验证建议和最终回答提示等 prompt 构建；提示不替模型指定工具路线。
- `plan_tracker.py`：保存模型自愿声明的计划和步骤更新，校验证据引用；不生成回退计划，不匹配工具，不推断步骤完成。

新增能力时优先扩展这些模块，而不是继续向 `conversation_runner.py`
主循环里堆分支。`conversation_runner.py` 应尽量保持为编排层：
它负责串起上下文压缩、模型循环、工具执行和确认机制。计划只作为可选审计记录，不能注入新的执行指令或成为执行门槛。
`runtime/run_execution_state.py` 集中保存跨轮次生命周期事实，包括轮次预算、
模型传输计数、用户插话和瞬时上下文。它只是显式状态容器，不根据这些
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
执行模型已经给出可用最终答复时，该答复保持为用户可见内容的权威来源；
`RunResult` 的 partial、failure、stopped 等状态作为独立事实和风险保留，不触发
第二次模型调用改写答复。只有最终内容缺失或仍含未解析工具协议时，才允许结果合成
补齐展示内容。
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
收束。模型返回普通非空答复且不再调用工具时，Runtime 将其记录为模型选择结束执行
循环；验证缺口继续保留在 `RunResult`，但不据此强制模型重入。模型也可通过可选的
`runtime.update_task` 声明目标是否闭合、剩余工作和验证边界。最终答复保留主模型
原文；Runtime 不解析普通答复 JSON，也不从自然语言总结里猜测完成语义，
`goal_status` 只呈现模型明确的目标声明，与执行及验证状态分开。兼容的汇总
`status` 仍进行单向一致性合并：模型可以把
表面成功降为部分完成，但不能把缺少产物或
验证的 Runtime 结果升级为成功。最终 `RunResult` 同时保留 `evidence_status` 和
`completion_assessment`，使任务状态、最终答复和审计证据保持一致。

结果归纳由 `run_result.py` 单独负责，API 不再另行裁决任务契约。缺少产物证据
属于未知或证据不足，以 `partial` 和风险呈现，不直接判失败。没有可选的完成
声明也不降低工具执行评价。成功 Run 的 Task 投影为 `completed`，目标声明仍可
为 `unknown`；显式 `incomplete` 仍保持开放。这不要求模型额外填写状态才能结束。
普通收尾仅构建一次结果，不再调用另一个模型补答。用户暂停在公布结果前生效；
结果和停止保护基于持久生命周期状态，日志保留窗口不影响该边界。

## 扩展原则

- 用户侧保持统一终端，内部通过 Profile 区分执行策略。
- 基建优先级高于功能清单：先让 Task、Context、Capability 三条执行主线和 Experience 学习层清楚。
- 新增任务类型先补 Profile / Policy / Prompt / Plan 测试，再接入主循环。
- 工具权限、安全确认和路径边界留在执行层，不由 prompt 或 UI 文案代替。
- 前端过程记录应展示 Runtime 的真实执行轨迹，而不是隐藏计划、推理、工具事件。

## 2026-10-21 执行主链复查

本次复查沿对话入口、上下文、Provider 协议、工具执行、证据、完成判定、
Task/Run 状态及恢复记录检查当前工作树。下面区分已复现问题与调整建议；
这不是所有 Provider 的兼容性认证，也不表示后续改造已经完成。

### 已确认的结构性缺口

| 优先级 | 代码位置 | 已复现事实与影响 |
| --- | --- | --- |
| P1 | `conversation_runner.py`、`run_result.py::_result_status` | 当前任务声明可选，缺省契约仍未确定目标。只执行一次场景读取、没有产物和完成声明，也能得到 `success`。调用成功与用户目标完成共用了一个结论。 |
| P1 | `conversation_runner.py`、`agent_strategy/classifiers.py::extract_native_tool_calls` | Runner 把正文和 reasoning 拼接后解析文本工具标记，且未按 Provider 协议限制。带“仅为示例”文字的完整标记仍会被识别为调用。现有权限与确认继续生效，但思考或引用内容可能成为执行候选。 |
| P1 | `api/conversations.py::_execute_tool_call`、`tool_event_presentation.py::tool_output_preview` | ToolEvent 的 `output` 来自前端预览，RunResult 又消费该事件。一次 patch 涉及 41 个路径时，预览只保留 40 个，展示预算会改变审计和产物证据范围。原始 ToolTask 输出仍在，问题是下游证据使用了展示投影。 |
| P1 | `core/task.py`、`product_task_store.py`、`api/conversations.py` | Schema 定义的状态图不允许 `completed -> running`，Store 的 `update_state` 仍可完成该转换。普通新消息没有显式 `task_id` 时会创建新 Task，模型的当前目标只更新 Run 契约，尚未形成稳定的用户目标记录。 |
| P2 | `agent_strategy/plan_tracker.py` | 步骤依靠标题关键词和工具类别匹配，单次工具成功便标记完成。“验证模型已创建并保存”可被一次 `git.status` 成功标为完成；普通读取步骤也可能因工具同时属于 verification 类而匹配失败。步骤状态没有绑定具体结果证据。 |
| P2 | `run_events.py`、`tool_call_loop.py`、`run_recovery.py` | 主模型轮次缺少独立持久化的协议摘要；结束原因主要汇总在最终消息中，难以区分 Provider 未发调用和适配器丢失调用。恢复快照还把模型任务契约标为 `runtime_fact`，恢复文本没有完整呈现该契约的目标与来源。 |

以上问题说明，删除隐藏语义裁决只是第一步。Runtime 的“事实”必须保留
来源和不确定性，不能由工具名称、界面预览、步骤标题或一次正常收尾推导出来。

### 建议收敛的基础契约

- 主执行模型持续解释用户目标、选择工具和修订计划；用户原话、模型声明与
  实际观察分别记录来源，不再增加独立的任务裁决调用。
- Task 表示持续的用户目标，Run 表示一次尝试，ToolTask 表示一次能力调用。
  Run 正常结束、目标是否完成、验证是否充分分别记录；缺少目标或闭合声明时
  保留未知状态，避免推断成功，也不据此强制模型重入。
- 原始工具输出经规范化生成证据，再分别投影为前端预览和模型上下文。
  前端显示数量与字符串长度上限不能裁剪运行事实。
- Provider 适配器输出有来源的结构化调用；需要文本调用兼容的 Provider 应
  显式声明该协议。reasoning 和引用示例只作为内容，不能自动升级为调用。
- 模型声明步骤进展并引用调用或证据；Runtime 校验引用存在及状态，不依据
  中英文关键词决定步骤已经完成。
- Task 状态变更通过单一状态迁移入口；恢复沿用目标与证据来源，并重新观察
  当前文件或外部应用状态。权限、PathGuard 和操作确认继续由执行层负责。

### 调整顺序与验收

1. 先修复确定的协议与收尾错误。当前已修复缺失调用载荷时的静默成功路径，
   允许一次有界补发，并修复结果整理适配器重复转发 `settings` 的接口错误。
   这些修复不解决上表中一般性的目标未知却判成功问题。
2. 拆分 Run 结束、Task 完成和验证结论，建立证据规范化边界；通过“仅只读探测”
   与“实际产物并验证”成对用例验收，保留正常直接问答的一次主模型调用路径。
3. 收敛 Task 身份、状态迁移和计划更新，验证插话、确认、重试与显式新任务的
   关系；不通过关键词自动继承或取消用户目标。
4. 收敛 Provider 调用解析与每轮协议审计，再验证恢复、MCP、内置工具和模型
   上下文对同一份证据的使用。测试应包含原始 Provider 事件到实际执行的链路，
   不能只模拟已经归一化的工具调用。

这是一组小步改造顺序，保留当前本地优先、统一执行入口和独立能力 Provider
的基础。后续验收应围绕实际副作用、证据与状态一致性展开，测试总数只是辅助指标。

### 当前已落实的第一轮改造

执行、目标和验证状态已分别记录；目标未声明或未闭合时保留未知状态。
工具结果先形成独立证据，再投影为前端预览和模型上下文；路径与诊断不受
前端显示数量限制。文本调用恢复改为 Provider 显式配置，只接受完整正文协议，
reasoning 与示例不进入执行。主模型每轮协议摘要进入持久化 Trace。

Task Store 已执行状态图、忽略旧尝试的延迟状态，并分别保存用户目标和模型
理解。显式重试沿用未完成 Task，终态 Task 的回放创建有来源关系的新 Task；
普通新消息的语义关系仍由用户或模型表达，Runtime 不自动合并历史任务。
计划进度通过模型声明与证据引用更新，恢复上下文保留目标来源与可信度。
以上行为的具体契约见 [task-model.md](task-model.md)、[tool-protocol.md](tool-protocol.md)
和 [model-harness.md](model-harness.md)。

### 第二轮生命周期与协议校验

流式入口在消息落库前检查引用和可启动状态；启动预约由请求独占，准备失败
释放占用，断线后执行句柄保留到后台任务结束。已公布结果及结束后的迟到执行
事件不会重新打开 Run / Task，原始紧凑事件通过 `late_event` 留在审计链。
结构化调用的索引、字段和整批完整性在执行前校验，畸形条目不会被 Provider
适配器静默丢弃；任务声明按其公开 Schema 校验，省略字段沿用已有语义。

本地真实模型验收已走通官方 Blender MCP 的读取、建模、错误修正、保存副本、
对象回读和截图调用；保存文件也经独立 Blender 进程重新打开检查。该实验只能
认定执行与结构证据成立：首次失败留下了额外对象和集合，截图像素全部为黑，
而模型最终答复仍声称视觉可见。该实验时 MCP 图片仍作为工具结果文本序列化，
没有独立图片内容块进入模型请求。这暴露出后续需要处理的媒体传输与验证证据
边界，不能把截图调用成功视为视觉验收通过，也不应通过新增场景关键词裁决解决。

### 第三轮媒体证据桥接

内联 MCP 图片现在经原始 ToolTask 引用进入现有视觉上下文桥接，并以独立图片
内容块传给主模型。原始二进制不复制到审计或工具文字上下文。尺寸和单色像素
只作为观察；附件准备、Provider 接受、文本降级与视觉审查结论分别记录，
失败调用也明确保留部分副作用和回滚的未知状态。未增加 Blender 路线分支或
独立的视觉裁决模型。

真实模型对上轮留存的全黑图片已能明确说明没有可辨识内容；实时 MCP 截图也
确认进入了 Provider 请求。单独图片描述仍出现过将相机线框误称为模型的情况，
结合只读对象类型后得到当前场景没有小龙的结论。因此本轮验收针对媒体传输与
审计边界，不把它扩大为所有视觉语义判断都可靠，也未改写此前 Run 的结论。

### 执行干预收敛

重复失败、重复读取和写入修复只产生工具结果及审计事件，不再额外追加系统
策略消息。读取范围汇总提示及相应的未使用提示构建器也已移除。主模型直接依据
原始工具结果选择下一步；协议校验、权限、PathGuard、确认及执行预算保留。
重复执行记录只保留次数和错误事实，不生成 `model_decision` 或下一步建议。
`runtime.update_task` 支持只更新完成或计划字段，目标声明与证据评价独立记录。
这次调整没有补充 Blender 路由或把任意代码执行成功视为交付成功。
