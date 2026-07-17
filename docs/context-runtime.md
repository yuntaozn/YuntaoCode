# Context Runtime

YuntaoCode 不应把上下文只理解成“聊天历史 + 工具输出 + prompt”。

在本地 AI Task Runtime 中，上下文是一种运行时资源。它需要被选择、压缩、
标注来源、声明可信度、保留证据边界，并能进入审计记录。模型上下文窗口会越来
越大，但真实项目、长文档、历史对话、工具轨迹和恢复事实也会一直超过单次模型
输入的上限。

Context Runtime 的目标不是替模型决定任务，也不是把所有历史都塞给模型，而是：

- 让模型看到完成当前请求所需的事实。
- 让模型知道哪些内容是历史支持，而不是隐藏当前目标。
- 让旧失败、旧工具调用格式和旧任务目标不污染新一轮判断。
- 让任务事实、记忆、证据、恢复线索和压缩摘要有清晰边界。
- 让用户和开发者可以审计模型当时看到了哪些上下文。

## Core Contract

```text
User Request
  -> Current Request Boundary
  -> Task Contract Context
  -> Context Pack
  -> Model Input
  -> Tool / Model Execution
  -> RunEvidence / RunResult
  -> Context Snapshot
```

Context Runtime 是提醒层和事实层，不是干预层。

模型可以根据上下文判断目标、选择能力、修改策略、继续执行或停止。Runtime 只
负责说明上下文来源、可信度、边界和风险，并保留权限、路径、确认、协议完整性等
硬执行边界。

## Context Layers

建议把上下文分为几个稳定层：

```text
Current Request Context
  用户最新消息、本轮约束、本轮补充信息。

Task Context
  task_contract、计划、当前步骤、任务状态、成功条件、未完成项。

Task Lineage Context
  相关历史任务候选、上一任务契约、可继承目标、用户追问关系。

Project Context / Active Focus
  当前工作区包含哪些项目，以及本轮实际围绕哪个项目、子项目、文件或外部对象。
  工作对象关系与任务关系独立。

Workspace Context
  工作区路径、项目结构摘要、明显入口文件、候选产物、浅层文件事实。

Evidence Context
  工具读取过的真实片段、路径、页码、行号、hash、截图、产物记录。

Tool Context
  最近工具调用、结果、错误、产物、验证状态、运行时风险。

Memory Context
  用户长期偏好、项目级记忆、明确保存的经验。

Recovery Context
  checkpoint、失败原因、恢复摘要、重试线索、暂停/恢复状态。
```

这些层可以共同进入模型上下文，但不能混成一段没有来源的普通文本。

## Trust And Source

每条上下文都应携带来源和可信度。初始 schema 在
`runtime/core/context.py` 中定义：

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

可信度建议保持小集合：

- `user_provided`
- `tool_verified`
- `runtime_fact`
- `summary`
- `memory`
- `model_inferred`
- `unverified`

Runtime 可以告诉模型“这是未验证摘要”或“这是工具验证事实”，但不应因为某条
摘要存在就锁死模型策略。

## Current Request Boundary

多轮任务里最容易出问题的是：模型把上一轮失败、上一轮工具调用格式或上一轮目标
当成了当前目标。

`runtime/agent_strategy/model_context_boundary.py` 负责模型侧边界声明：

- `model_context_hygiene_notice()` 说明历史消息被压缩，但 UI 和审计记录没有删除。
- `current_request_boundary_notice()` 明确下一条用户消息才是本轮请求。
- historical task markers 把旧任务 turn 替换为可追踪标记，细节转入
  Context Pack 的 `task_lineage`。

这层只声明边界，不分类意图，不路由任务，不阻断执行。

## Context Hygiene And Noise

UI 历史和审计记录应完整保留，但模型侧上下文需要卫生处理。

`runtime/agent_strategy/context_hygiene.py` 负责清理模型输入中的历史噪声：

- 历史文本工具调用标记，如 `<toolcall>`。
- 上一轮失败摘要和缺参数报错。
- 很长的过程记录或思考过程。
- 已转入 `task_lineage` 的历史任务 turn。

