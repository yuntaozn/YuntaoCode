"""从对话 Runner 提取的 Agent 策略辅助包。

本包将面向模型的策略事实与 API、Runner 管道分离。辅助函数应暴露 Schema、证据、
提示和审计事实，不应成为隐藏任务路由器或工具路线锁。

- ``classifiers``：工具事实、协议辅助函数和进度观察
- ``capability_grounding``：规范化模型选定的能力引用
- ``capability_router``：能力契约与模型优先的路线提案
- ``contract_evolution``：模型明确声明的续接关系与成功事实
- ``conversation_task_context``：有界历史任务候选
- ``context_hygiene``：执行前的模型上下文清理
- ``convergence``：由进展驱动的执行收敛观察
- ``document_completion``：长文本与文档完成证据
- ``document_contract_guard``：文档导出证据建议
- ``profiles``：不控制路线或预算的内部 Profile 描述
- ``policy``：用户计划策略门禁
- ``prompts``：各执行阶段的提示构建
- ``run_finalization``：根据可观察证据生成纯 Run 收尾门禁
- ``task_contract``：模型任务契约与 Runtime 自有 Schema 边界
- ``tool_execution_guard``：执行前安全与建议管道
- ``tool_result_risks``：不阻塞、面向模型的风险证据
- ``plan_tracker``：执行计划生命周期管理"""