# Task Model Draft

YuntaoCode 的核心对象应该逐步从“对话消息”上移到“任务”。

对话仍然是用户入口，但 Runtime 需要围绕 Task 管理目标、计划、步骤、工具调用、确认、错误、恢复和最终结果。这样即使模型、UI 或工具协议变化，任务执行体系仍然可以复用。

## 为什么是 Task

Tool 只能说明系统“能做什么”。

Task 才能说明系统“正在为什么目标做什么、做到哪一步、依据是什么、失败后如何恢复”。

第一层任务理解不应主要依赖关键词分类。更合适的分工是：模型负责理解用户目标并提出任务路由，Runtime 负责校验能力契约、权限、确认、产物和执行轨迹。

如果把模型替换掉，YuntaoCode 仍应保留这些价值：

- 本地任务状态管理。
- 可观察的执行过程。
- 可恢复的写入和工具调用。
- 可审计的模型与工具协作记录。
- 可复用的任务模板。

## 概念结构

```text
Task
  -> Goal
  -> Context
  -> RouteProposal
      -> Capability
      -> Tool
      -> ExpectedArtifact[]
  -> Plan
      -> Step[]
  -> Trace
      -> ModelEvent[]
      -> ToolEvent[]
      -> ConfirmationEvent[]
      -> ErrorEvent[]
  -> Recovery
      -> Checkpoint[]
      -> RetryPolicy
      -> RollbackRecord[]
  -> Result
```

## Task

Task 是一次用户目标的执行实例。

建议字段：

```json
{
  "id": "task_xxx",
  "conversation_id": "conv_xxx",
  "workspace_id": "workspace_xxx",
  "name": "分析项目代码",
  "goal": "分析当前项目结构并给出下一步开发建议",
  "kind": "project_review",
  "state": "running",
  "created_at": "...",
  "updated_at": "...",
  "metadata": {}
}
```

## Route Proposal And Capability

RouteProposal 是模型对任务的结构化理解，Capability 是 Runtime 对可执行能力的契约。

```json
{
  "goal": "把 PDF 转成带图片和文字的 Word",
  "capability_id": "document.pdf_to_docx",
  "tool_id": "document.extract_pdf_to_docx",
  "expected_artifacts": ["docx"],
  "requires_write": true,
  "requires_verification": true,
  "confidence": 0.86
}
```

原则：

- 模型可以提出路由，但不能发明不存在的能力或工具。
- 系统只接受通过 Capability Contract 验证的提案。
- 需要文件产物的任务必须产生真实 artifact，不能只用自然语言宣布完成。
- 任务成功由 Trace、ToolEvent、Artifact Verification 决定。

## Task Contract

当前 Task Contract 是主执行模型声明的审计状态，不再作为执行前的独立语义裁决。

Run 默认直接进入主模型/工具循环；初始记录使用 `source=main_execution_pending` 和 `intent=undetermined`，只保存用户原话，不替模型分类目标。主执行模型可选调用 `runtime.update_task`，记录或修订 goal、状态变化、验证需求、产物和计划，来源为 `model_execution`。Runtime 校验字段与权限边界，不调用另一个模型重新解释插话。

该协议由 `runtime/task_state_control.py` 管理，是每个 Run 的控制消息，不注册成外部 Capability 或 `runtime.skills.*`。普通工具调用不以声明为前提。声明响应与同批真实工具响应保持顺序；声明本身不会产生 ToolTask、写入或外部状态变化的成功证据。

模型可使用如下声明；权限、确认策略和访问范围不能通过该工具修改：

```json
{
  "goal": "创建并验证模型",
  "intent": "write_required",
  "requires_write": false,
  "requires_state_change": true,
  "requires_verification": true,
  "required_verification_modalities": ["structural", "visual"],
  "capability_ids": ["mcp.blender"],
  "deliverables": [{"kind": "external_state", "capability_id": "mcp.blender"}],
  "plan": ["创建模型", "读取结构并检查预览"]
}
```

计划仅由主执行模型按需在同一执行流中记录。Runtime 不再提供独立规划调用、计划提示注入、固定回退步骤或工具到步骤的自动匹配。旧 `planning_policy` 数据可以读取，但不改变执行流程；界面已移除计划策略开关。插话作为原始 user 消息进入当前上下文，不自动中断计划、不重判契约、不叠加高优先级任务解释。主模型可以继续原任务，也可以根据用户明确要求修订目标。

