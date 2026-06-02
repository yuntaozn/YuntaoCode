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
POST /tasks
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

## ToolTask 与 Task 的边界

当前 `/tasks` API 管理的是一次工具调用记录，也就是 `ToolTask`，不是未来产品层面的用户目标级 `Task`。

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
