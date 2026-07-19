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

当前基座开始引入 Task Contract 作为 RouteProposal 前的入口层。

模型先判断用户目标，输出结构化契约；Runtime 再规范字段形状、执行安全与协议边界，并基于契约记录验收证据。这样可以避免把“写 HTML”“生成视频”“转换 Word”等场景都固化成系统关键词。

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
- `runtime/agent_strategy/policy.py`：计划执行策略。
- `runtime/agent_strategy/plan_tracker.py`：计划生命周期辅助函数。
- `runtime/task_store.py`：本地工具任务记录。
- `runtime/run_events.py`：版本化运行事件与规范事件名。
- `runtime/run_result.py`：基于工具事件生成确定性运行结果。
- `runtime/panel/static/panel.js`：流式过程展示。

下一步不是立即重写，而是逐步把隐含概念显式化：

1. 给 Task / Step / Trace 定义稳定数据结构。
2. 把 run events 向稳定事件名收敛。
3. 为状态迁移补测试。
4. 再考虑 Task Template 和恢复接口。

当前代码层基础契约见 [runtime-foundation.md](runtime-foundation.md)。