下面是持久化契约的兼容结构；旧字段仍可用于读取历史记录：

示例：

```json
{
  "goal": "创建一个可以显示 3D 模型的 HTML 示例页",
  "intent": "write_required",
  "requires_write": true,
  "requires_state_change": true,
  "requires_verification": true,
  "requires_plan": false,
  "deliverables": [
    {
      "kind": "file",
      "path_hint": "model-viewer.html",
      "description": "Three.js 模型查看器示例"
    }
  ],
  "first_action": "write",
  "execution_advisories": [],
  "confidence": 0.8
}
```

Runtime 负责：

- 将模型契约规范为稳定 schema。
- 应用 `只分析/不要修改` 这类硬边界。
- 校验写入、验证、文档覆盖等成功条件。
- 记录 `task.contract` 事件，供审计和 UI 展示。

`requires_write` 只表示任务必须产生或修改本地文件。
`requires_state_change` 表示任务必须产生可观察状态变化，范围还包括 Blender/CAD
场景、浏览器会话、数据库或其他外部应用。工具通过 `effects`、`roles` 和
`artifacts` 将实际执行事实回传，Runtime 再判断目标产物角色是否满足。

`requires_write=false` is not a no-write permission lock. It means a local file
write is not required for completion. When the user request is ambiguous, the
model may still decide that a repair write is the best strategy unless the user
explicitly asks for analysis only. Runtime records such writes as observed
state changes and keeps them separate from target deliverable satisfaction.
If an optional write is not followed by observed verification, Runtime records
`optional_write_not_verified` as audit evidence instead of turning the task
contract into a hard execution lock.

Task Contract can also declare `required_verification_modalities`. This field
describes the evidence shape needed to consider the task complete, not a tool
mandate. The current modalities are:

- `structural`: state, object, file, or metadata facts prove the target exists.
- `visual`: screenshots, renders, page captures, or image artifacts prove what
  the user can see.
- `behavioral`: tests, builds, commands, or runtime checks prove behavior.
- `content`: text/document inspection proves output content.

For visual goals such as UI layout, webpage appearance, rendered images, or
Blender/CAD model quality, structural facts like object counts are useful but
do not replace visual evidence. Runtime records missing visual evidence in
RunResult instead of silently treating a structural inspection as full
completion.

### Task Continuity And Deliverable Paths

The model declares whether the current request is `new`, `continue`, `revise`,
or `replace`. For `continue/revise`, Runtime keeps the previous semantic target
as a `continuity_anchor`, while the current user request becomes the revision
instruction. An execution fallback must not silently replace the user goal.

`path_hint` is a preferred location rather than a completion lock. Runtime
accepts a same-kind artifact written to another path and records the deviation
for audit. Only `path_policy: "exact"` requires an exact path match.

## Lifecycle

任务状态应比普通消息状态更明确：

```text
created
  -> planning
  -> running
  -> waiting_confirmation
  -> verifying
  -> completed

created/running/waiting_confirmation/verifying
  -> failed
  -> cancelled
```

## Plan And Step

Plan 是任务的可展示执行方案，Step 是可推进的最小阶段。

```json
{
  "title": "计划执行",
  "steps": [
    {
      "id": "step_1",
      "title": "定位相关代码",
      "description": "扫描目录并读取与需求相关的文件",
      "tool_hint": "filesystem.scan_folder / code.search_text",
      "state": "completed",
      "started_at": "...",
      "completed_at": "...",
      "result_ref": "trace_event_xxx"
    }
  ]
}
```

原则：

- Step 不应只是 prompt 文案。
- Step 应能关联工具调用、模型输出和结果摘要。
- Step 状态变化应可测试。

## Trace

Trace 是任务审计的基础。

当前已有的 run events 可以逐步收束为更稳定的事件类型：

```text
task.created
task.planning
plan.generated
step.started
model.reasoning
model.message
tool.started
tool.completed
tool.failed
confirmation.requested
confirmation.resolved
checkpoint.created
recovery.retry
task.completed
task.failed
```

Trace 的目标不是“展示热闹过程”，而是：

- 用户能知道系统为什么这样做。
- 开发者能复盘失败位置。
- 测试能断言状态迁移。
- 支持 replay / resume 的证据基础。

## Recovery

Recovery 是 YuntaoCode 区别于普通 AI Chat 的关键能力。

