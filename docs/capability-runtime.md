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

同一个 capability 可以有多个 provider 实现。Runtime 可以根据可用性、权限、
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
  外部插件声明。0.1 不把外部插件代码自动注册为可信运行时 provider。

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
  document, web, preview, desktop
  通用但偏重或带外部访问边界，可以启停，也应清楚展示依赖和风险。

外部能力提供者
  CLI providers, MCP services, external plugin declarations, Capability Packs, AI-built tool adapter drafts
  不应直接混入 `runtime/skills/`，需要独立生命周期和受控边界。
```

不适合默认内置的能力包括视频生成、Blender/CAD 建模、RAG/向量库、重度浏览器自动化、特定办公流程、特定行业工具，以及纯提示词方法论 Skill Pack。这些应优先作为 CLI provider、MCP、外部插件声明或 AI 草稿处理，而不是扩大主 Runtime。

`desktop.observation` 是正在孵化的本机桌面观察 provider。代码主体放在
`providers/desktop_observation/`，Runtime 只通过 `runtime.skills.desktop`
做薄适配。它的边界是只读观察：窗口列表、活动窗口、进程列表、全屏截图和指定窗口
截图；不提供点击、输入、快捷键、聚焦、关闭窗口或进程控制。窗口和进程事实进入
`desktop_state.v1`，截图进入 `visual_evidence.v1`。截图可能包含隐私内容，因此
截图类工具需要确认；窗口/进程列表仍只作为 evidence/verification facts，不替模型
选择任务路线。详见 [desktop-observation-provider.md](desktop-observation-provider.md)。

`preview.visual_debug` 是内置可选能力中的证据能力。它使用浏览器预览本地 HTML
或 URL，并把截图、console error、page error 和 failed request 作为 verification
evidence 写入任务临时目录。它不代表 Runtime 要替模型判断 UI 是否完成，也不应把
网页调试硬编码成任务流程；Runtime 只把可观察证据交给模型和 RunResult。
截图、渲染图等产物可贡献 visual evidence；HTTP 状态、资源响应、DOM 快照、
预览服务和 debug session 等运行事实可贡献 structural evidence。二者都只是
RunResult 中的证据模态，不会替模型决定是否还需要交互、内容或人工观察。
本地 HTML 默认通过短生命周期的 `127.0.0.1` 静态服务打开，避免 `file://`
导致 module script、import map、相对资源和 Three.js 页面被浏览器策略误拦。
`preview.interact_page` 在同一能力下提供有界交互验证：模型可以自行声明点击、输入、
等待、读取文本和文本断言动作，工具返回 `interaction_trace`、`dom_text`、截图和
调试证据。成功的交互断言可作为 behavioral/content evidence；失败的断言只作为
风险和下一步修正依据，不应被 Runtime 静默替换成固定流程。

`preview.capture_file` 是同一能力下的通用文件观察入口。它不替模型判断任务类型，
只根据文件本身返回可观察证据：HTML 复用浏览器预览，图片登记为 visual evidence，
PDF 在 PyMuPDF 可用时渲染指定页截图；不支持的格式或缺失依赖返回结构化
runtime diagnostics。Word/PPT 等重依赖文件预览应继续走可选 provider 或文档能力，
而不是让主 Runtime 假设本机一定具备 Office/LibreOffice。

视觉类工具应返回或可归一化为 `visual_evidence.v1`。该契约至少包含来源
（URL、本地文件、MCP 或外部提供者）、截图/渲染产物路径、尺寸、格式、捕获时间、
页面状态、console/page/network 错误，以及该产物是否可作为模型上下文的 image
input。`preview.*`、`web.*` 和 MCP 截图结果都应尽量进入这个证据结构；旧的
`path`、`artifact_kind`、`has_runtime_errors` 等顶层字段可继续保留作为兼容出口。
RunResult 只把它作为“观察证据”汇总，不把它变成隐藏任务路线或硬性拦截。

`visual_evidence.model_context.eligible` 只是工具声明“这张图适合给模型看”，不是
Runtime 必须注入图片的命令。真正进入模型上下文前还需要满足三层边界：

1. 当前模型配置未显式关闭图片输入；如果接口或模型实际拒绝图片请求，模型流传输层
   应保留文字化视觉事实并重试一次。
