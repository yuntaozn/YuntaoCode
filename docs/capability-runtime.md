# Capability Runtime

YuntaoCode 的工具不应只是“模型能调用的一组函数”。对于开源基座，工具需要被提升为能力契约：声明它能做什么、需要什么权限、会产生什么产物、是否长任务、是否可重试、如何验证。

Capability Runtime 管理这些能力契约，并把内置工具、CLI、MCP、外部插件、
Capability Pack 和 AI-built draft 都放进同一条受控路径。

## Core Idea

```text
Registered Tool / Capability Provider
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
- AI-built Capability Pack 或工具适配器草稿不能因为用户确认一次就进入主进程执行。
- 能力启用不等于所有工具调用免确认。

## Capability, Tool, Provider

三者边界：

```text
Capability
  任务层可理解的能力，例如 document.pdf_to_docx。

Tool
  实际执行单元，例如 document.extract_pdf_to_docx。

Provider
  能力来源或实现方式，可以暴露一个或多个 capability/tool。
  例如 builtin、cli、mcp、capability_pack、external_plugin、ai_draft。
```

也就是说，MCP、CLI、插件和自建能力包都不是任务层边界，能力才是任务运行时
的边界。模型应优先理解 `document.pdf_to_docx`、`code.text_write`、
`mcp.blender` 这类 capability；至于它由 Python 内置工具、受控 CLI、MCP
服务还是外部插件实现，属于 provider 层事实。

Provider 层需要被记录和审计，但不应让任务逻辑分裂成多套流程：

```text
Capability Runtime
  capability_id: document.pdf_to_docx
  tools:
    - document.extract_pdf_to_docx
    - pdf_cli.convert
  providers:
    - builtin
    - cli
```

同一个 capability 未来可以有多个 provider 实现。Runtime 可以根据可用性、权限、
平台、依赖、执行证据和模型判断来选择工具，但安全确认、PathGuard、Trace、
RunResult 和验证证据仍走同一条路径。

Provider kind 当前保持小集合：

```text
builtin
  运行在主 Runtime 内的内置 Python 能力。

cli
  受控本地命令提供的能力。CLI 不等于任意 shell；它应有声明式 command/args、
  输入输出、权限、超时和验证证据。

mcp
  具有独立服务生命周期和协议连接状态的外部能力提供者。MCP 工具进入
  ToolRegistry 后仍是普通 capability tool。

capability_pack
  用户数据目录中的方法型 Skill、任务模板或上下文包。默认不执行代码。

external_plugin
  未来受控插件 provider。

ai_draft
  AI 生成的能力草稿或适配器描述，默认不进入可信运行时。
```

## Relation To Tool Protocol

Capability Runtime describes what a tool can do, what it may affect, and how it
is governed. The lower-level transport and call-shape rules live in
[tool-protocol.md](tool-protocol.md):

- malformed textual tool markers are not successful tool calls;
- required input fields are validated before confirmation;
- truncated model output must not execute state-changing tools;
- temporary scripts and probe outputs should use the task temp directory;
- code writes should prefer structured patch/edit tools over large full-file
  retransmission.

Tool-result risks are separate advisory evidence. They are derived from
observable tool output, carried through tool events, and surfaced in RunResult
without forcing a fixed model strategy. See
[tool-result-risks.md](tool-result-risks.md).

## Built-in Capability Standard

默认内置能力要少而稳。一个能力适合进入 `runtime/skills/`，通常需要同时满足：

1. 足够通用，不绑定单一业务场景或行业流程。
2. 对 Task Runtime 完成真实本地任务有基础价值。
3. 能被 `PathGuard`、权限、确认和审计机制约束。
4. 有明确 `ToolSpec`：input schema、effects、artifacts、roles、long-running、retry-safe 等。
5. 失败能结构化返回，不应拖垮 Runtime 启动或执行循环。
6. 跨平台路径清晰，不能默认依赖某个系统的 shell 习惯。
7. 产物或状态变化能进入 RunResult、Runbook、Replay/Evaluation 证据链。
8. 依赖缺失时可降级，而不是让整个 Runtime 不可用。

当前内置能力按来源分为：

```text
Runtime 能力
  attachment, memory
  属于 Context/Runtime 输入与记忆边界，只读展示，不从插件页直接启停。

