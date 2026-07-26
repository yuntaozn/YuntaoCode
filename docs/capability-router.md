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

Runtime 只接受通过能力目录验证的提案。未知能力、未知工具、工具不属于能力、需要写入但没有确认、需要产物但未生成，都不能被视为完成。

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
- `runtime/tool_registry.py`
  - `ToolSpec` 支持能力元数据。
- 系统提示中加入 Capability Router 原则和可用能力目录。

下一步可以继续做独立模型路由预检，但不要急于替换主循环：

1. 在进入主循环前请求模型生成 `TaskRouteProposal`。
2. Runtime 校验提案。
3. 低置信度或提案不合法时，把修正提示交回模型。
4. 通过提案后，把 `capability_id`、`tool_id`、`expected_artifacts` 写入 Task Trace。
5. 最终结果根据工具事件和产物验证生成，而不是只相信模型总结。