`runtime/agent_strategy/context_noise.py` 负责纯分类和摘要：

- 识别历史工具调用文本。
- 识别失败日志和过程日志。
- 生成历史失败摘要、历史过程摘要、用户引用失败输出摘要。

这两个模块只服务模型上下文卫生。它们不能变成隐藏任务路由器，也不能替代模型对
当前任务的判断。

## Task Lineage

连续任务、追问、恢复和“再试一次”需要历史联系，但不能把完整旧对话原样塞给模型。

当前方向是：

1. 从历史消息中抽取可能相关的 task candidate。
2. 在 Context Pack 中写入 `task_lineage` 记录。
3. 由模型在 task contract 阶段决定是否引用某个 candidate。
4. Runtime 只审计“模型引用了哪个候选任务”，不直接把旧任务目标强加给当前轮。

续接关系也不等于目标冻结。只有模型在当前 Task Contract 中显式选择 `continue` 或
`revise` 时，Runtime 才允许历史锚点补充当前模型遗漏的字段。当前轮明确给出的 goal、
deliverable、capability、状态变化和验证要求始终优先；“继续”“再试一次”等关键词本身
不能触发 Runtime 继承旧目标。每轮完成归一化后都应生成新的 continuity anchor，避免
旧目标在后续轮次中永久覆盖当前请求。

这样可以避免两种极端：

- 完全丢掉历史，导致追问无法理解。
- 把旧任务目标当成当前目标，导致跨项目或跨任务污染。

Task Lineage 的审计记录可以保留完整候选元数据，但模型侧表示必须按候选独立限长，
确保有限预算内仍能看到所有入选候选的 ID、目标、焦点和真实路径。不能先拼成一段很长
的 JSON，再统一截断到只剩第一个候选。

候选按时间顺序展示，不根据当前文字与历史路径的关键词重合度重新排序，也不生成
`active_target`。历史 Run 的真实写入路径保留在 `actual_paths` 证据中，不会被提升为
当前合同的 deliverable。模型显式给出的空 goal、空 capability 或空 deliverable 也是
当前判断，不能被旧锚点重新填回。

相关代码：

- `runtime/agent_strategy/task_lineage.py`
- `runtime/agent_strategy/conversation_task_context.py`
- `runtime/agent_strategy/task_contract.py`
- `runtime/context_pack.py`

## Project Context And Active Focus

Task Lineage 说明“之前做过什么”，但不能单独回答“当前正在围绕哪个对象工作”。
如果把两者混在 `scope_relation` 中，一个新的动作或产物就可能错误地清空当前子项目，
或者反过来把上一任务的旧目标强加给新任务。

当前契约将两条关系分开：

```text
scope_relation
  new / continue / revise / replace
  描述当前动作和旧任务之间的关系。

focus_relation
  explicit / inherit / switch / unresolved
  描述当前工作对象从哪里来。
```

因此“分析完某个子项目后，为它编写正式设计说明”可以是：

```text
scope_relation = new
focus_relation = inherit
```

新任务只继承项目对象，不继承旧任务的 goal、计划、工具路线或完成判断。

`runtime/agent_strategy/project_context.py` 根据模型在 Task Contract 中声明的焦点和
所引用的 task candidate，生成 `active_focus.v1` 快照。快照只包含：

- 焦点关系和模型声明的对象名称、类型、路径提示。
- 被引用的历史候选 ID。
- 候选 Run 中真实观察到的路径证据。
- 当前 workspace 路径和焦点是否已解析。

Runtime 不通过关键词替模型选择对象，也不因为 Active Focus 存在就覆盖当前 goal。
Context Pack 以 `project_context` 记录把快照传给规划、执行、验证和总结阶段。当证据
不足时保持 `unresolved`，而不是默认为整个 workspace。

## Context Pack And Ledger

`runtime/context_pack.py` 是当前 Context Runtime 的主要汇聚点。

它把以下事实组合成阶段化 Context Pack：

- 当前用户请求。
- Workspace Snapshot。
- Task Lineage。
- 当前 Task Contract。
- 与当前请求相关的 Memory Selection。
- Capability Snapshot。
- 最近工具结果、风险和验证事实。
- Context Hygiene 报告。

