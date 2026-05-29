# YuntaoCode

**云涛智能终端** — 面向开发者与办公场景的本地 AI 辅助工具。

由 [沈阳云涛智能科技有限公司](mailto:wutaoplay@outlook.com) 开发，基于 Tauri + Python sidecar 架构，将大语言模型能力与本地文件、代码、文档、终端深度集成。

> [English Version](README.en.md)

## 特性

- **本地优先**：文件读写、代码编辑、文档处理均在用户电脑执行，数据不出本机
- **智能对话**：流式对话 + 多轮工具调用，支持记忆管理、上下文压缩
- **工具生态**：文件系统、代码编辑、Shell、Git、文档处理、网页浏览等内置技能，支持插件扩展
- **记忆系统**：自动从对话中提取长期记忆，相关性过滤注入上下文
- **多模型支持**：兼容 OpenAI API 协议，支持火山方舟、通义千问、Ollama 等

## 快速开始

### 配置 API Key

启动服务后，打开设置页面配置模型接口和 API Key。**未配置 API Key 时无法进行对话。**

- **本地模型（Ollama/vLLM）**：可在设置中关闭“要求 API Key”选项
- **云端模型**：需要填写对应服务商的 API Key

### 登录说明

**当前版本登录功能不是强制的**，可以直接使用面板进行对话，无需登录。

### 开发模式

```powershell
cd YuntaoCode
pip install -r requirements.txt
python -m runtime.app --host 127.0.0.1 --port 8765 --workspace D:\code
```

启动后浏览器打开 `http://127.0.0.1:8765/` 即可使用本地面板。

### 桌面版打包

```powershell
cd desktop-shell
npm install
npm run build:windows
```

## 架构

YuntaoCode 的 Python Runtime 采用 Tornado 构建。相比偏向标准 API 服务的框架，Tornado 更适合作为本地异步运行时，承载 WebSocket 流式通信、工具调度、文件系统访问、Shell 执行和插件扩展等能力。

```text
yuntaocode/
  runtime/                 Python Tornado 本地运行时
    app.py                 服务入口
    config.py              运行配置
    conversation_runner.py 对话执行循环
    memory_store.py        记忆持久化存储
    memory_service.py      记忆相关性过滤
    memory_extractor.py    对话自动记忆提取
    tool_registry.py       工具注册中心
    context_manager.py     上下文压缩
    security.py            路径安全边界
    api/                   HTTP / WebSocket 接口
    skills/                本地技能（filesystem/code/shell/git/web/document/memory）
  desktop-shell/           Tauri 桌面壳
  docs/                    架构与工具协议说明
  requirements.txt         Python 运行时依赖
```

## 扩展指南

### 添加新工具

在 `runtime/skills/` 下新建模块，定义 handler 和 ToolSpec，然后在 `runtime/skills/__init__.py` 注册：

```python
from runtime.tool_registry import ToolRegistry, ToolSpec

def my_tool_handler(args, context):
    # context 包含 settings、path_guard 等
    return {"result": "..."}

def register_my_tools(registry: ToolRegistry):
    registry.register(
        ToolSpec(id="my.tool", name="我的工具", description="...", input_schema={...}),
        my_tool_handler,
    )
```

### 添加新 API

在 `runtime/api/` 下新建 handler，继承 `ApiHandler`，然后在 `runtime/app.py` 注册路由。

## 项目信息

| 项目 | 说明 |
|------|------|
| 名称 | YuntaoCode (云涛智能终端) |
| 公司 | 沈阳云涛智能科技有限公司 |
| 邮箱 | wutaoplay@outlook.com |
| 版本 | 0.1.0 |
| 协议 | Apache License 2.0 |

## License

[Apache License 2.0](LICENSE)

Copyright 2024-2026 沈阳云涛智能科技有限公司
