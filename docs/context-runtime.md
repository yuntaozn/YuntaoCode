# Context Runtime

YuntaoCode 不应把上下文只理解成“聊天历史 + 工具输出 + prompt”。

对于本地 AI 任务运行时，上下文是一种需要被选择、压缩、标注来源、验证有效性并可审计的运行时资源。模型上下文窗口会越来越大，但真实项目、长文档、历史对话和任务轨迹也会一直超过单次模型输入的上限。

## Core Idea

```text
User Request
  -> Task Contract
  -> Context Selection
  -> Evidence / Memory / Tool Result Boundaries
  -> Model Input
  -> Trace / Result
  -> Context Snapshot
```

Context Runtime 的目标不是把所有内容塞给模型，而是回答：

- 当前阶段需要什么信息？
- 这些信息来自哪里？
- 哪些是工具验证过的事实？
- 哪些只是模型推断或旧摘要？
- 哪些内容已经过期、未验证或被后续结果推翻？
- 压缩后哪些风险和未完成项必须保留？

## Context Layers

建议把上下文分成几个稳定层：

```text
User Intent Context
  用户最新目标、约束、偏好、本轮禁止事项。

Task Context
  task_contract、计划、当前步骤、任务状态、成功条件。

Workspace Context
  项目结构摘要、文档摘要、文件索引。

Evidence Context
  已通过工具读取的真实片段、路径、行号、页码、hash。

Tool Context
  最近工具调用、结果、错误、产物、验证状态。

Memory Context
  长期偏好、项目记忆、历史经验。

Recovery Context
  失败原因、checkpoint、重试策略、未完成项。
```

## Trust And Source

每条上下文都应携带来源和可信度，而不是混成一段普通文本。

初始 schema 已在 `runtime/core/context.py` 中定义：

```json
{
  "schema_version": "context_record.v1",
  "kind": "evidence",
  "content": "run_result.py builds deterministic facts from tool events.",
  "source_id": "file:D:/code/YuntaoCode/runtime/run_result.py",
  "source_type": "file",
  "trust": "tool_verified",
  "task_id": "task_xxx",
  "freshness": "current"
}
```

建议可信度分层：

- `user_provided`
- `tool_verified`
- `runtime_fact`
- `summary`
- `memory`
- `model_inferred`
- `unverified`

## Memory Scope

Long-term memory is part of the context runtime, so it must have explicit
scope boundaries:

- `global` memory is for user-level preferences, communication style, identity,
  language preference, and cross-project habits.
- `workspace` memory is for project-specific facts such as architecture
  decisions, paths, tech stack, task conventions, and local constraints.
- Model context may receive only global memories plus memories for the current
  `workspace_id`.
- Automatic memory extraction is intentionally global-only and narrow: it should
  store only high-confidence user-level facts. Project facts should be saved
  explicitly through a workspace-scoped memory path.

This prevents one project run from becoming hidden context for another project
while still allowing the assistant to remember stable user preferences.

## Context Snapshot

上下文压缩不应只是自然语言摘要，而应形成结构化快照：

```json
{
  "schema_version": "context_snapshot.v1",
  "task_id": "task_xxx",
  "phase": "verification",
  "summary": "The file was written; shell server verification timed out.",
  "records": [],
  "evidence": [],
  "unresolved": [
    "No browser verification was observed."
  ]
}
```

压缩后必须保留：

- 任务目标和硬约束。
- 已确认事实。
- 已读取证据。
- 真实产物。
- 工具失败和失败原因。
- 未验证项和剩余风险。
- 用户中途追加的纠偏信息。

## Phase-Aware Context

不同阶段需要不同上下文：

```text
understanding
  用户意图、最近消息、相关记忆、初始 task_contract。

planning
  任务目标、workspace 摘要、能力目录、硬约束。

execution
  当前步骤、必要证据片段、最近工具结果、失败恢复信息。

verification
  写入记录、产物路径、验证规则、失败/风险。

summary
  RunResult、变更路径、验证事实、剩余风险。
```