同时生成 Context Ledger，记录每条上下文的：

- `kind`
- `source`
- `trust`
- `freshness`
- token 估算
- content hash

Context Pack 以 `context.pack` 事件进入 RunEvidence、Runbook 和诊断包。它是可
审计事实包，不是任务路由器。

模型侧记录按语义分配预算，而不是对所有记录使用相同字符上限。记录顺序优先保持：
当前请求、相关历史候选、Active Focus、当前 Task Contract、Workspace 摘要和能力/
证据事实，避免多子项目 Workspace 先于明确焦点形成宽泛锚定。

## Visual Evidence Context

视觉证据是 Evidence Context 的一种。网页截图、文件预览、图片、PDF 页面渲染、
MCP 视口截图和外部应用截图都应先成为可审计的 `visual_evidence.v1`，再由
Context Runtime 判断是否能作为模型输入。

当前边界是：

- Runtime 不因为存在截图就判定任务完成，也不强制模型使用截图。
- 模型配置默认视为支持图片输入；如果某个接口或模型不支持多模态，应在模型设置中
  显式关闭视觉输入。
- 只有模型未关闭视觉输入时，符合边界的视觉证据才会作为 image input 加入下一轮
  模型上下文。
- 图片上下文只来自当前 workspace 或 Runtime 数据目录，避免把任意本地路径读入
  模型请求。
- 不支持多模态的模型仍会收到文本化证据，例如截图路径、尺寸、DOM 文本、
  console/page/network 错误、OCR 或运行诊断。
- 每次视觉证据注入都应写入 RunEvent/metadata，方便诊断“模型当时是否真的看到了图”。

这层让模型有机会“看见”自己刚刚生成或验证的产物，而不是把视觉判断硬编码
进系统。视觉上下文和文本上下文一样，只提供来源、可信度和边界。

## Memory Scope

Memory 是 Context Runtime 的一部分，但不能和任务事实混淆。

建议边界：

- `global` memory 只保存用户级偏好、表达习惯、稳定身份信息和跨项目习惯。
- `workspace` memory 保存项目级事实，例如架构决策、路径、技术栈、任务约定。
- 模型上下文只能从 global memory 和当前 `workspace_id` 对应的 workspace
  memory 中选择。选择结果还必须与当前请求相关；workspace memory 不应因为属于
  当前项目就默认进入每次模型调用。
- 只有语言和沟通方式这类窄范围 stable global memory 可以在无关键词命中时少量进入
  上下文；身份、领域偏好、UI 偏好、技术栈、路径和任务细节必须与当前请求直接相关。
- 自动记忆提取应保持窄范围，优先保存高置信用户级事实。
- 项目事实应通过显式 workspace memory 路径保存。

记忆选择结果以 `memory` Context Record 进入 `task_contract` 和 `planning` 阶段，
Context Ledger 保留被选中的 memory ID、范围和来源。基础 system prompt 不再隐式混入
记忆文本。模型仍可判断记忆是否相关；Runtime 只提供带 `memory` trust 标记的存储事实，
不会把记忆当成新的用户指令。

这能减少“另一台电脑、另一个项目、上一轮任务”的隐藏污染。

## Attachment Context

用户上传的图片、PDF、Word、数据文件等附件属于 conversation 内的不可变输入资源。
它们应服务于当前请求，而不是在同一对话的后续所有任务中自动变成当前目标。

建议边界：

- 当前用户消息携带的附件可以作为当前请求附件目录进入模型上下文。
- 历史用户消息携带的附件只能作为 historical attachment candidates 暴露。
- 模型只有在当前请求明确提到“刚才那个文件/继续处理该附件/重新检查上次上传的
  PDF”等上下文时，才应调用 `attachment.extract_text` 读取历史附件。
- 历史附件目录不应作为普通用户意图写入持久压缩摘要；摘要只需保留“曾上传附件”
  这类事实，不应长期保存 attachment_id 和工具调用提示。
- 附件存储路径不是项目路径，不能被当作 workspace 文件产物。

这保留了“继续处理刚才文件”的能力，也避免旧附件在新任务中隐性带偏模型。

## Context Snapshot