2. 视觉产物路径位于当前 workspace 或 Runtime 数据目录之内。
3. 文件类型和大小处于模型上下文桥接允许的范围。

如果模型不支持多模态、传输拒绝图片，或产物不满足边界，Runtime 仍应保留截图
路径、尺寸、错误和 DOM/OCR 等文本证据，让模型基于可审计事实继续判断。也就是说，视觉证据桥接是
Evidence Context 的增强，不是任务路由、验证替代品或系统级自动判定。

运行/调试类工具应返回或可归一化为 `debug_session.v1`。该契约记录命令、工作目录、
进程号、退出码、超时、stdout/stderr 摘要、诊断、服务 URL/端口和心跳等事实。
`shell.run_command` 和 `preview.*` 已接入该结构。它的作用是帮助模型、用户和
RunResult 理解“实际运行过什么、运行到哪里、失败在哪里”，而不是让 Runtime 替模型
决定下一步策略。

`debug_audit.v1` 从 `debug_session.v1` 汇总运行调试证据，标记依赖安装、预览服务、
端口/进程检查、服务会话、长时间运行、超时、stderr 和诊断等事实。它只进入
RunResult、RunEvidence 和 RunWorkbench 作为审计视图，不参与任务路由、工具选择、
完成判断或失败收束。模型需要根据这些事实自行决定是否继续验证、换工具、调整命令或
向用户说明风险。

子进程可观察性属于 ToolTask 执行契约，而不是某个安装器的特例：

- stdout/stderr 在进程运行中增量写入 ToolTask 日志，并通过现有 `tool_log` 事件显示；
- 输出需要节流和有界保留，避免高频日志拖垮本地任务存储；
- 长时间无输出时发送带已运行时间和静默时间的心跳，但不据此判断任务策略；
- 普通命令保持较短默认超时，已识别的依赖安装使用较长默认超时，显式 timeout 仍由调用者决定；
- 停止 Run 时取消应传播到 ToolTask，并请求终止其子进程树；
- 命令角色只用于超时、确认文案和审计展示，不应成为隐藏任务路由器。

`tool_task_progress.v1` 是 ToolTask 日志的只读摘要。它把任务状态、已运行时间、最近进展、
命令角色、最近 stdout/stderr 输出、心跳、取消记录和日志计数整理给 API、流式事件和
前端工具卡片使用。它不替模型判断任务是否该继续，也不把依赖安装、预览服务或端口检查
变成固定流程；模型仍根据可见事实自主决定下一步。

工具成功也必须代表真实的可观察变化。文件编辑中 `old_text` 与 `new_text` 最终解析为
相同内容、行范围替换没有改变文件等 no-op 情况，应返回可纠正的工具失败，不能生成
虚假 diff、备份或写入证据。这样模型可以修正参数，进展判断也不会因为一次空操作被
错误重置。

验证证据具有时间关系：发生在最新写入或外部状态变化之前的截图、测试或查询，只能
作为历史验证尝试和错误诊断，不能证明当前状态。Runtime 应把“证据已过期”和原验证
错误一起反馈给模型，由模型决定重新验证、继续修复、换路线或如实收束。

## Cross-platform Baseline

YuntaoCode 宣称支持 Windows、macOS 和 Linux 时，默认含义不是所有外部工具在三端都天然存在，而是 Runtime 核心和基础能力在三端都有清晰边界：

1. Runtime 核心必须跨平台：设置目录、工作区路径、PathGuard、任务状态、Run/RunEvent、附件、记忆、工具注册、HTTP API 和前端不能依赖单一操作系统。
2. 内置基础能力应提供跨平台入口：文件读写使用 Python/Pathlib；代码写入走统一文件能力；Shell 建议使用 `command + args`，不要把 PowerShell、bash、cp、rm、Copy-Item 等语法当作通用协议。
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
  -> Model-selected Capability / Deliverable
  -> Capability Snapshot And Advisory Preflight
  -> Tool Execution
  -> RunResult
