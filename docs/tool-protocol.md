# 本地工具协议

工具协议服务于 Task Runtime。工具定义系统“能做什么”，但任务模型定义系统“为什么做、做到哪一步、如何恢复和审计”。任务模型草案见 [task-model.md](task-model.md)。

## 按需加载工具定义

每个 Run 的首轮只携带 `runtime.discover_tools` 定义，普通回答可以直接结束。
模型需要能力时，通过原生工具调用发现并加载定义：

- `{}`：分页列出当前可用工具命名空间及数量，不加载定义。
- `{"query":"blender"}`：在工具 ID 与描述中按子串匹配；空格分隔的词取并集。
  按完整 ID、工具名词项匹配及目录内词频排序，描述匹配补充召回，同分按 ID 稳定
  排序分页。匹配页中的原始定义从下一轮开始可用。
- `{"tool_ids":["filesystem.read_file","filesystem.write_file"]}`：加载指定定义。
- 查询默认每页 5 项，`limit` 最多 10，`offset` 与返回的 `next_offset` 用于分页。

发现只读取已启用且当前可用的目录，不读取用户消息、不额外调用模型判断任务，
也不执行能力。每次发现都刷新目录，能看到本轮新连接的 MCP；已加载定义在本 Run
内保留，刷新时移除已不可用项。新 Run 从单个发现入口重新开始。
模型加载后仍直接调用工具原有名称和参数。加载状态不是权限许可，也不强制模型
对已知工具先发现；实际调用继续经过注册、参数校验、PathGuard 和操作确认。
`runtime.update_task` 同样按需加载，属于可选审计声明。

`tool_discovery` / `tool.definitions` 事件记录发现结果，工具定义加载不生成
ToolTask，也不作为任务完成证据。能力使用通常增加一次发现往返；不需要工具的
回答不增加模型调用。

## 工具元数据

```json
{
  "id": "document.extract_docx_outline",
  "name": "提取 Word 大纲",
  "description": "读取 .docx 文档标题层级和段落数量。",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": { "type": "string" }
    },
    "required": ["path"]
  },
  "requires_confirmation": false,
  "local_only": true
}
```

当同一工具在特定参数下会产生不同效果时，可在 `ToolSpec.affordances` 中声明条件能力，
包括 `input_hints`、`artifacts`、`effects`、`roles` 和 `evidence_limits`。它们是提供给
模型判断的可用性事实，不是参数默认值、自动路由或成功证明；实际状态改变和验证强度
仍以执行后的 ToolResult 为准。

## 提交任务

```http
POST /tool-tasks
Content-Type: application/json

{
  "tool": "filesystem.scan_folder",
  "input": {
    "path": ".",
    "max_depth": 2
  },
  "wait": true
}
```

## 任务状态

```text
queued -> running -> success
queued -> running -> failure
```

## 任务流程里的意义

任务流程不只编排提示词，也编排工具：

```text
扫描资料目录
-> 提取 Word/PDF 文本
-> 后台模型识别工程信息
-> 本地生成审查报告
-> 人工确认
```

## 临时产物

临时脚本、中间 JSON、探测输出等一次性文件应写入任务临时目录，而不是写入用户项目目录。

一种可用的工具流程：

```text
filesystem.write_temp_file
-> shell.run_command(cwd="task_temp")
-> 根据结果决定是否写入真实项目文件
```

`filesystem.write_temp_file` 产物属于 ToolTask 的临时产物，不应视为真实项目变更，也不能满足“已完成代码修改/已生成项目文件”的成功条件。

跨平台命令建议使用 `command` + `args` 参数数组，即使程序没有参数也显式传
`args=[]`。这种形式使用 `direct_exec`，不会经过平台 shell。省略 `args` 时，Windows
使用 Windows PowerShell 5.1，其他平台使用 POSIX shell；工具结果会返回
`shell_dialect`。只有任务明确依赖某个平台时，才使用 PowerShell、bash、cp、rm、
Copy-Item 等平台专属语法。GUI 或长驻程序可传 `background=true` 直接启动，工具会
立即返回 PID 和 `process_state=running`，而不是把程序等待退出当成普通命令验证。

## 模型工具调用边界

工具定义仅在模型显式调用 `runtime.discover_tools` 时查询和加载。检索只消费
`query` 或精确 `tool_ids`，不扫描用户任务。中文连续文本使用相邻字对匹配描述，
按词面命中及目录内出现频次排序，避免“文件读取”因描述写成“读取文件”而消失。
这不包含意图分类、同义词扩写、能力关键词映射或自动执行；零命中仍如实返回。

模型必须通过接口提供的结构化工具调用协议调用工具，并提供工具输入 schema
要求的参数。普通回复文本中的 `<toolcall>`、`<mcreference>`、FunctionCall
标记或无参数工具名，不属于成功工具调用。

运行时可以兼容解析少量模型供应商输出的文本工具调用格式。工具参数必须是完整的
JSON 对象；无法解析、不是对象或缺少必要参数时，运行时记录协议失败并且不执行，
也不猜测、补全或修复参数。失败结果会回到模型上下文，由模型自行决定下一步策略。
普通答案中的 JSON、调用示例或不完整文本标记保留为正文，不触发隐式完成声明、
自动改写或补发指令。只有已配置且完整匹配的调用协议才能进入执行。
原生批次协议无效时整批不执行，返回 `model_protocol_error`、实际错误码和
`executed_tool_calls=0`，由主模型在统一资源预算内选择后续响应。
未执行尝试不再包含 `model_decision` 或替代工具目录；工具由模型显式查询。
错误反馈不指定重试次数、替代路线或参数拆分方法。