上下文压缩不应只是自然语言摘要，而应形成结构化快照：

```json
{
  "schema_version": "context_snapshot.v1",
  "task_id": "task_xxx",
  "phase": "verification",
  "summary": "The file was written; shell verification timed out.",
  "records": [],
  "evidence": [],
  "unresolved": [
    "No browser verification was observed."
  ]
}
```

压缩后必须保留：

- 当前任务目标和硬边界。
- 用户中途追加的纠偏信息。
- 已确认事实。
- 已读取证据。
- 真实产物和路径。
- 工具失败和失败原因。
- 未验证项和剩余风险。
- 可恢复的 checkpoint 或下一步建议。

Context Snapshot 是恢复和回放的事实输入，不是让模型机械重复旧策略的脚本。

## Durable Summary Hygiene

`runtime/context_manager.py` 中的对话压缩摘要是持久化到 conversation metadata 的
长期上下文。它和单次模型调用中的运行时提示不是一回事。

持久摘要只应吸收真实对话事实，例如用户明确表达的长期偏好、仍可能相关的结论、
产物路径和未完成事实。以下内容只能作为单次调用的模型侧脚手架，不能写入长期摘要：

- `Context hygiene` 边界提示。
- `Current request boundary` 边界提示。
- `Context Pack for this model call` 阶段提示。
- 已转入 task lineage 的 historical task markers。
- 工具调用格式示例、旧失败过程日志和临时运行时提示。

这条边界的目的不是删掉历史。UI、RunEvent、诊断包和审计记录仍应保留完整事实；
只是模型下一轮不应因为压缩摘要而反复看到旧任务边界和旧工具失败格式，从而把它们
误当作当前目标或调用模板。

## Context By Model Call Stage

不同阶段需要不同上下文：

```text
task_contract
  当前用户请求、workspace 摘要、相关 task_lineage、能力概览、记忆边界。

planning
  模型声明的任务契约、能力边界、候选步骤、用户硬约束。

execution
  当前步骤、最近工具结果、必要证据片段、失败恢复线索。

verification
  写入记录、产物路径、验证规则、失败和风险。

summary
  RunResult、变更路径、验证事实、剩余风险、未完成项。
```

`runtime/core/context.py` 提供 `select_records_for_phase()` 作为纯函数骨架。它不是
最终检索系统，只是把“按阶段选择上下文”的规则先显式化。

## Current Implementation

当前已有基础：

- `runtime/context_manager.py`
  - 上下文 token 计算、自动/手动压缩入口。
  - 保留最近消息，将旧消息压缩为摘要。
  - 使用 durable summary source 的数量与内容摘要指纹验证缓存前缀，再增量生成摘要。
  - `summary_up_to_index` 只保留为观察字段，不再作为清洗后消息列表的复用游标。
- `runtime/agent_strategy/context_noise.py`
  - 识别历史工具调用文本、失败日志和过程日志。
  - 生成可回填给模型的紧凑历史摘要。
- `runtime/agent_strategy/model_context_boundary.py`
  - 生成模型侧上下文卫生提示、当前请求边界提示和历史任务 marker。
- `runtime/agent_strategy/context_hygiene.py`
  - 在不删除 UI 历史和审计记录的前提下，清洗模型侧上下文。
- `runtime/agent_strategy/task_lineage.py`
  - 从历史消息中抽取相关任务候选。
- `runtime/agent_strategy/project_context.py`
  - 将任务关系与工作对象关系分离，生成可审计的 Active Focus Snapshot。
- `runtime/workspace_snapshot.py`
  - 在不读取文件内容的前提下生成轻量项目事实快照。
- `runtime/context_pack.py`
  - 组合本轮请求、Workspace Snapshot、Task Lineage、Active Focus、Task Contract、
    Capability Snapshot 和 Context Hygiene 报告。
  - 生成 Context Ledger。
- `runtime/tool_event_presentation.py`
  - 对工具结果做模型侧预算压缩，保留路径、错误、完整性和风险。
- `runtime/visual_context.py`
  - 将工具产生且符合边界的视觉证据转换为模型可接收的 image input。
  - 默认随模型配置启用，支持通过 `supports_vision=false` 显式关闭，并保留可审计注入记录。
