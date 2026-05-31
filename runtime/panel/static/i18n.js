/**
 * YuntaoCode i18n - Internationalization module
 * Supports zh-CN and en locales with localStorage persistence.
 */

const LOCALES = {
    "zh-CN": {
        // === Navigation (HTML) ===
        "nav.new_conversation": "新对话",
        "nav.search": "搜索",
        "nav.plugins": "插件",
        "nav.automation": "自动化",
        "nav.settings": "设置",
        "nav.logout": "退出",
        "nav.back": "返回",
        "nav.main_nav": "主导航",

        // === Sidebar (HTML) ===
        "sidebar.backend_account": "后台账号",
        "sidebar.not_logged_in": "未登录",
        "sidebar.login": "登录",
        "sidebar.model": "模型",
        "sidebar.project_dirs": "项目目录",
        "sidebar.select_folder": "选择工作空间",
        "sidebar.conversations": "对话",
        "sidebar.search_history": "搜索历史对话",

        // === Topbar (HTML) ===
        "topbar.select_project": "选择工作空间",
        "topbar.bind_conversation": "对话会绑定到当前项目",
        "topbar.tools_not_loaded": "工具未加载",
        "topbar.local_placeholder": "本地占位模式",

        // === Composer (HTML) ===
        "composer.send": "发送",
        "composer.interrupt": "插话",
        "composer.stop": "停止",
        "composer.upload_image": "上传图片",
        "composer.plan_auto": "计划: 自动",
        "composer.select_project_first": "先选择工作空间，再开始对话",
        "composer.placeholder": "向 YuntaoCode 提问，输入 @ 可提及工具或文件",

        // === Status bar ===
        "status.executing": "正在执行",
        "status.continue_exec": "继续执行",
        "status.stop_btn": "停止",
        "status.thinking": "正在思考",
        "status.stopped": "已停止",
        "status.stopped_generating": "（已停止生成）",
        "status.generating": "继续生成中",
        "status.reasoning": "正在推理",
        "status.reasoning_block_title": "思考过程",
        "status.reasoning_live": "流式生成",
        "process.history_title": "过程记录",
        "process.history_count": "{count} 条",
        "process.draft": "中间回复 {n}",
        "process.reasoning_snapshot": "思考快照 {n}",
        "status.compressing": "压缩中...",
        "status.preparing_plan": "正在准备计划",
        "status.direct_exec": "直接执行中",
        "status.exec_by_plan": "正在按计划执行",
        "status.advancing_plan": "正在推进计划",
        "status.organizing_changes": "正在整理本轮变更",
        "status.correcting_tool": "正在纠偏工具调用",
        "status.continuing": "正在继续...",
        "status.stopping": "正在停止...",
        "status.confirm_pause": "任务暂停，等待确认",
        "status.waiting_confirm": "等待确认",
        "status.guidance_received": "已收到插话，正在重新审视任务",
        "status.model_still_processing": "模型仍在处理，请稍候",
        "status.waited": "，已等待 ",
        "status.model_still": "，模型仍在处理",

        // === Settings dialog (HTML) ===
        "settings.title": "设置",
        "settings.key_hint": "模型 Key 保存在本机用户配置目录，不写入项目目录。",
        "settings.close": "关闭",
        "settings.volcengine_key": "火山方舟 API Key",
        "settings.qwen_key": "通义千问 API Key",
        "settings.leave_empty": "留空表示不修改",
        "settings.not_configured": "未配置",
        "settings.execution_perms": "执行与权限",
        "settings.file_access": "文件访问权限",
        "settings.access_project": "当前项目目录",
        "settings.access_full": "完全本机权限",
        "settings.access_full_warning": "完全本机权限会允许 AI 访问本机当前用户可访问的路径，请谨慎开启。",
        "settings.exec_mode": "执行模式",
        "settings.exec_conservative": "保守：少自动执行",
        "settings.exec_auto": "自动：系统判断",
        "settings.exec_aggressive": "激进：强制计划与验证",
        "settings.code_backup": "代码备份",
        "settings.auto_checkpoint": "写入前自动创建回退点",
        "settings.keep_recent": "保留最近批次",
        "settings.refresh": "刷新",
        "settings.restore_latest": "恢复最近一次",
        "settings.clear_backups": "清空备份",
        "settings.cancel": "取消",
        "settings.save": "保存",

        // === Plugins dialog (HTML) ===
        "plugins.title": "插件",
        "plugins.desc": "本地技能会以插件形式管理，后续可扩展启停、权限和配置。",
        "plugins.recent_tasks": "最近任务",
        "plugins.no_tasks": "暂无任务",

        // === Login dialog (HTML) ===
        "login.title": "登录后台",
        "login.username": "用户名",
        "login.password": "密码",
        "login.cancel": "取消",
        "login.login_btn": "登录",
        "login.register_link": "没有账号？去注册",

        // === Settings page (settings.html) ===
        "settings_page.title": "设置 - YuntaoCode",
        "settings_page.overview": "设置总览",
        "settings_page.loading": "读取中...",
        "settings_page.groups": "设置分组",
        "settings_page.group_models": "模型接口",
        "settings_page.group_runtime": "执行与权限",
        "settings_page.group_memories": "记忆管理",
        "settings_page.group_backups": "备份与回退",
        "settings_page.heading": "设置",
        "settings_page.subtitle": "管理本地模型配置、执行模式、访问权限、用户记忆和回退备份",
        "settings_page.models_title": "模型接口",
        "settings_page.models_desc": "管理默认模型、OpenAI-compatible 接口和每个模型的上下文、工具调用、思考参数。Ollama、vLLM、火山方舟和通义千问都可以放在这里。",
        "settings_page.default_model": "默认模型",
        "settings_page.provider": "接口 Provider",
        "settings_page.add_provider": "新增接口",
        "settings_page.model_list": "模型列表",
        "settings_page.add_model": "新增模型",
        "settings_page.runtime_title": "执行与权限",
        "settings_page.runtime_desc": "控制本地工具对文件系统的访问范围，以及 AI 在任务中推进计划、执行和验证的主动程度。",
        "settings_page.access_warning": "完全本机权限会允许 AI 访问本机当前用户可访问的路径。写入类工具仍会创建备份，但请只在信任当前任务时开启。",
        "settings_page.config_location": "配置文件位置",
        "settings_page.backups_title": "备份与回退",
        "settings_page.backups_desc": "写入工具执行前会保存受影响文件，便于非 Git 项目在修改失误后回退。一次任务改多个文件时，记录会列出本次触及的文件名。",
        "settings_page.refresh": "刷新",
        "settings_page.refreshed": "已刷新",
        "settings_page.refresh_backups": "刷新备份",
        "settings_page.memories_title": "记忆管理",
        "settings_page.memories_desc": "记忆用于让 AI 参考你的长期偏好和工作习惯。系统会在对话结束后自动提取值得记住的信息，你也可以手动管理。启用的记忆会按相关性注入上下文。",
        "settings_page.enable_memories": "启用用户记忆",
        "settings_page.auto_extract": "对话结束后自动提取记忆（AI 会从对话中学习值得记住的信息）",
        "settings_page.max_inject": "每次最多注入",
        "settings_page.current_memories": "当前记忆",
        "settings_page.memory_entries": "记忆条目",
        "settings_page.all_sources": "全部来源",
        "settings_page.source_manual": "手动添加",
        "settings_page.source_auto": "自动提取",
        "settings_page.source_conversation": "AI 保存",
        "settings_page.add_memory": "新增记忆",
        "settings_page.return": "返回",
        "settings_page.save_settings": "保存设置",
        "settings_page.language": "语言",

        // === Plugins page (plugins.html) ===
        "plugins_page.title": "插件管理 - YuntaoCode",
        "plugins_page.overview": "插件总览",
        "plugins_page.groups": "插件分组",
        "plugins_page.heading": "插件管理",
        "plugins_page.subtitle": "查看和管理本地技能插件及其依赖状态",
        "plugins_page.refresh": "刷新",

        // === Workspace (JS) ===
        "workspace.pinned": "置顶",
        "workspace.ops": "项目操作",
        "workspace.unpin": "取消置顶",
        "workspace.pin": "置顶项目",
        "workspace.open_explorer": "在资源管理器中打开",
        "workspace.remove": "移除",
        "workspace.select_dir": "请选择工作空间",
        "workspace.opened": "已打开项目目录",
        "workspace.select_first": "请先选择或添加工作空间",
        "workspace.not_found": "项目目录不存在，请重新选择",
        "workspace.confirm_remove": "从项目列表移除\"{name}\"？本地文件不会被删除。",
        "workspace.picked_but_failed": "项目已选择，但刷新列表失败：{error}",

        // === Conversations (JS) ===
        "conv.running": "运行中",
        "conv.messages_count": "{count} 条消息",
        "conv.delete_title": "删除对话",
        "conv.no_match": "暂无匹配对话",
        "conv.confirm_delete": "确定删除这个对话？",
        "conv.create_failed": "创建对话失败",
        "conv.deleted": "对话已删除",
        "conv.delete_failed": "删除失败：{error}",

        // === Tools/Skills (JS) ===
        "tools.count": "{count} 个本地技能",
        "tools.calling": "正在调用 {name}",
        "tools.completed": "已完成 {name}",
        "tools.calling_short": "调用中",
        "tools.called": "已调用",
        "tools.call_failed": "调用失败",
        "tools.failure_reason": "失败原因",
        "tools.failure_default": "工具执行失败，但后端没有返回详细原因。",
        "tools.path": "路径：",
        "tools.task": "任务：",
        "tools.working_clean": "工作区干净",
        "tools.file_created": "已新增文件",
        "tools.file_written": "已写入文件",
        "tools.exit_code_0": "✓ 退出码 0",
        "tools.exit_code": "✗ 退出码 {code}",

        // === Plugins (JS) ===
        "plugins.enabled": "已启用",
        "plugins.disabled": "已停用",
        "plugins.enabled_short": "启用",
        "plugins.deps": "依赖：",

        // === Empty chat (JS) ===
        "chat.empty_title": "我们该在 {name} 中做什么？",
        "chat.suggestion_scan": "扫描目录，概括这个项目的文件结构",
        "chat.suggestion_login": "帮我查找这个项目里和登录相关的代码",
        "chat.suggestion_analyze": "分析当前目录，给我一个下一步开发建议",
        "chat.guidance_chip": "运行中插话",
        "chat.guidance_sent": "已发送插话，系统会在安全点重新审视任务",

        // === Plan execution (JS) ===
        "plan.exec_title": "计划执行",
        "plan.source_auto": "自动判断",
        "plan.source_manual": "手动开启",
        "plan.source_plan": "计划执行",
        "plan.pending": "待执行",
        "plan.running": "执行中",
        "plan.completed": "完成",
        "plan.failed": "失败",
        "plan.skipped": "跳过",
        "plan.step": "步骤 {n}",
        "plan.exec_conservative": "执行: 保守",
        "plan.exec_auto": "执行: 自动",
        "plan.exec_aggressive": "执行: 激进",

        // === Backup (JS) ===
        "backup.batches": "已有 {count} 批",
        "backup.none": "暂无备份",
        "backup.latest": "最近一次",
        "backup.n": "备份 {n}",
        "backup.files": "{count} 个文件",
        "backup.restored": " · 已恢复过",
        "backup.hint": "写入工具成功执行后会在这里显示最近备份。",
        "backup.new_file": "新文件",
        "backup.unknown_file": "未知文件",
        "backup.more_files": "还有 {count} 个文件未展开",
        "backup.confirm_restore": "恢复备份会覆盖当前文件内容，确认继续？",
        "backup.restored_n": "已恢复 {count} 个文件",
        "backup.no_restore": "暂无可恢复备份",
        "backup.confirm_clear": "确认清空所有本地备份？清空后无法通过本功能恢复。",
        "backup.cleared": "备份已清空",
        "backup.badge": "已创建回退点 · {count} 个文件",
        "backup.restore": "恢复",
        "backup.recent_n_files": "显示最近 {n} 批备份，共 {total} 批，涉及 {files} 个文件",
        "backup.recent_latest": "最近一次备份",
        "backup.recent_n": "备份 {n}",
        "backup.n_files_etc": "{shown} 等 {count} 个文件",

        // === Changes (JS) ===
        "changes.touched": "本轮触达文件",
        "changes.changed": "本轮新增/变更文件",
        "changes.branch": "分支 {branch}",
        "changes.dirty": "工作区待处理 {count} 个",
        "changes.truncated": "仅显示前 80 个",

        // === Bulk replace (JS) ===
        "bulk.replace": "替换",
        "bulk.match": "匹配",
        "bulk.files_total": "{action} {files} 个文件，共 {total} 处",
        "bulk.occurrences": "{count} 处",
        "bulk.truncated": "结果过多，已截断显示",

        // === Execution notice (JS) ===
        "exec.validation": "执行校验",
        "exec.write_tool": "写入工具",

        // === Mentions (JS) ===
        "mention.project": "项目",
        "mention.tool": "工具",
        "mention.file": "文件",
        "mention.no_match": "暂无匹配项",

        // === Context (JS) ===
        "context.compress_click": "点击压缩上下文",
        "context.no_conversation": "没有活动对话",
        "context.compressed": "上下文已压缩：{before} → {after} tokens",
        "context.no_need": "对话内容较少，无需压缩",
        "context.compress_failed": "压缩失败：{error}",

        // === Image (JS) ===
        "image.select_file": "请选择图片文件",
        "image.max_5mb": "图片大小不能超过 5MB",
        "image.preview": "预览",
        "image.remove": "移除图片",

        // === Toast (JS) ===
        "toast.task_new_tab": "任务执行中，已在新页面打开，当前执行页会继续保留",
        "toast.task_allow_popup": "任务执行中，为避免丢失状态，请先完成任务或允许浏览器打开新页面",
        "toast.logged_out": "已退出后台账号",
        "toast.settings_saved": "设置已保存",
        "toast.confirm_failed": "确认失败: {error}",

        // === Error (JS) ===
        "error.model_failed": "模型返回失败",
        "error.empty_error": "模型服务返回了空错误对象",
        "error.load_failed": "加载对话失败",

        // === Auth (JS) ===
        "auth.fill_fields": "请填写后台地址、用户名和密码",
        "auth.logged_in": "已登录：{user}",

        // === Settings JS ===
        "settings_js.no_key": "未配置 Key",
        "settings_js.key_configured": "已配置：{hint}",
        "settings_js.provider_name": "接口名称",
        "settings_js.provider_type": "类型",
        "settings_js.leave_empty": "留空表示不修改",
        "settings_js.no_key_hint": "未配置；Ollama/vLLM 可关闭 Key 要求",
        "settings_js.require_key": "要求 API Key",
        "settings_js.provider_params": "接口默认参数 JSON",
        "settings_js.no_providers": "暂无接口，请新增 OpenAI-compatible 接口。",
        "settings_js.remove_provider": "移除",
        "settings_js.display_name": "显示名称",
        "settings_js.provider_label": "接口",
        "settings_js.api_model_name": "API 模型名",
        "settings_js.context_window": "上下文窗口 tokens",
        "settings_js.support_tools": "支持工具调用",
        "settings_js.thinking_mode": "思考参数模式",
        "settings_js.thinking_none": "无 / 标准 OpenAI",
        "settings_js.thinking_volcengine": "火山 thinking",
        "settings_js.thinking_qwen": "千问 enable_thinking",
        "settings_js.model_params": "模型参数 JSON",
        "settings_js.no_models": "暂无模型，请新增模型。",
        "settings_js.json_error": "JSON 参数格式错误：{error}",
        "settings_js.provider_exists": "接口 ID 已存在",
        "settings_js.provider_id_prompt": "接口 ID（例如 ollama-local）",
        "settings_js.model_id_prompt": "模型 ID / API 模型名（例如 qwen3:8b）",
        "settings_js.model_exists": "模型 ID 已存在",
        "settings_js.memory_prompt": "输入记忆内容（最多 500 字）：",
        "settings_js.memory_added": "记忆已添加",
        "settings_js.memory_saved": "记忆已保存",
        "settings_js.memory_deleted": "记忆已删除",
        "settings_js.add_failed": "添加失败：{error}",
        "settings_js.save_failed": "保存失败：{error}",
        "settings_js.delete_failed": "删除失败：{error}",
        "settings_js.confirm_delete_memory": "确认删除此记忆？",
        "settings_js.confirm_delete_provider": "移除接口 {id}？关联模型也需要改到其他接口后才能使用。",
        "settings_js.no_memories": "暂无记忆",
        "settings_js.memories_count": "{enabled} 条启用 / 共 {total} 条",
        "settings_js.source_manual": "手动",
        "settings_js.source_auto": "自动提取",
        "settings_js.source_conversation": "AI 保存",
        "settings_js.no_memory_filter": "该来源暂无记忆。",
        "settings_js.no_memory_all": "暂无记忆。可以新增一条记忆，或开启自动提取让 AI 从对话中学习。",
        "settings_js.memory_text_label": "记忆内容",
        "settings_js.memory_text_placeholder": "例如：用户偏好简洁直接的代码说明。",
        "settings_js.memory_tags_label": "标签",
        "settings_js.memory_tags_placeholder": "coding, writing, preference",
        "settings_js.memory_unnamed": "未命名记忆",
        "settings_js.memory_no_tags": "无标签",
        "settings_js.memory_usage": "使用 {count} 次",
        "settings_js.memory_save_btn": "保存",
        "settings_js.memory_delete_btn": "删除",
        "settings_js.memory_enabled": "启用",
        "settings_js.summary_full": "完全本机权限",
        "settings_js.summary_project": "当前项目目录",
        "settings_js.summary_conservative": "保守",
        "settings_js.summary_auto": "自动",
        "settings_js.summary_aggressive": "激进",
        "settings_js.summary_text": "{access} · {mode}执行 · {models} 个模型 · {memories} 条记忆",
        "settings_js.new_file": "新文件",
        "settings_js.unknown_file": "未知文件",

        // === Plugins JS ===
        "plugins_js.load_failed": "加载插件失败: {error}",
        "plugins_js.toggled": "{id} 已{state}",
        "plugins_js.enabled": "启用",
        "plugins_js.disabled": "禁用",
        "plugins_js.op_failed": "操作失败: {error}",
        "plugins_js.enabled_count": "{enabled}/{total} 已启用",
        "plugins_js.dep_missing": " · ⚠️ 存在依赖缺失",
        "plugins_js.all_plugins": "全部插件",
        "plugins_js.no_data": "暂无插件数据",
        "plugins_js.deps_label": "依赖：",

        // === Backend: Plugin descriptions ===
        "plugin.desc.filesystem": "本地文件与目录访问能力，用于扫描项目结构、读取和写入文件。",
        "plugin.desc.document": "本地文档处理能力，用于 Word、PDF、Markdown、PPT 等文档解析与生成。",
        "plugin.desc.code": "代码检索与编辑能力，用于列出代码文件、搜索文本和精确修改代码。",
        "plugin.desc.shell": "终端命令执行能力，可运行构建、测试、安装等命令。",
        "plugin.desc.git": "Git 版本控制能力，用于查看状态、差异和提交。",
        "plugin.desc.web": "网站访问能力，用于访问 URL、提取网页正文和渲染动态页面。",
        "plugin.name.filesystem": "文件系统",
        "plugin.name.document": "文档处理",
        "plugin.name.code": "代码检索与编辑",
        "plugin.name.shell": "终端命令",
        "plugin.name.git": "Git 版本控制",
        "plugin.name.web": "网站访问",
    },

    "en": {
        // === Navigation ===
        "nav.new_conversation": "New Chat",
        "nav.search": "Search",
        "nav.plugins": "Plugins",
        "nav.automation": "Automation",
        "nav.settings": "Settings",
        "nav.logout": "Logout",
        "nav.back": "Back",
        "nav.main_nav": "Main navigation",

        // === Sidebar ===
        "sidebar.backend_account": "Backend Account",
        "sidebar.not_logged_in": "Not logged in",
        "sidebar.login": "Login",
        "sidebar.model": "Model",
        "sidebar.project_dirs": "Projects",
        "sidebar.select_folder": "Choose workspace",
        "sidebar.conversations": "Chats",
        "sidebar.search_history": "Search history",

        // === Topbar ===
        "topbar.select_project": "Choose workspace",
        "topbar.bind_conversation": "Chats are bound to the current project",
        "topbar.tools_not_loaded": "Tools not loaded",
        "topbar.local_placeholder": "Local placeholder mode",

        // === Composer ===
        "composer.send": "Send",
        "composer.interrupt": "Interrupt",
        "composer.stop": "Stop",
        "composer.upload_image": "Upload image",
        "composer.plan_auto": "Plan: Auto",
        "composer.select_project_first": "Choose a workspace first",
        "composer.placeholder": "Ask YuntaoCode, type @ to mention tools or files",

        // === Status bar ===
        "status.executing": "Executing",
        "status.continue_exec": "Continue",
        "status.stop_btn": "Stop",
        "status.thinking": "Thinking",
        "status.stopped": "Stopped",
        "status.stopped_generating": "(Generation stopped)",
        "status.generating": "Continuing to generate",
        "status.reasoning": "Reasoning",
        "status.reasoning_block_title": "Thinking Process",
        "status.reasoning_live": "Streaming",
        "process.history_title": "Process History",
        "process.history_count": "{count} items",
        "process.draft": "Intermediate reply {n}",
        "process.reasoning_snapshot": "Thinking snapshot {n}",
        "status.compressing": "Compressing...",
        "status.preparing_plan": "Preparing plan",
        "status.direct_exec": "Executing directly",
        "status.exec_by_plan": "Executing by plan",
        "status.advancing_plan": "Advancing plan",
        "status.organizing_changes": "Organizing changes",
        "status.correcting_tool": "Correcting tool call",
        "status.continuing": "Continuing...",
        "status.stopping": "Stopping...",
        "status.confirm_pause": "Task paused, awaiting confirmation",
        "status.waiting_confirm": "Awaiting confirmation",
        "status.guidance_received": "Guidance received, re-evaluating task",
        "status.model_still_processing": "Model is still processing, please wait",
        "status.waited": ", waited ",
        "status.model_still": ", model still processing",

        // === Settings dialog ===
        "settings.title": "Settings",
        "settings.key_hint": "Model keys are stored in user config directory, not in project.",
        "settings.close": "Close",
        "settings.volcengine_key": "Volcengine API Key",
        "settings.qwen_key": "Qwen API Key",
        "settings.leave_empty": "Leave empty to keep unchanged",
        "settings.not_configured": "Not configured",
        "settings.execution_perms": "Execution & Permissions",
        "settings.file_access": "File Access",
        "settings.access_project": "Current project only",
        "settings.access_full": "Full local access",
        "settings.access_full_warning": "Full local access allows AI to reach any path accessible to the current user. Enable with caution.",
        "settings.exec_mode": "Execution Mode",
        "settings.exec_conservative": "Conservative: less auto-execution",
        "settings.exec_auto": "Auto: system decides",
        "settings.exec_aggressive": "Aggressive: enforced plan & verify",
        "settings.code_backup": "Code Backup",
        "settings.auto_checkpoint": "Auto-create checkpoint before writes",
        "settings.keep_recent": "Keep recent batches",
        "settings.refresh": "Refresh",
        "settings.restore_latest": "Restore latest",
        "settings.clear_backups": "Clear backups",
        "settings.cancel": "Cancel",
        "settings.save": "Save",

        // === Plugins dialog ===
        "plugins.title": "Plugins",
        "plugins.desc": "Local skills are managed as plugins. Start/stop, permissions and config coming soon.",
        "plugins.recent_tasks": "Recent Tasks",
        "plugins.no_tasks": "No tasks yet",

        // === Login dialog ===
        "login.title": "Backend Login",
        "login.username": "Username",
        "login.password": "Password",
        "login.cancel": "Cancel",
        "login.login_btn": "Login",
        "login.register_link": "No account? Register",

        // === Settings page ===
        "settings_page.title": "Settings - YuntaoCode",
        "settings_page.overview": "Settings Overview",
        "settings_page.loading": "Loading...",
        "settings_page.groups": "Settings Groups",
        "settings_page.group_models": "Model Providers",
        "settings_page.group_runtime": "Execution & Permissions",
        "settings_page.group_memories": "Memory Management",
        "settings_page.group_backups": "Backup & Rollback",
        "settings_page.heading": "Settings",
        "settings_page.subtitle": "Manage model config, execution mode, access, memories and backups",
        "settings_page.models_title": "Model Providers",
        "settings_page.models_desc": "Manage default model, OpenAI-compatible providers and per-model context, tool calling, thinking params. Ollama, vLLM, Volcengine and Qwen can all be configured here.",
        "settings_page.default_model": "Default Model",
        "settings_page.provider": "Provider",
        "settings_page.add_provider": "Add Provider",
        "settings_page.model_list": "Models",
        "settings_page.add_model": "Add Model",
        "settings_page.runtime_title": "Execution & Permissions",
        "settings_page.runtime_desc": "Control file system access scope and how proactively AI advances plans, executes and verifies tasks.",
        "settings_page.access_warning": "Full local access allows AI to reach any path accessible to the current user. Write tools still create backups, but enable only when you trust the current task.",
        "settings_page.config_location": "Config File Location",
        "settings_page.backups_title": "Backup & Rollback",
        "settings_page.backups_desc": "Write tools save affected files before execution, enabling rollback for non-Git projects after mistakes. Multi-file tasks list all touched files.",
        "settings_page.refresh": "Refresh",
        "settings_page.refreshed": "Refreshed",
        "settings_page.refresh_backups": "Refresh Backups",
        "settings_page.memories_title": "Memory Management",
        "settings_page.memories_desc": "Memories let AI reference your long-term preferences and habits. The system auto-extracts memorable info after conversations. You can also manage them manually. Enabled memories are injected by relevance.",
        "settings_page.enable_memories": "Enable user memories",
        "settings_page.auto_extract": "Auto-extract memories after conversations (AI learns from chats)",
        "settings_page.max_inject": "Max inject per turn",
        "settings_page.current_memories": "Current Memories",
        "settings_page.memory_entries": "Memory Entries",
        "settings_page.all_sources": "All Sources",
        "settings_page.source_manual": "Manual",
        "settings_page.source_auto": "Auto-extracted",
        "settings_page.source_conversation": "AI Saved",
        "settings_page.add_memory": "Add Memory",
        "settings_page.return": "Back",
        "settings_page.save_settings": "Save Settings",
        "settings_page.language": "Language",

        // === Plugins page ===
        "plugins_page.title": "Plugins - YuntaoCode",
        "plugins_page.overview": "Plugin Overview",
        "plugins_page.groups": "Plugin Groups",
        "plugins_page.heading": "Plugin Management",
        "plugins_page.subtitle": "View and manage local skill plugins and their dependencies",
        "plugins_page.refresh": "Refresh",

        // === Workspace ===
        "workspace.pinned": "Pinned",
        "workspace.ops": "Project actions",
        "workspace.unpin": "Unpin",
        "workspace.pin": "Pin project",
        "workspace.open_explorer": "Open in file explorer",
        "workspace.remove": "Remove",
        "workspace.select_dir": "Choose a workspace",
        "workspace.opened": "Project directory opened",
        "workspace.select_first": "Please choose or add a workspace first",
        "workspace.not_found": "Project directory not found, please reselect",
        "workspace.confirm_remove": "Remove \"{name}\" from project list? Local files will not be deleted.",
        "workspace.picked_but_failed": "Project selected, but failed to refresh list: {error}",

        // === Conversations ===
        "conv.running": "Running",
        "conv.messages_count": "{count} messages",
        "conv.delete_title": "Delete chat",
        "conv.no_match": "No matching chats",
        "conv.confirm_delete": "Delete this chat?",
        "conv.create_failed": "Failed to create conversation",
        "conv.deleted": "Chat deleted",
        "conv.delete_failed": "Delete failed: {error}",

        // === Tools/Skills ===
        "tools.count": "{count} local skills",
        "tools.calling": "Calling {name}",
        "tools.completed": "Completed {name}",
        "tools.calling_short": "Calling",
        "tools.called": "Called",
        "tools.call_failed": "Call failed",
        "tools.failure_reason": "Failure reason",
        "tools.failure_default": "Tool execution failed, but no detailed reason was returned.",
        "tools.path": "Path: ",
        "tools.task": "Task: ",
        "tools.working_clean": "Working tree clean",
        "tools.file_created": "File created",
        "tools.file_written": "File written",
        "tools.exit_code_0": "Exit code 0",
        "tools.exit_code": "Exit code {code}",

        // === Plugins ===
        "plugins.enabled": "Enabled",
        "plugins.disabled": "Disabled",
        "plugins.enabled_short": "Enabled",
        "plugins.deps": "Dependencies: ",

        // === Empty chat ===
        "chat.empty_title": "What should we do in {name}?",
        "chat.suggestion_scan": "Scan directory and summarize project structure",
        "chat.suggestion_login": "Find login-related code in this project",
        "chat.suggestion_analyze": "Analyze current directory and suggest next steps",
        "chat.guidance_chip": "Runtime guidance",
        "chat.guidance_sent": "Guidance sent, system will re-evaluate at a safe point",

        // === Plan execution ===
        "plan.exec_title": "Plan Execution",
        "plan.source_auto": "Auto-detected",
        "plan.source_manual": "Manually enabled",
        "plan.source_plan": "Plan Execution",
        "plan.pending": "Pending",
        "plan.running": "Running",
        "plan.completed": "Completed",
        "plan.failed": "Failed",
        "plan.skipped": "Skipped",
        "plan.step": "Step {n}",
        "plan.exec_conservative": "Exec: Conservative",
        "plan.exec_auto": "Exec: Auto",
        "plan.exec_aggressive": "Exec: Aggressive",

        // === Backup ===
        "backup.batches": "{count} batches",
        "backup.none": "No backups",
        "backup.latest": "Latest",
        "backup.n": "Backup {n}",
        "backup.files": "{count} files",
        "backup.restored": " · Restored",
        "backup.hint": "Recent backups will appear here after write tools execute successfully.",
        "backup.new_file": "New file",
        "backup.unknown_file": "Unknown file",
        "backup.more_files": "{count} more files not shown",
        "backup.confirm_restore": "Restoring backup will overwrite current files. Continue?",
        "backup.restored_n": "Restored {count} files",
        "backup.no_restore": "No backups to restore",
        "backup.confirm_clear": "Clear all local backups? This cannot be undone.",
        "backup.cleared": "Backups cleared",
        "backup.badge": "Checkpoint created · {count} files",
        "backup.restore": "Restore",
        "backup.recent_n_files": "Showing {n} recent batches, {total} total, {files} files",
        "backup.recent_latest": "Latest backup",
        "backup.recent_n": "Backup {n}",
        "backup.n_files_etc": "{shown} and {count} files",

        // === Changes ===
        "changes.touched": "Files touched this turn",
        "changes.changed": "New/changed files this turn",
        "changes.branch": "Branch {branch}",
        "changes.dirty": "{count} pending in working tree",
        "changes.truncated": "Showing first 80 only",

        // === Bulk replace ===
        "bulk.replace": "Replace",
        "bulk.match": "Match",
        "bulk.files_total": "{action} {files} files, {total} occurrences",
        "bulk.occurrences": "{count} occurrences",
        "bulk.truncated": "Results truncated",

        // === Execution notice ===
        "exec.validation": "Execution Validation",
        "exec.write_tool": "Write tool",

        // === Mentions ===
        "mention.project": "Project",
        "mention.tool": "Tool",
        "mention.file": "File",
        "mention.no_match": "No matches",

        // === Context ===
        "context.compress_click": "Click to compress context",
        "context.no_conversation": "No active conversation",
        "context.compressed": "Context compressed: {before} to {after} tokens",
        "context.no_need": "Conversation is short, no compression needed",
        "context.compress_failed": "Compression failed: {error}",

        // === Image ===
        "image.select_file": "Please select an image file",
        "image.max_5mb": "Image size must not exceed 5MB",
        "image.preview": "Preview",
        "image.remove": "Remove image",

        // === Toast ===
        "toast.task_new_tab": "Task running, opened in new tab, current page preserved",
        "toast.task_allow_popup": "Task running, please complete it or allow popups",
        "toast.logged_out": "Logged out",
        "toast.settings_saved": "Settings saved",
        "toast.confirm_failed": "Confirm failed: {error}",

        // === Error ===
        "error.model_failed": "Model returned failure",
        "error.empty_error": "Model service returned empty error object",
        "error.load_failed": "Failed to load conversation",

        // === Auth ===
        "auth.fill_fields": "Please enter backend URL, username and password",
        "auth.logged_in": "Logged in: {user}",

        // === Settings JS ===
        "settings_js.no_key": "No key configured",
        "settings_js.key_configured": "Configured: {hint}",
        "settings_js.provider_name": "Provider Name",
        "settings_js.provider_type": "Type",
        "settings_js.leave_empty": "Leave empty to keep unchanged",
        "settings_js.no_key_hint": "Not configured; Ollama/vLLM can disable key requirement",
        "settings_js.require_key": "Require API Key",
        "settings_js.provider_params": "Provider Default Params JSON",
        "settings_js.no_providers": "No providers yet. Add an OpenAI-compatible provider.",
        "settings_js.remove_provider": "Remove",
        "settings_js.display_name": "Display Name",
        "settings_js.provider_label": "Provider",
        "settings_js.api_model_name": "API Model Name",
        "settings_js.context_window": "Context Window Tokens",
        "settings_js.support_tools": "Support Tool Calling",
        "settings_js.thinking_mode": "Thinking Mode",
        "settings_js.thinking_none": "None / Standard OpenAI",
        "settings_js.thinking_volcengine": "Volcengine thinking",
        "settings_js.thinking_qwen": "Qwen enable_thinking",
        "settings_js.model_params": "Model Params JSON",
        "settings_js.no_models": "No models yet. Please add a model.",
        "settings_js.json_error": "JSON param format error: {error}",
        "settings_js.provider_exists": "Provider ID already exists",
        "settings_js.provider_id_prompt": "Provider ID (e.g. ollama-local)",
        "settings_js.model_id_prompt": "Model ID / API model name (e.g. qwen3:8b)",
        "settings_js.model_exists": "Model ID already exists",
        "settings_js.memory_prompt": "Enter memory content (max 500 chars):",
        "settings_js.memory_added": "Memory added",
        "settings_js.memory_saved": "Memory saved",
        "settings_js.memory_deleted": "Memory deleted",
        "settings_js.add_failed": "Add failed: {error}",
        "settings_js.save_failed": "Save failed: {error}",
        "settings_js.delete_failed": "Delete failed: {error}",
        "settings_js.confirm_delete_memory": "Delete this memory?",
        "settings_js.confirm_delete_provider": "Remove provider {id}? Linked models must be reassigned first.",
        "settings_js.no_memories": "No memories",
        "settings_js.memories_count": "{enabled} enabled / {total} total",
        "settings_js.source_manual": "Manual",
        "settings_js.source_auto": "Auto-extracted",
        "settings_js.source_conversation": "AI Saved",
        "settings_js.no_memory_filter": "No memories from this source.",
        "settings_js.no_memory_all": "No memories yet. Add one or enable auto-extraction for AI to learn from chats.",
        "settings_js.memory_text_label": "Memory Content",
        "settings_js.memory_text_placeholder": "e.g.: User prefers concise code explanations.",
        "settings_js.memory_tags_label": "Tags",
        "settings_js.memory_tags_placeholder": "coding, writing, preference",
        "settings_js.memory_unnamed": "Unnamed memory",
        "settings_js.memory_no_tags": "No tags",
        "settings_js.memory_usage": "Used {count} times",
        "settings_js.memory_save_btn": "Save",
        "settings_js.memory_delete_btn": "Delete",
        "settings_js.memory_enabled": "Enabled",
        "settings_js.summary_full": "Full local access",
        "settings_js.summary_project": "Project only",
        "settings_js.summary_conservative": "Conservative",
        "settings_js.summary_auto": "Auto",
        "settings_js.summary_aggressive": "Aggressive",
        "settings_js.summary_text": "{access} · {mode} exec · {models} models · {memories} memories",
        "settings_js.new_file": "New file",
        "settings_js.unknown_file": "Unknown file",

        // === Plugins JS ===
        "plugins_js.load_failed": "Failed to load plugins: {error}",
        "plugins_js.toggled": "{id} {state}",
        "plugins_js.enabled": "enabled",
        "plugins_js.disabled": "disabled",
        "plugins_js.op_failed": "Operation failed: {error}",
        "plugins_js.enabled_count": "{enabled}/{total} enabled",
        "plugins_js.dep_missing": " · ⚠️ Missing dependencies",
        "plugins_js.all_plugins": "All Plugins",
        "plugins_js.no_data": "No plugin data",
        "plugins_js.deps_label": "Dependencies: ",

        // === Backend: Plugin descriptions ===
        "plugin.desc.filesystem": "Local file and directory access for scanning project structure, reading and writing files.",
        "plugin.desc.document": "Local document processing for Word, PDF, Markdown, PPT parsing and generation.",
        "plugin.desc.code": "Code search and editing for listing files, searching text and precise code modifications.",
        "plugin.desc.shell": "Terminal command execution for build, test, install and more.",
        "plugin.desc.git": "Git version control for status, diff and commits.",
        "plugin.desc.web": "Web access for fetching URLs, extracting content and rendering dynamic pages.",
        "plugin.name.filesystem": "File System",
        "plugin.name.document": "Document Processing",
        "plugin.name.code": "Code Search & Edit",
        "plugin.name.shell": "Terminal Commands",
        "plugin.name.git": "Git Version Control",
        "plugin.name.web": "Web Access",
    },
};