- 写入前创建 checkpoint。
- 工具失败后记录可恢复原因。
- 对可恢复失败生成明确 retry prompt。
- 最终结果里说明已验证内容和未验证风险。

## Template

Task Template 是比 prompt 更稳定的复用单元。

一个模板可以包含：

- 适用任务类型。
- 默认 Plan 结构。
- 允许工具集合。
- 验证要求。
- 失败恢复策略。
- 最终输出格式。

示例：

```json
{
  "id": "code_change.v1",
  "name": "代码修改任务",
  "steps": [
    "定位相关代码",
    "分析修改点",
    "执行代码变更",
    "验证结果",
    "汇总变更"
  ],
  "required_trace": ["tool.completed", "checkpoint.created"],
  "verification": ["git.diff", "shell.run_command"]
}
```

## 当前代码映射

### 执行结束、目标完成与验证

RunResult 分别记录 `execution_status`（`completed / failed / stopped`）、
`goal_status`（`unknown / complete / incomplete`）和 `verification_status`
（`unknown / not_required / missing / satisfied`）。执行正常结束不证明用户目标完成。
没有完成声明时，目标保留 `unknown`，不改变已经观察到的工具执行评价；
不会因此触发新的模型裁决调用或强制继续执行。`goal_status=complete` 表示模型
明确声明目标完成，来源见 `completion_assessment`，不表示 Runtime 已验证完成。
缺少产物或验证证据会保留对应风险并使兼容 `status` 为 `partial`；只有实际错误
才能支持失败结论，不能把“不曾观察到”直接解释成“执行失败”。
无工具直接回答仍可在一次主模型响应内结束。历史契约和旧记录继续兼容读取，
不回写其完成结论。

Task 状态投影正常结束的执行：成功 Run 对应 `completed`，不要求额外调用
`runtime.update_task`。这不把 `goal_status=unknown` 改成 `complete`；目标声明
与执行状态保持独立。只有模型显式声明 `incomplete` 时，成功执行对应的 Task
仍为 `paused`。`metadata.run_outcome` 保存当前 Run 的来源和目标声明事实，避免
结果事件被裁剪后改变投影，也不能把旧 Run 的声明带入新的尝试。

`runtime.update_task` 可在同一执行循环里声明任务、计划、`completion` 和
`step_updates`。声明采用字段增量更新，至少包含一个字段；可以只提交
`completion` 或计划进度，无需再次填写目标及验证要求。完成声明只记录模型判断，
不能升级缺少产物或必需验证的证据结果，也不能把任意代码输出提升为可信写入。
步骤更新使用零起始 `index`，可引用当前 Run 已观察到的 `tool_task_ids`；未知引用
或失败调用不能作为步骤完成证据。没有引用的完成步骤标明 `model_declared / unverified`。
工具成功仅更新调用观察，标题关键词和循环结束不会自动完成或跳过步骤。

Task Store 的变更经过 `ProductTask.transition`。未完成任务的新尝试先进入
`resuming`；已完成或取消任务的显式回放创建新 Task 并记录 `source_task_id`。
旧 Run 的延迟事件不覆盖当前 Run。普通新消息默认创建新 Task，继续关系通过
显式 `task_id`、`source_run_id` 或回放记录表达，不用关键词猜测。用户原始
`goal` 与有来源的 `metadata.model_understanding` 分开保存。

流式请求在持久化用户消息前检查 Task / Run 引用、所属会话和可启动状态。
启动预约按请求独占，准备失败或取消会释放；HTTP 断线只退订事件，不移除后台
执行的停止句柄。占用和执行句柄由后台任务的结束回调释放。

公布 `result` 后，执行事件不能重新打开 Run 或覆盖该结果；收束期仍可补充
检查点和只读审计材料。`done` 或启动恢复标记 `interrupted` 后，所有新持久化
事件以 `late_event / run.late_event` 保存，原始紧凑事件放在 `original_event`。
这些记录不参与 Task 状态、任务理解、最终结果投影，在线客户端也只收到该审计
封套。重复结束事件遵循相同规则。用户停止不能被迟到调用或成功结束事件撤销。
这些保护读取持久的 `stage / status`，不依赖结果和停止事件仍处于日志保留窗口。
结果后的检查点保持 `stage=result`，只增加审计材料，直到 `done`。
用户在最后一次模型响应或变更摘要期间暂停时，收尾等待用户恢复后才公布结果。