- `runtime/run_recovery.py`
  - 从 RunResult 生成恢复用 ContextSnapshot。
- `runtime/run_events.py`
  - 持久化运行事件，为 Context Ledger 提供事实来源。
- `runtime/run_result.py`
  - 从工具事件生成确定性结果，可作为 summary 阶段核心上下文。
- `runtime/agent_strategy/run_finalization.py`
  - 将目标产物缺口、验证缺口和最终收束判断显式化。
  - 目标产物缺口只产生继续或换策略建议，不在该层直接停止任务。

## Current Scope

Context Runtime 不以一次性完成 RAG、向量检索或复杂知识库为前提。当前基础边界是：

1. 模型看到的上下文必须可审计。
2. 历史任务可以成为候选事实，但不能成为隐藏当前目标。
3. 记忆必须有 global/workspace 边界。
4. 旧工具调用格式和失败日志不能成为模型模仿样本。
5. Context Pack 和 Context Ledger 必须先稳定，再考虑 Evidence Index。
6. Runtime 提醒模型风险和事实，不替模型选择任务策略。

## Implemented Foundation

Context Runtime 当前已具备以下基础：

- 当前模型上下文经过 `context_hygiene` 清理，旧工具调用格式、失败日志和历史任务噪声不会作为可模仿样本直接进入下一轮模型输入。
- 每个关键阶段可以生成 `Context Pack`，并以 `context.pack` 事件进入 RunEvidence、Runbook、诊断包和任务工作台。
- Context Ledger 记录来源、信任度、新鲜度、任务归属和内容预览，使用户可以审计模型当时看到的是哪些事实。
- Task lineage、previous contract、recovery context、tool result facts 和 final-answer candidate 都通过 Context Pack 暴露为事实，而不是隐藏路线控制。
- Previous contract 与 task_lineage candidate 分开记录：前者只是上一任务契约的历史锚点，后者才是可由模型显式引用的历史任务候选，避免旧任务目标伪装成当前目标。
- 续接契约只有在模型显式选择 continue/revise 后才可补充遗漏字段；历史 goal、路径和能力不能覆盖当前模型已经声明的目标。
- Task Relation 与 Focus Relation 已分离：新任务可以继承同一项目对象，但不能因此继承上一任务的目标和执行路线。
- Active Focus 以 `project_context` 记录进入规划、执行、验证和总结阶段；对象不明确时保持 unresolved，不自动扩大到整个工作区。
- 压缩摘要缓存只有在 durable source 前缀摘要指纹一致时才能复用；Context Hygiene 改变历史 marker 数量后不会继续沿用失配的消息索引。
- 执行式追问的 Task Contract 判断由模型完成；“执行”“按计划执行”等短语不再触发 Runner 直接继承旧契约的旁路。
- 运行中插话会重新触发模型 Task Contract 判断；Runtime 不再用字数、文件类型或关键词正则单独修改当前契约。
- Memory 已区分 global 与 workspace 范围；相关性选择结果通过可审计的 `memory`
  Context Record 进入任务契约和规划阶段，不再作为无来源文本隐式混入基础提示词。
- 无直接相关性的 global memory 仅允许少量语言/沟通偏好进入当前请求，领域、工具和项目偏好不会作为普遍背景注入。
- 视觉证据可以在模型支持时进入 image input，同时保留 `context.visual` / RunEvidence 审计记录。
- Context Snapshot 可由 RunResult / recovery flow 生成，为暂停、恢复和显式 Replay Run 提供恢复依据。
- 需要写入、导出或外部状态变化的任务，如果暂未观察到目标产物，会按工具事实是否变化进行进展判断；事实仍在变化时继续给模型空间，事实停滞时提示模型换路线，而不是按固定次数直接失败。
- 搜索/读取预算只作为进展提醒：当模型长时间侦察但没有目标产物时，Runtime 将事实反馈给模型选择下一步，不再把“达到侦察预算”本身作为失败原因。

Evidence Index、向量检索、复杂知识库、样本库和跨设备上下文同步不属于当前
Context Runtime 基础实现。