`runtime/core/context.py` 已提供 `select_records_for_phase()` 作为纯函数骨架。它不是最终检索实现，只是把“上下文按阶段筛选”的规则先显式化。

## Relation To Memory

Memory 是 Context Runtime 的一部分，但不能和任务事实混淆。

例如：

```text
长期偏好：用户重视开源基座，不希望盲目堆功能。
任务事实：本轮修改了 shell 超时提示。
```

长期偏好可以进入 Memory Context。任务事实应进入 Task / Tool / Evidence Context。两者需要不同生命周期和可信度。

## Current Implementation

当前已有基础：

- `runtime/context_manager.py`
  - 上下文 token 计算、自动/手动压缩入口。
  - 保留最近消息，将旧消息压缩为摘要。
  - `summary_up_to_index` 参与增量摘要，避免反复把已摘要历史重新压缩。
- `runtime/agent_strategy/context_hygiene.py`
  - 在不删除 UI 历史和审计记录的前提下，清洗模型侧上下文中的失败工具标记、半截执行过程和噪声记录。
- `runtime/tool_event_presentation.py`
  - 对工具结果做模型侧预算压缩，保留路径、错误、完整性、下一次读取提示和运行时风险。
- `runtime/workspace_snapshot.py`
  - 在不读取文件内容的前提下生成轻量项目事实快照，包括顶层目录、浅层文件类型、明显产物路径和观察线索。
  - 快照以 `context.workspace_snapshot` 事件进入 RunEvidence/Runbook/诊断包，并作为任务契约判断的事实上下文，而不是路由规则。
- `runtime/context_pack.py`
  - 将本轮用户意图、Workspace Snapshot、相关上一任务契约、当前任务契约、能力边界和上下文卫生风险组合成阶段化 Context Pack。
  - 生成 Context Ledger，记录每条上下文的 kind、source、trust、freshness、token 估算和内容 hash，便于诊断模型当时看到了哪些事实。
  - `task_contract` 阶段记录模型理解任务前的事实；`planning` 阶段记录任务契约和能力边界形成后的事实；`execution` 阶段记录最新工具结果、当前执行状态和恢复线索；`verification` / `summary` 阶段记录 RunResult、验证、风险和最终答复依据。
  - Context Pack 以 `context.pack` 事件进入 RunEvidence/Runbook/诊断包；它是可审计事实包，不是任务路由器。
- `runtime/prompt_context.py`
  - 系统 prompt 中注入工作区、记忆和执行习惯。
- `runtime/run_recovery.py`
  - 从 RunResult 生成恢复用 ContextSnapshot，并格式化为恢复上下文。
- `runtime/run_events.py`
  - 持久化运行事件，为上下文账本提供事实来源。
- `runtime/run_result.py`
  - 从工具事件生成确定性结果，可作为 summary 阶段核心上下文。
- `runtime/core/context.py`
  - ContextRecord、EvidenceRecord、ContextSnapshot 初始 schema。

## Next Steps

短期建议：

1. 让 `compress_context()` 输出结构化摘要草案，而不仅是文本。
2. 将 `task_contract`、`run_result`、失败风险写入 ContextSnapshot。
3. 让 Workspace Snapshot 支持按用户当前表达提取相关候选路径，但仍保持事实层，不替模型判断任务。
4. 为已读取文件建立轻量 EvidenceRecord，记录路径、摘要、范围和 hash。
5. 将关键 Context Pack 汇总写入 ContextSnapshot，支持暂停/恢复/回放时复用。
6. 前端展示“上下文事实/未验证项”，避免用户只看到模型总结。

中期建议：

1. 建立 Context Ledger，记录哪些上下文进入过模型。
2. 支持任务级上下文快照，用户清空聊天不应删除任务事实。
3. 为长文档、代码仓库和多轮任务引入 Evidence Index。
4. 让恢复任务优先读取 Recovery Context，而不是依赖旧对话。