这些未执行尝试应进入 `tool_attempt_observation.v1`；一个 Run 中的同类观察会进一步
汇总为 `tool_attempt_recovery.v1`。这份汇总只描述事实，例如缺失字段、协议边界、
是否可由模型修正、是否涉及硬安全边界或大写入式载荷；它不替模型选择重试路线。

模型 Provider 的流事件应保留 `finish_reason`。当一轮因 `length`、
`max_tokens` 或 `max_output_tokens` 停止时，本轮工具调用视为可能截断，不得执行。
这条规则尤其保护 `filesystem.write_file`、Shell、Git 等会改变本地状态的工具。

代码展示格式化与工具调用传输是两层问题：Markdown、高亮和格式化器只负责展示或
写后质量检查，不能修复被模型输出上限截断的工具参数。小范围修改可使用结构化
编辑工具；完整文件写入必须以一次完整、可解析的工具调用到达运行时。

## 代码写入协议

对于已有代码的小块增量修改，`code.apply_patch` 是一个结构化入口。它参考 Codex 风格的小块补丁协议：

```text
*** Begin Patch
*** Update File: src/app.js
@@
-const enabled = false;
+const enabled = true;
*** End Patch
```

Runtime 会先完整解析并验证补丁涉及的全部文件，再执行写入。补丁缺少结束标记、
上下文无法唯一匹配、目标越过工作区边界或任一文件校验失败时，本轮不会写入任何
文件。补丁仍经过确认策略和备份流程。

写入能力的适用边界：

- `code.apply_patch`：适合已有代码的小块增量修改，也支持创建小文件。
- `code.edit_file`：适合明确知道唯一 `old_text` / `new_text` 的精确替换。
- `code.replace_text`：适合跨文件的同一文本批量替换。
- `filesystem.apply_changes`：适合一组有界的本地文件变更事务，包括创建、
  覆盖、字面替换和删除。
- `filesystem.write_file`：适合完整的小文件；不应用于一次传输大型代码产物。

这些边界是模型可参考的能力事实，不是固定路线。模型仍应根据当前任务、文件大小、
已有上下文、输出预算、确认策略和验证证据选择可执行方案。

模型输出预算与上下文窗口是两个不同限制。上下文窗口很大，不代表单轮输出也足够
大。任意模型都可以声明 `max_output_tokens` 和该 Provider 接受的
`output_token_param`（`max_tokens`、`max_completion_tokens` 或
`max_output_tokens`）；未声明时 Runtime 不猜测参数，沿用 Provider 默认值。
高级 `request_options` 只用于 Provider 特殊透传参数，不能覆盖 Runtime 拥有的
`model`、`messages`、`tools`、`thinking`、`reasoning_effort` 或输出预算字段。
即使提高预算，模型仍应优先发送小补丁，而不是反复尝试完整大文件写入。

## ToolTask 与 Task 的边界

### 工具结果、证据与展示

ToolEvent 的 `output` 来自 `runtime/tool_result_evidence.py` 的独立审计投影，
保留完整路径数组、结构化结果、诊断和状态。`output_source.task_id` 指向原始
ToolTask；内联图片、音频等二进制不复制到 Run 事件，但可通过原始记录追溯。
`output_preview` 只负责前端展示，显示数量和文字预算不会裁剪下游完成证据。
模型上下文仍单独按 `tool_event_presentation.py` 的预算压缩。历史事件缺少
`output_preview` 时，前端兼容使用原有 `output`。

执行前只检查工具可用性、参数与权限边界，不再根据任务契约附加能力路线、
文档覆盖或验证方式建议。工具结果中的 `runtime_risks` 保留实际风险事实，
不携带推荐动作、替代工具或恢复路线；原始诊断仍在工具输出中。详见
[tool-result-risks.md](tool-result-risks.md)。

### 文本调用兼容

默认仅结构化工具调用可进入执行。需要文本协议的模型或 Provider 必须显式配置
`text_tool_protocol` 为 `function_call`、`tagged` 或 `xml`；`none` 为关闭状态。
正文必须全部是该协议的完整调用块，解释文字、代码围栏和 reasoning 不参与恢复。
声明协议不会改变注册、参数检查、权限或操作确认。普通答案中的调用示例按内容
保留，不能仅因出现标记而执行或触发结果重写。

当前 `/tool-tasks` API 管理一次工具调用记录，也就是 `ToolTask`；`/tasks` API 管理产品层面的用户目标级 `Task`。

为了保持兼容，API 路径和旧字段暂时保留；为了让贡献者理解边界，公开记录会包含：

```json
{
  "schema_version": "0.1",
  "record_kind": "tool_task",
  "kind": "tool_task",
  "tool_id": "filesystem.scan_folder"
}
```

用户目标级 Task API 独立建模 Task / Plan / Step / Trace / Result，不把工具调用记录继续扩展成产品级任务。

MCP 图片结果在审计投影中包含 `inline_images` 元数据和原始 ToolTask 引用。
模型工具响应不包含媒体 base64；图片通过 Context Runtime 单独附加。捕获成功、
像素观察、Provider 接受和视觉审查是独立事实；当前 `visual_review_status` 保留
`unconfirmed`，不能用一次截图调用成功代替画面质量判断。

外部工具返回失败不证明此前的修改已回滚。失败风险记录保留
`side_effects=unknown / rollback_observed=false`，供模型结合实际状态决定如何恢复；
Runtime 不自动删除对象、重复执行或选择清理路线。
