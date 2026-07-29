# Capability Router

YuntaoCode 的任务入口应从“系统关键词分类”逐步转向“模型理解任务，系统验证能力”。

这不是放任模型自由发挥。模型负责理解用户目标和选择候选能力；Runtime 负责能力目录、权限、参数、确认、执行轨迹、产物验证和失败恢复。

## Core Idea

```text
User Request
  -> Model Task Understanding
  -> Task Route Proposal
  -> Capability Contract Validation
  -> Tool Execution
  -> Artifact Verification
  -> Task Trace / Result
```

## Why

关键词分类只能覆盖见过的表达方式。用户说“重新将 PDF 导一个图片加文字的 Word”时，系统不应该靠新增词条才知道这是 PDF 转 Word。

更合理的边界是：

- 模型理解自然语言、上下文和意图。
- 系统提供已注册能力目录。
- 模型只能选择目录中的能力和工具。
- 系统校验工具是否存在、参数是否合法、权限是否允许、是否需要确认。
- 任务成功以真实工具记录和产物验证为准，不以模型自然语言为准。

## Capability Contract

工具不只是函数，还应声明它属于什么能力、会产生什么产物、是否长任务、是否可重试。

当前最小字段：

```json
{
  "id": "document.pdf_to_docx",
  "name": "PDF To Word",
  "description": "Convert a PDF into a Word document.",
  "tool_ids": ["document.extract_pdf_to_docx"],
  "artifacts": ["docx"],
  "requires_confirmation": true,
  "long_running": true,
  "retry_safe": true,
  "idempotent": false
}
```

## Capability Affordance

同一工具可能因参数不同而具有不同的执行形态。Capability Router 会把
`ToolSpec.affordances` 聚合为条件能力事实，并在任务契约判断前提供给模型：

```text
affordance=process.start_background via shell.run_command:
Start a GUI process and return its PID
(when=background=true; effects=external_state_change;
limits=process creation is not behavioral verification)
```

这不是 Runtime 生成的路线提案，也不是“出现某类任务就必须调用某工具”的规则。
模型仍负责理解用户是否要求真实运行、选择哪项能力以及需要哪些验证；Runtime 只负责
确认该 affordance 是否来自当前可用 ToolSpec，并把条件效果、证据边界和执行后的真实
结果记录到 Snapshot、Trace 与 RunResult。

## Task Route Proposal

模型路由层可以输出结构化提案：

```json
{
  "goal": "把 PDF 转成带图片和文字的 Word",
  "capability_id": "document.pdf_to_docx",
  "tool_id": "document.extract_pdf_to_docx",
  "expected_artifacts": ["docx"],
  "requires_write": true,
  "requires_verification": true,
  "confidence": 0.86,
  "rationale": "用户要求 PDF 转 Word 且保留图片和文字顺序"
}
```

Runtime 会验证模型提案并形成事实证据。未知能力、未知工具、工具不属于能力、需要写入但没有确认、需要产物但未生成，都应作为证据缺口或风险进入 Trace、RunEvidence 和完成自审，而不是由运行时静默改写成另一条路线。

## Relation To Existing Policy

现有 `Intent Classifier` 仍可保留，但应降级为执行提示和安全边界事实：

- 明确安全边界时继续由 PathGuard、权限、确认和工具执行 guard 处理。
- 简单寒暄可以直接回复。
- 历史上下文可作为候选事实进入模型判断。
- “只分析”“帮我看下”“继续”等自然语言语义由模型在 Task Contract 中判断，Runtime 不用关键词把它们改写成隐藏路线锁。

它不应承担完整自然语言任务理解。

## Current Implementation Step

当前代码已具备最小闭环：

- `runtime/core/capability.py`
  - CapabilityContract 和 PermissionSet 初始 schema。
- `runtime/agent_strategy/capability_router.py`
  - 能力契约聚合。
  - 条件 Capability Affordance 聚合和模型可见事实。
  - 任务路由提案结构。
  - 提案验证。
  - 能力目录 prompt。
- `runtime/agent_strategy/task_contract.py`
  - 模型可以在 Task Contract 中声明 `capability_ids` 和可选
    `route_proposals`。
- `runtime/conversation_runner.py`
  - 每个 Run 在 Task Contract 与 Capability Preflight 后生成
    `task_route_evidence.v1`，作为 evidence-only 事件和模型上下文事实。
- `runtime/run_evidence.py`
  - RunEvidence 汇总 `task_route_evidence`，用于诊断、Runbook 和后续评测。
- `runtime/completion_evidence_pack.py`
  - Completion self-review 会携带 `task_route_evidence`，让模型基于路线
    有效性、能力缺口、产物和验证事实自行判断继续、修复或总结。
- `runtime/tool_registry.py`
  - `ToolSpec` 支持能力元数据和可选条件 affordance。
- 系统提示中加入 Capability Router 原则和可用能力目录。

后续可以继续强化模型路由预检，但不要急于替换主循环：

1. 在进入主循环前请求模型生成 `TaskRouteProposal`。
2. Runtime 校验提案。
3. 低置信度或提案不合法时，把证据缺口交回模型。
4. 把 `capability_id`、`tool_id`、`expected_artifacts` 写入 Task Trace。
5. 最终结果根据工具事件和产物验证生成，而不是只相信模型总结。
