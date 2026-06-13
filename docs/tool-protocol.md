# 本地工具协议

工具协议服务于 Task Runtime。工具定义系统“能做什么”，但任务模型定义系统“为什么做、做到哪一步、如何恢复和审计”。任务模型草案见 [task-model.md](task-model.md)。

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

后续可以加：

```text
waiting_confirmation
cancelled
```

## 任务流程里的意义

任务流程以后不要只编排提示词，而是编排工具：

```text
扫描资料目录
-> 提取 Word/PDF 文本
-> 后台模型识别工程信息
-> 本地生成审查报告
-> 人工确认
```

## 临时产物

临时脚本、中间 JSON、探测输出等一次性文件应写入任务临时目录，而不是写入用户项目目录。

推荐工具流程：

```text
filesystem.write_temp_file
-> shell.run_command(cwd="task_temp")
-> 根据结果决定是否写入真实项目文件
```

`filesystem.write_temp_file` 产物属于 ToolTask 的临时产物，不应视为真实项目变更，也不能满足“已完成代码修改/已生成项目文件”的成功条件。

跨平台命令优先使用 `command` + `args` 参数数组。只有任务明确依赖某个平台时，才使用 PowerShell、bash、cp、rm、Copy-Item 等平台专属语法。

## 模型工具调用边界

模型必须通过接口提供的结构化工具调用协议调用工具，并提供工具输入 schema
要求的参数。普通回复文本中的 `<toolcall>`、`<mcreference>`、FunctionCall
标记或无参数工具名，不属于成功工具调用。

运行时可以兼容解析少量模型供应商输出的文本工具调用格式。工具参数必须是完整的
JSON 对象；无法解析、不是对象或缺少必要参数时，运行时记录协议失败并且不执行，
也不猜测、补全或修复参数。失败结果会回到模型上下文，由模型自行决定下一步策略。
最终回复不得包含未执行的工具调用标签。

模型 Provider 的流事件应保留 `finish_reason`。当一轮因 `length`、
`max_tokens` 或 `max_output_tokens` 停止时，本轮工具调用视为可能截断，不得执行。
这条规则尤其保护 `filesystem.write_file`、Shell、Git 等会改变本地状态的工具。

代码展示格式化与工具调用传输是两层问题：Markdown、高亮和格式化器只负责展示或
写后质量检查，不能修复被模型输出上限截断的工具参数。小范围修改优先使用结构化
编辑工具；完整文件写入必须以一次完整、可解析的工具调用到达运行时。

## 代码写入协议

代码写入优先使用 `code.apply_patch`。它参考 Codex 风格的小块补丁协议：

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

写入能力的推荐边界：

- `code.apply_patch`：首选，适合已有代码的小块增量修改，也支持创建小文件。
- `code.edit_file`：适合明确知道唯一 `old_text` / `new_text` 的精确替换。
- `code.replace_text`：适合跨文件的同一文本批量替换。
- `filesystem.write_file`：适合完整的小文件；不应用于一次传输大型代码产物。

模型输出预算与上下文窗口是两个不同限制。上下文窗口很大，不代表单轮输出也足够
大。任意模型都可以声明 `max_output_tokens` 和该 Provider 接受的
`output_token_param`（`max_tokens`、`max_completion_tokens` 或
`max_output_tokens`）；未声明时 Runtime 不猜测参数，沿用 Provider 默认值。
低层 `request_options` 可以覆盖声明值。即使提高预算，模型仍应优先发送小补丁，
而不是反复尝试完整大文件写入。

## ToolTask 与 Task 的边界

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

未来如果引入用户目标级 Task API，应独立建模 Task / Plan / Step / Trace / Result，不要继续把工具调用记录扩展成产品级任务。
