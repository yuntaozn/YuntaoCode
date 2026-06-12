# Capability Runtime

YuntaoCode 的工具不应只是“模型能调用的一组函数”。对于开源基座，工具需要被提升为能力契约：声明它能做什么、需要什么权限、会产生什么产物、是否长任务、是否可重试、如何验证。

Capability Runtime 管理这些能力契约，并把工具、插件、MCP、AI-built draft 都放进同一条受控路径。

## Core Idea

```text
Registered Tool / Plugin / MCP Server
  -> Capability Contract
  -> Permission Check
  -> Confirmation Gate
  -> ToolTask Execution
  -> Artifact / Verification
  -> Task Trace / RunResult
```

模型可以提出使用某个能力，但 Runtime 必须校验：

- capability 是否存在。
- tool_id 是否属于该 capability。
- 参数是否符合 schema。
- 权限是否允许。
- 是否需要用户确认。
- 是否产生了预期 artifact。
- 是否声明了实际 effect，以及它在当前任务中承担的 role。
- 验证是否通过。

## Contract Shape

初始纯 schema 已在 `runtime/core/capability.py` 中定义：

```json
{
  "schema_version": "capability_contract.v1",
  "capability_id": "document.pdf_to_docx",
  "tool_id": "document.extract_pdf_to_docx",
  "name": "PDF To Word",
  "description": "Convert a PDF into a Word document.",
  "input_schema": {},
  "output_artifacts": ["docx"],
  "effect_types": ["file_write"],
  "task_roles": ["deliverable"],
  "permissions": {
    "filesystem": "workspace",
    "shell": "false",
    "network": "false",
    "model": "false"
  },
  "long_running": true,
  "retry_safe": true,
  "requires_confirmation": true,
  "local_only": true
}
```

## Permission Model

权限先保持小而清晰：

```text
filesystem
  none | workspace | full_local

shell / network / model
  false | confirm_each | allow
```

## Confirmation Policy

Execution confirmation is separate from planning. The runtime validates a tool
call in this order:

```text
resolve tool id
  -> validate required input
  -> check plugin and hard guards
  -> classify risk
  -> apply confirmation policy
  -> execute ToolTask
```

Invalid calls, including calls missing required fields, fail before manual
confirmation. This prevents users from approving an operation that cannot be
executed.

| Policy | Workspace write | Shell / Git commit | Hard guards |
| --- | --- | --- | --- |
| conservative | confirm | confirm | always enforced |
| auto | allow | confirm | always enforced |
| aggressive | allow | allow inside authorized boundaries | always enforced |

原则：

- 写入文件、Shell、Git 写操作、导出、外部状态修改默认需要确认。
- `full_local` 永远是高风险权限。
- AI-built plugin draft 不能因为用户确认一次就进入主进程执行。
- 能力启用不等于所有工具调用免确认。

## Capability, Tool, Plugin

三者边界：

```text
Capability
  任务层可理解的能力，例如 document.pdf_to_docx。

Tool
  实际执行单元，例如 document.extract_pdf_to_docx。

Plugin
  能力提供者，可以暴露一个或多个 capability/tool。
```

也就是说，插件不是产品边界，能力才是任务运行时的边界。未来 MCP 工具、外部插件、本地内置工具都应映射成 Capability Contract 后再被模型使用。

## Relation To Task Contract

Task Contract 描述“本轮用户目标需要什么”。

Capability Contract 描述“系统有什么能力可以满足目标”。

建议路径：

```text
User Request
  -> Model Task Contract
  -> Route Proposal
  -> Capability Contract Validation
  -> Tool Execution
  -> RunResult
```

这可以避免继续用关键词补丁处理“生成视频”“PDF 转 Word”“创建 HTML 示例页”等表达差异。

## Relation To Plugins

当前 `docs/plugin-system.md` 仍是外部插件设计草案。Capability Runtime 是它的上层原则：

- 内置工具属于内置 capability provider。
- AI-built plugin draft 属于未加载 draft provider。
- 外部插件未来属于本地或受控 provider。
- MCP 工具属于外部 capability provider。

所有 provider 都需要走同样的能力声明、权限、确认、Trace、RunResult。

## Current Implementation

当前已有基础：

- `runtime/tool_registry.py`
  - ToolSpec 注册和工具元数据。
- `runtime/agent_strategy/capability_router.py`
  - 能力目录、路由提案和验证草案。
- `runtime/capability_governance.py`
  - AI-built plugin draft 边界治理。
- `runtime/api/plugins.py`
  - 当前插件/能力分组展示。
- `runtime/core/capability.py`
  - CapabilityContract、PermissionSet，以及 artifact、effect、task role 初始 schema。

## Next Steps

短期建议：

1. 将 ToolSpec 的 artifact、effect、role 和权限元数据逐步映射为 CapabilityContract。
2. 在 task_contract 之后增加可选 RouteProposal 验证事件。
3. 在 RunResult 中记录 artifact 与 capability_id。
4. 前端插件页区分 built-in capability、AI draft、future external provider。

中期建议：

1. 为外部插件建立子进程或独立环境边界。
2. 将 MCP server 暴露的工具包装成 CapabilityContract。
3. 为 capability 增加验证规则，例如 artifact_exists、coverage_check、syntax_check。
4. 引入受控 promote flow，而不是让 AI draft 修改主 runtime。