内置基础能力
  filesystem, code, shell, git
  支撑本地任务执行，可以启停，但仍受权限、确认和审计约束。

内置可选能力
  document, web, preview
  通用但偏重或带外部访问边界，可以启停，也应清楚展示依赖和风险。

外部能力提供者
  CLI providers, MCP services, future external plugins, Capability Packs, AI-built tool adapter drafts
  不应直接混入 `runtime/skills/`，需要独立生命周期和受控边界。
```

不适合默认内置的能力包括视频生成、Blender/CAD 建模、RAG/向量库、重度浏览器自动化、特定办公流程、特定行业工具，以及纯提示词方法论 Skill Pack。这些应优先走 CLI provider、MCP、外部插件、AI 草稿或 Skill Evolution，而不是扩大主 Runtime。

`preview.visual_debug` 是内置可选能力中的证据能力。它使用浏览器预览本地 HTML
或 URL，并把截图、console error、page error 和 failed request 作为 verification
evidence 写入任务临时目录。它不代表 Runtime 要替模型判断 UI 是否完成，也不应把
网页调试硬编码成任务流程；Runtime 只把可观察证据交给模型和 RunResult。
本地 HTML 默认通过短生命周期的 `127.0.0.1` 静态服务打开，避免 `file://`
导致 module script、import map、相对资源和 Three.js 页面被浏览器策略误拦。
`preview.interact_page` 在同一能力下提供有界交互验证：模型可以自行声明点击、输入、
等待、读取文本和文本断言动作，工具返回 `interaction_trace`、`dom_text`、截图和
调试证据。成功的交互断言可作为 behavioral/content evidence；失败的断言只作为
风险和下一步修正依据，不应被 Runtime 静默替换成固定流程。

视觉类工具应返回或可归一化为 `visual_evidence.v1`。该契约至少包含来源
（URL、本地文件、MCP 或外部提供者）、截图/渲染产物路径、尺寸、格式、捕获时间、
页面状态、console/page/network 错误，以及该产物是否可作为模型上下文的 image
input。`preview.*`、`web.*` 和 MCP 截图结果都应尽量进入这个证据结构；旧的
`path`、`artifact_kind`、`has_runtime_errors` 等顶层字段可继续保留作为兼容出口。
RunResult 只把它作为“观察证据”汇总，不把它变成隐藏任务路线或硬性拦截。

运行/调试类工具应返回或可归一化为 `debug_session.v1`。该契约记录命令、工作目录、
进程号、退出码、超时、stdout/stderr 摘要、诊断、服务 URL/端口和心跳等事实。
`shell.run_command` 和 `preview.*` 首先接入该结构；未来 CLI provider、dev server、
浏览器调试、长任务和外部应用连接也应优先复用它。它的作用是帮助模型、用户和
RunResult 理解“实际运行过什么、运行到哪里、失败在哪里”，而不是让 Runtime 替模型
决定下一步策略。

## Cross-platform Baseline

YuntaoCode 宣称支持 Windows、macOS 和 Linux 时，默认含义不是所有外部工具在三端都天然存在，而是 Runtime 核心和基础能力在三端都有清晰边界：

1. Runtime 核心必须跨平台：设置目录、工作区路径、PathGuard、任务状态、Run/RunEvent、附件、记忆、工具注册、HTTP API 和前端不能依赖单一操作系统。
2. 内置基础能力必须优先使用跨平台入口：文件读写使用 Python/Pathlib；代码写入使用统一文件能力；Shell 优先使用 `command + args`，不要把 PowerShell、bash、cp、rm、Copy-Item 等语法当作通用协议。
3. 可选能力可以有平台适配器：打开文件夹、Word/LibreOffice 转换、浏览器、Git、MCP 服务和桌面壳可以按系统走不同实现，但缺依赖时必须结构化失败并给出可理解诊断。
4. 文档转换和 GUI 能力不能成为 Runtime 启动前提：缺少 Office、LibreOffice、xdg-open、open、Explorer、浏览器或 MCP 二进制时，只应影响对应 capability。
5. 新增 `runtime/skills/` 能力时，需要回答：Windows/macOS/Linux 是否都可运行？如果不能，是否有明确降级、错误提示、测试或文档说明？