```

Runtime 不根据用户文本自动选择 Provider，也不把文件产物改写成外部状态或反向改写。
模型可以引用 Capability Snapshot 中的能力；Preflight 只说明可用性、健康状态和证据边界。
这可以避免继续用关键词补丁处理“生成视频”“PDF 转 Word”“创建 HTML 示例页”等表达差异。

## Relation To Plugins

当前 `docs/plugin-system.md` 仍是外部插件设计草案。Capability Runtime 是它的上层原则：

- 内置工具属于内置 capability provider。
- 受控 CLI 属于 `cli` provider，而不是裸 shell 能力。
- AI-built Capability Pack 属于未加载 pack asset；其中的 tool adapter 草稿仍是未加载 draft provider。
- 外部插件是可分发包；0.1 只建立声明和安装状态边界，不自动加载其中的可执行组件。
  Skill、Capability Pack 等非执行组件仍走各自的选择与上下文路径。
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
- Current `task_contract.capability_ids` are validated against that
  snapshot.
- External-state contracts are checked against capabilities that advertise
  `external_state_change`; missing or unhealthy providers become advisory
  readiness facts rather than a hidden route decision.
- Fallback from a target external-state capability to shell scripts or ordinary
  file generation is surfaced as capability-boundary evidence. The Runtime may
  require normal safety confirmation, but the model remains responsible for
  choosing whether to retry, ask the user, explain the boundary, or select
  another safe strategy.
- Capability preflight facts are advisory unless they represent a hard safety
  boundary. Non-blocking advisories are carried as `runtime_risks` so the model,
  RunResult, diagnostics, and evaluation records can audit them without
  turning capability fit into a hidden route lock.
- New runs emit `capability_preflight.v2`. The contract contains
  `advisories`, `readiness_issues`, `visual_verification_tool_ids`, and a
  `route_hint` whose policy is advisory. `preferred_tool_ids` is retained only
  as a null compatibility field for older diagnostic readers; new runs do not
  rank tools for the model.
  It intentionally avoids legacy route-control fields such as hard fallback
  restrictions or enforcement flags. Readers may still normalize older
  diagnostic records, but new runtime behavior must not reintroduce those
  fields as hidden policy controls.

`runtime/capability_evidence.py` builds `capability_evidence_summary.v1` from
persisted tool events. It preserves declared ToolSpec metadata
(`declared_capability`, effects, roles, and verification strength) alongside
observed tool-output facts such as artifacts, effects, roles, paths, and
verification strength. RunResult, Runbook, diagnostics, and evaluation code can
use this summary as audit evidence. It is not an execution
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

## Current Provider Boundary

Capability Runtime 的 Provider 遵循同一套原则：

- Built-in tools, CLI providers, and MCP providers are capability providers.
  Capability Packs, plugin declarations, and non-executable
  plugin components are capability assets. None of them owns task state,
  planning, completion, replay, or audit.
- Provider metadata must normalize into ToolSpec / Capability facts:
  artifacts, effects, roles, permissions, verification strength, provider kind,
  provider id, availability, health, and last error.
- Tool availability is layered runtime evidence, not a package-import shortcut:
  dependency installed -> provider/runtime dependency ready -> tool available
  or degraded -> capability snapshot. `ToolSpec.readiness_probe` reports
  `available`, `health`, `code`, `message`, and bounded details without
  executing the task or choosing its strategy. Browser-backed tools use this
  to distinguish the Playwright Python package from its managed Chromium
  binary; CLI and MCP lifecycle facts combine with the same boundary.
- `capability_preflight.v2` is advisory. It provides readiness issues,
  preferred tools, visual verification tools, and route hints, but it does not
  hide tools, stop runs, or force fallback rules.
- Tool execution guards remain the hard boundary for PathGuard, permissions,
  confirmation, disabled providers, unavailable services, malformed arguments,
  and unsafe state changes.
- Multi-artifact verification is owned per target artifact. The latest
  successful write for each path may contribute structural evidence; writing a
  later file must not erase evidence for earlier files. Task-level verification
  aggregates those facts with later tests, visual captures, and behavioral
  checks.
- MCP lifecycle state is a provider health fact: stopped, process running,
  protocol disconnected, connected, discovered, degraded, or unavailable. It
  must flow into capability evidence instead of creating Blender-specific or
  MCP-specific runner branches.
- CLI providers must be declarative command providers with permissions,
  timeout, output schema, and evidence. They must not become a free-form shell
  escape hatch.
- AI-built Capability Packs are user-data-level drafts by default. They can
  provide method skills, task templates, context packs, or tool-adapter drafts,
  but generated executable code is not trusted runtime code.
