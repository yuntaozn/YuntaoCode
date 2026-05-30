# YuntaoCode — 云涛智能终端

**Local-First AI Runtime & 智能终端平台**  
由真实工程项目实践演化而来，YuntaoCode 将大语言模型与本地工具、文件系统、Shell、Git、文档处理、记忆管理及任务调度深度融合，为本地 AI Agent 提供稳定、可扩展的运行环境。

---

## 为什么选择 YuntaoCode

YuntaoCode 并非从宏大产品规划开始，而是从多个真实项目积累演化而来：

- SaaS 系统、知识库、智能评分、BIM/工程应用
- 机器人巡检与本地模型实践
- 本地 AI Agent 与多轮工具调用

在这些工程实践中，我们发现：

- 模型和工具不断演进  
- 稳定的本地 Runtime 和工具协同能力是长期价值核心  
- 高校教学和工程实验场景需要可控、本地化、可扩展的平台  

因此，YuntaoCode 并非一个简单的聊天终端，而是 **Local-First AI Runtime 平台**。

---

## 核心特性

### 本地优先
- 所有文件读写、代码执行、文档处理均在用户本机完成  
- 用户数据完全本地化

### 工具生态
- 内置工具：文件系统、Shell、Git、文档处理、网页访问  
- 支持插件扩展，开发者可自定义技能

### 记忆系统
- 自动从对话和操作中提取长期记忆  
- 支持相关性检索和上下文压缩注入

### 多模型支持
- OpenAI API 兼容  
- 支持 Ollama、火山方舟、通义千问等本地/远程模型

### 可扩展与自我进化预设
- 记录工具调用和操作结果  
- 生成经验、提示词、任务优化建议  
- 支持受控的自我优化策略（用户确认执行）

---

## 架构概览

```text
                YuntaoCode Runtime

┌─────────────────────────────────────┐
│ Memory                              │
│ Context Manager                     │
│ Tool Registry                       │
│ Conversation Runner                 │
│ Task Scheduler                      │
└──────────────────┬──────────────────┘
                   │

      ┌────────────┼────────────┐
      │            │            │

      ▼            ▼            ▼

   Desktop      Browser       API

      │            │            │

      └─────── UI Layer ────────┘

Tools:
- Filesystem
- Shell
- Git
- Document
- Web
- Memory
- Models

Python Runtime 是核心，Tauri 桌面壳只是界面层。

快速开始
克隆仓库
git clone https://github.com/yuntaozn/YuntaoCode.git
cd YuntaoCode
安装依赖
pip install -r requirements.txt
启动 Runtime
python -m runtime.app --host 127.0.0.1 --port 8765

浏览器访问：

http://127.0.0.1:8765
打包桌面版
cd desktop-shell
npm install
npm run build:windows
扩展指南
添加新工具

在 runtime/skills/ 下创建模块，定义 handler 和 ToolSpec，并在 __init__.py 注册：

from runtime.tool_registry import ToolRegistry, ToolSpec

def my_tool_handler(args, context):
    return {"result": "..."}

def register_my_tools(registry: ToolRegistry):
    registry.register(
        ToolSpec(id="my.tool", name="我的工具", description="...", input_schema={}),
        my_tool_handler,
    )
添加新 API

在 runtime/api/ 下创建 handler，继承 ApiHandler，并在 runtime/app.py 注册路由。

开发计划（Roadmap）
v0.1
 本地 AI 对话
 工具调用
 文件系统 / Shell / Git
 记忆系统
v0.2
 MCP 支持
 插件系统
 多工作区
v0.3
 本地知识库
 工作流编排
 Agent 自动任务
v1.0
 企业部署
 团队协作
 插件市场
教育场景

YuntaoCode 适合高校教学和工程实验：

AI Agent 实训
MCP 教学
RAG 教学
本地大模型部署实验
软件工程课程案例
项目状态
当前版本：0.1.0
状态：活跃开发中
API 和插件接口可能在 v1.0 前调整
License

Apache License 2.0
LICENSE