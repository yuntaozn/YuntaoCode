# Task Model Draft

YuntaoCode 的核心对象应该逐步从“对话消息”上移到“任务”。

对话仍然是用户入口，但 Runtime 需要围绕 Task 管理目标、计划、步骤、工具调用、确认、错误、恢复和最终结果。这样即使模型、UI 或工具协议变化，任务执行体系仍然可以复用。

## 为什么是 Task

Tool 只能说明系统“能做什么”。

Task 才能说明系统“正在为什么目标做什么、做到哪一步、依据是什么、失败后如何恢复”。

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

后续可以扩展：

```text
paused
resuming
rolling_back
rolled_back
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
- 未来能支持 replay / resume。

## Recovery

Recovery 是 YuntaoCode 区别于普通 AI Chat 的关键方向。

短期目标：

- 写入前创建 checkpoint。
- 工具失败后记录可恢复原因。
- 对可恢复失败生成明确 retry prompt。
- 最终结果里说明已验证内容和未验证风险。

中期目标：

- `task.pause()`
- `task.resume()`
- `task.retry(step_id)`
- `task.rollback(checkpoint_id)`
- `task.replay(trace_id)`

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

- `runtime/conversation_runner.py`：当前主编排层。
- `runtime/agent_strategy/profiles.py`：内部任务 Profile。
- `runtime/agent_strategy/policy.py`：计划执行策略。
- `runtime/agent_strategy/plan_tracker.py`：计划生命周期辅助函数。
- `runtime/task_store.py`：本地工具任务记录。
- `runtime/panel/static/panel.js`：流式过程展示。

下一步不是立即重写，而是逐步把隐含概念显式化：

1. 给 Task / Step / Trace 定义稳定数据结构。
2. 把 run events 向稳定事件名收敛。
3. 为状态迁移补测试。
4. 再考虑 Task Template 和恢复接口。