const I18N_STORAGE_KEY = "yuntaocode_locale";

function getLocale() {
    return localStorage.getItem(I18N_STORAGE_KEY) || "zh-CN";
}

function setLocale(lang) {
    if (!LOCALES[lang]) return;
    localStorage.setItem(I18N_STORAGE_KEY, lang);
    applyI18n();
    // Dispatch event for other scripts to react
    window.dispatchEvent(new CustomEvent("locale-changed", { detail: { locale: lang } }));
}

function t(key, vars) {
    const locale = getLocale();
    const dict = LOCALES[locale] || LOCALES["zh-CN"];
    let text = dict[key] || LOCALES["zh-CN"][key] || key;
    if (vars) {
        for (const [k, v] of Object.entries(vars)) {
            text = text.replace(new RegExp("\\{" + k + "\\}", "g"), String(v));
        }
    }
    return text;
}

function applyI18n(root) {
    const container = root || document;
    container.querySelectorAll("[data-i18n]").forEach((el) => {
        const key = el.getAttribute("data-i18n");
        el.textContent = t(key);
    });
    container.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        const key = el.getAttribute("data-i18n-placeholder");
        el.placeholder = t(key);
    });
    container.querySelectorAll("[data-i18n-title]").forEach((el) => {
        const key = el.getAttribute("data-i18n-title");
        el.title = t(key);
    });
    container.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
        const key = el.getAttribute("data-i18n-aria-label");
        el.setAttribute("aria-label", t(key));
    });
    // Update <title>
    const titleEl = container.querySelector("title[data-i18n]");
    if (titleEl) document.title = t(titleEl.getAttribute("data-i18n"));
}

function applyI18nDynamic(container) {
    applyI18n(container);
}

// Auto-apply on DOMContentLoaded
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => applyI18n());
} else {
    applyI18n();
}