Run 使用一个固定的模型轮次资源上限，默认 120；任务声明和工具结果不改变
可用轮数。轮次耗尽是资源事实，不是系统对任务是否值得继续的判断。Provider
错误、HTTP 错误和连续空闲超时耗尽传输重试时，也会生成 RunResult、恢复检查点、
助手消息和 `done`。没有工具证据时保留实际失败，已有变更仍保留为产物事实；
传输模块不自行决定 Task 完成或根据已有证据跳过收尾。

任务声明直接按模型看到的参数 Schema 校验，包括嵌套枚举、未知字段、长度和
数量。无效声明整体拒绝，不通过清洗丢弃验证要求；步骤的实际引用证据仍由
Plan Tracker 检查。验证模态必须与更新后保留的 `requires_verification=true` 一致。
后续声明省略的语义字段沿用已有理解，进度报告不会清空交付物或验证模态；
`model_explicit_fields` 只记录当次实际提供的字段。

现有代码已经有 Task Runtime 的雏形：

- `runtime/core/task.py`：用户目标级 Task / Plan / Step 初始 schema，区别于一次工具调用的 ToolTask。
- `runtime/product_task_store.py`：产品级 Task、Checkpoint、ContextSnapshot 的 SQLite 持久化边界。
- `/tasks`：产品级 Task API；`/tool-tasks`：一次工具调用记录 API。
- Replay / recovery 创建新的 Run，并通过 `source_run_id`、`parent_run_id` 和 `resume_from_checkpoint_id` 保留血缘。
- `runtime/core/events.py`：TraceEvent 初始 schema 和稳定事件名方向。
- `runtime/core/result.py`：RunResult 公共 schema 常量和结果事实结构。
- `runtime/conversation_runner.py`：当前主编排层。
- `runtime/run_execution_state.py`：单个 Run 的跨轮次生命周期状态，不承担任务理解或路线选择。
- `runtime/tool_call_loop.py`：单轮模型流与工具调用协议边界，只返回传输和协议事实，不决定任务策略。
- `runtime/tool_execution_batch.py`：执行模型提出的工具批次，维护执行状态与消息协议顺序，不选择工具。
- `runtime/run_finalizer.py`：循环结束后的结果收束边界，负责 RunResult、恢复点、最终展示和消息持久化，不决定是否继续执行。
- `runtime/agent_strategy/profiles.py`：内部任务 Profile。
- `runtime/agent_strategy/policy.py`：模型声明到内部 Profile 的映射。
- `runtime/agent_strategy/plan_tracker.py`：可选计划记录与模型明确声明的步骤更新。
- `runtime/task_store.py`：本地工具任务记录。
- `runtime/run_events.py`：版本化运行事件与规范事件名。
- `runtime/run_result.py`：基于工具事件生成确定性运行结果。
- `runtime/run_completion.py`：保留完成证据包和旧版模型完成声明的兼容解析；主循环
  不再插入完成审查。普通非空答复表示模型选择结束执行循环，工具调用表示继续。
  Runtime 不从最终答复关键词推断任务完成状态，也不因验证缺口强制重入。
- `runtime/panel/static/panel.js`：流式过程展示。

RunResult 将执行证据和语义闭合判断分开记录：

- `evidence_status` 来自工具、产物、验证、错误和 Runtime 边界事实。
- `completion_assessment` 是兼容字段，来自模型主动提供的 `goal_closed`、剩余工作
  和验证边界声明；Runtime 不要求模型生成该字段。
- 最终 `status` 只允许模型声明降低成功状态，不允许模型声明覆盖 Runtime 已观察到
  的失败、缺少目标产物或验证缺口。

交付、验证及文本要求由 `run_result.py` 一处归纳。API 不再独立检查任务契约，
Finalizer 正常收尾只构建一次结果；仅在缺少最终答案、确实生成了新答案后重算。
历史 `contract_failures` 记录仍保留，不回写已有 Run 的结论。

下一步不是立即重写，而是逐步把隐含概念显式化：

1. 给 Task / Step / Trace 定义稳定数据结构。
2. 把 run events 向稳定事件名收敛。
3. 为状态迁移补测试。
4. 再考虑 Task Template 和恢复接口。

当前代码层基础契约见 [runtime-foundation.md](runtime-foundation.md)。
