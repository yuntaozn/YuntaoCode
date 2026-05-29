# 本地工具协议

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