因此，跨平台支持的基线是“核心一致、能力可诊断、外部依赖可降级”，而不是把某个开发机上的工具链硬编码进主 Runtime。

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
- 受控 CLI 属于 `cli` provider，而不是裸 shell 能力。
- AI-built Capability Pack 属于未加载 pack asset；其中的 tool adapter 草稿仍是未加载 draft provider。
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
  - AI-built Capability Pack 与工具适配器草稿边界治理。
- `runtime/api/plugins.py`
  - 当前插件/能力分组展示。
- `runtime/core/capability.py`
  - CapabilityContract、CapabilityProvider、PermissionSet，以及 artifact、effect、task role 初始 schema。

Additional runtime guards now exist in `runtime/agent_strategy/capability_preflight.py`:

- `capability_snapshot` captures the per-run available capability boundary.
- `capability_snapshot` records `provider_kind`, `provider_id`, and provider
  summaries so diagnostics can distinguish "the capability is unavailable"
  from "a specific MCP/CLI provider is unhealthy".
- Model-declared `task_contract.capability_ids` are validated against that
  snapshot.
- External-state tasks require an available capability with
  `external_state_change`.
- Fallback from a target external-state capability to shell scripts or ordinary
  file generation is surfaced as capability-boundary evidence. The Runtime may
  require normal safety confirmation, but the model remains responsible for
  choosing whether to retry, ask the user, explain the boundary, or select
  another safe strategy.
- Preflight blockers are recorded in `RunResult` as deterministic failure
  evidence.

`runtime/capability_evidence.py` builds `capability_evidence_summary.v1` from
persisted tool events. It preserves declared ToolSpec metadata
(`declared_capability`, effects, roles, and verification strength) alongside
observed tool-output facts such as artifacts, effects, roles, paths, and
verification strength. RunResult, Runbook, diagnostics, and future replay /
evaluation code can use this summary as audit evidence. It is not an execution
policy and must not block or force a strategy by itself.

Current built-in local file capability split:

- The 0.1 foundation treats YuntaoCode's own local file capability as the
  primary file channel. Editor-specific bridges are deferred until there is a
  separate product decision and a clear provider lifecycle.
- `filesystem.local_files`: read and scan files inside the workspace boundary.
- `filesystem.change_set`: apply a bounded local file transaction for create,
  overwrite, literal replace, and delete operations, with PathGuard,
  confirmation, backup, trace, and RunResult evidence.
- `code.text_write`: create or modify text/code files through structured write
  tools.
- `filesystem.local_state`: change local file state, such as
  `filesystem.delete_file`, with PathGuard, confirmation, backup, trace, and
  RunResult evidence.

## Next Steps

短期建议：

1. 将 ToolSpec 的 artifact、effect、role 和权限元数据逐步映射为 CapabilityContract。
2. 在 task_contract 之后增加可选 RouteProposal 验证事件。
3. 继续把 artifact、capability_id 和验证规则沉淀为可测试的 evidence schema。
4. 将 CLI provider 设计为声明式能力来源，而不是开放任意 shell。
5. 前端插件页区分 built-in capability、CLI provider、MCP provider、AI draft、future external provider。

中期建议：

1. 为外部插件建立子进程或独立环境边界。
2. 将 MCP server 暴露的工具包装成 CapabilityContract。
3. 为 capability 增加验证规则，例如 artifact_exists、coverage_check、syntax_check。
4. 引入受控 promote flow，而不是让 AI draft 修改主 runtime。
