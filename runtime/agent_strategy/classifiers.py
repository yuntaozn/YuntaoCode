"""Strategy helpers extracted from ConversationMessagesStreamHandler.

Functions in this module have no ``self`` dependency and perform no I/O.
Most are pure value transforms; functions such as ``merge_tool_call_chunks``
intentionally update caller-provided accumulators in place.
They can be tested in isolation without a Tornado handler or runtime context.
"""

from __future__ import annotations

import json
import re
from typing import Any

from runtime.tool_aliases import TOOL_ID_ALIASES, normalize_tool_id

from .profiles import (
    profile_for_task_intent,
    round_limit_for_profile,
    stage_sequence_for_profile,
)


# ---------------------------------------------------------------------------
# Tool-ID constants
# ---------------------------------------------------------------------------

DOCUMENT_WRITE_TOOL_IDS: frozenset[str] = frozenset({
    "document.export_markdown",
    "document.export_docx",
    "document.extract_pdf_to_docx",
    "document.translate_docx",
    "document.generate_docx_from_outline",
    "document.export_pdf",
    "document.generate_ppt",
    "document.merge_pdfs",
    "document.split_pdf",
    "document.create_bookmark_outline",
})

WRITE_TOOL_IDS: frozenset[str] = frozenset({
    "code.apply_patch",
    "code.edit_file",
    "code.replace_text",
    "filesystem.transform_text",
    "filesystem.write_file",
    *DOCUMENT_WRITE_TOOL_IDS,
})

POST_WRITE_VERIFY_TOOL_IDS: frozenset[str] = frozenset({
    "shell.run_command",
    "git.status",
    "git.diff",
    "code.search_text",
    "code.list_project_files",
    "git.log",
})

NATIVE_TOOL_CALL_BEGIN = "<|FunctionCallBegin|>"
NATIVE_TOOL_CALL_END = "<|FunctionCallEnd|>"
XML_TOOL_CALL_PATTERN = re.compile(
    r"<(?P<name>[A-Za-z][\w]*(?:[._][\w]+)+)>(?P<body>.*?)</(?P=name)>",
    re.DOTALL,
)
XML_TOOL_ARG_PATTERN = re.compile(
    r"<arg-key>(?P<key>.*?)</arg-key>\s*<arg-value>(?P<value>.*?)</arg-value>",
    re.DOTALL,
)
MCP_REFERENCE_TOOL_CALL_PATTERN = re.compile(
    r"<mcreference\b[^>]*>\s*<toolcall\b[^>]*>.*?</toolcall>\s*</mcreference>",
    re.DOTALL | re.IGNORECASE,
)
TAGGED_TOOL_CALL_PATTERN = re.compile(
    r"<toolcall\b[^>]*>(?P<body>.*?)</toolcall>",
    re.DOTALL | re.IGNORECASE,
)
BARE_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z][\w]*(?:[._][\w]+)+")
BARE_TAGGED_TOOL_CALL_IDS: frozenset[str] = frozenset({
    "filesystem.scan_folder",
    "code.list_project_files",
    "git.status",
})

POST_WRITE_READ_TOOL_IDS: frozenset[str] = frozenset({
    "filesystem.read_file",
    "filesystem.read_text_preview",
    "filesystem.scan_folder",
})

LONG_RUNNING_SERVICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpython(?:3|\.exe)?\s+-m\s+http\.server\b", re.IGNORECASE),
    re.compile(r"\bpy\s+-m\s+http\.server\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+run\s+(dev|serve|start)\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+start\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(dev|serve|start)\b", re.IGNORECASE),
    re.compile(r"\byarn\s+(dev|serve|start)\b", re.IGNORECASE),
    re.compile(r"\b(vite|next|nuxt|astro)\s+dev\b", re.IGNORECASE),
    re.compile(r"\bwebpack-dev-server\b", re.IGNORECASE),
    re.compile(r"\bpython(?:3|\.exe)?\s+manage\.py\s+runserver\b", re.IGNORECASE),
    re.compile(r"\bflask\s+run\b", re.IGNORECASE),
    re.compile(r"\buvicorn\b.*\s+--reload\b", re.IGNORECASE),
    re.compile(r"\bstreamlit\s+run\b", re.IGNORECASE),
)

RECON_TOOL_IDS: frozenset[str] = frozenset({
    "filesystem.scan_folder",
    "filesystem.read_file",
    "filesystem.read_text_preview",
    "document.extract_docx_outline",
    "document.extract_pdf_text_preview",
    "code.search_text",
    "code.list_project_files",
    "git.status",
    "git.diff",
    "git.log",
})

STATE_CHANGING_EXTRA_TOOL_IDS: frozenset[str] = frozenset({
    "shell.run_command",
    "git.commit",
})


# ---------------------------------------------------------------------------
# Tool classification helpers
# ---------------------------------------------------------------------------

def canonical_tool_id(value: Any) -> str:
    """Convert model-emitted tool IDs to registered runtime tool IDs."""
    return normalize_tool_id(value)


def explorer_tool_ids(mode: str | None) -> set[str]:
    """Return the set of tool IDs available during the explorer stage."""
    base: set[str] = {
        "filesystem.scan_folder",
        "filesystem.read_file",
        "filesystem.read_text_preview",
        "document.extract_docx_outline",
        "document.extract_pdf_text_preview",
        "code.search_text",
        "code.list_project_files",
    }
    if mode in {"coding", "terminal"}:
        base |= {"git.status", "git.log"}
    return base


def verification_tool_ids(mode: str | None) -> set[str]:
    """Return the set of tool IDs that count as verification."""
    ids: set[str] = set(POST_WRITE_VERIFY_TOOL_IDS)
    if mode in {"document", "paper"}:
        ids |= {
            "filesystem.scan_folder",
            "filesystem.read_file",
            "filesystem.read_text_preview",
            "document.extract_docx_outline",
            "document.extract_pdf_text_preview",
        }
    return ids


def is_write_tool(tool_id: str) -> bool:
    tool_id = canonical_tool_id(tool_id)
    return tool_id in WRITE_TOOL_IDS


def is_recon_tool(tool_id: str) -> bool:
    tool_id = canonical_tool_id(tool_id)
    return tool_id in RECON_TOOL_IDS


def is_state_changing_tool(tool_id: str) -> bool:
    tool_id = canonical_tool_id(tool_id)
    return is_write_tool(tool_id) or tool_id in STATE_CHANGING_EXTRA_TOOL_IDS


def is_verification_tool(tool_id: str, mode: str | None) -> bool:
    tool_id = canonical_tool_id(tool_id)
    return tool_id in verification_tool_ids(mode)


def shell_command_text(input_data: dict[str, Any] | None) -> str:
    if not isinstance(input_data, dict):
        return ""
    command = str(input_data.get("command") or "").strip()
    args = input_data.get("args") if isinstance(input_data.get("args"), list) else []
    arg_text = " ".join(str(item).strip() for item in args if str(item).strip())
    return f"{command} {arg_text}".strip()


def is_long_running_service_command(input_data: dict[str, Any] | None) -> bool:
    text = shell_command_text(input_data)
    if not text:
        return False
    normalized = text.replace("&&", " ; ").replace("|", " ")
    return any(pattern.search(normalized) for pattern in LONG_RUNNING_SERVICE_PATTERNS)


def is_invalid_verification_method_event(event: dict[str, Any]) -> bool:
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if tool_id != "shell.run_command":
        return False
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    reason = str(output.get("reason") or "").strip()
    if reason in {"invalid_verification_method", "long_running_service_verification"}:
        return True
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    return bool(output.get("timed_out") is True and is_long_running_service_command(event_input))


# ---------------------------------------------------------------------------
# Intent classification — user message
# ---------------------------------------------------------------------------

def has_no_write_instruction(content: str) -> bool:
    text = content.lower()
    if not text:
        return False
    no_write_terms = (
        "不要改代码", "不用改代码", "先不要改代码", "先别改代码", "别改代码", "不改代码",
        "不要修改代码", "不要改文件", "不要修改文件", "不要动文件", "不要动代码",
        "不要写入", "不要执行修改", "不要改动", "不需要改动", "不需要修改", "无需修改",
        "先不改", "只分析", "仅分析", "只看", "只检查", "只给建议", "给出建议",
        "调整建议", "改进建议", "不要改",
        "no code changes", "do not modify", "don't modify", "read only", "analysis only",
    )
    return any(term in text for term in no_write_terms)


def has_explicit_write_instruction(content: str) -> bool:
    text = content.lower()
    if not text:
        return False
    explicit_write_terms = (
        "帮我改", "帮我修", "帮我加", "帮我删", "开始改", "直接改", "继续改", "继续做",
        "继续优化", "优化网站", "优化页面", "优化其他页",
        "创建robots", "生成robots", "创建sitemap", "生成sitemap",
        "按你说的继续改进", "按你说的改",
        "修复", "改成", "改造", "改造成", "改为", "替换", "新增", "添加", "添加路由",
        "删除", "移除", "去掉", "实现", "创建页面", "创建逻辑", "独立页面",
        "修改导航", "接入", "更新", "重构", "补上", "写入", "生成文件", "变更",
        "恢复", "回退",
        "apply", "implement", "fix", "update", "modify", "change", "refactor",
        "remove", "delete", "add",
    )
    return any(term in text for term in explicit_write_terms)


def looks_like_read_only_request(content: str) -> bool:
    text = content.lower()
    if not text:
        return False
    if has_no_write_instruction(content):
        return True
    if has_explicit_write_instruction(content):
        return False
    read_only_terms = (
        "分析", "检查", "查看", "看下", "看看", "梳理", "评估", "审查", "建议",
        "方案", "思路", "解释", "说明", "为什么", "如何", "是否", "可行性",
        "状态", "现状", "风险", "问题", "原因", "定位", "排查",
        "review", "analyze", "analyse", "explain", "suggest", "recommend",
    )
    return any(term in text for term in read_only_terms)


def looks_like_document_export_request(content: str) -> bool:
    text = content.lower()
    pdf_word_pair = "pdf" in text and any(term in text for term in ("word", "docx"))
    document_transform_action = any(
        term in text
        for term in (
            "导", "转", "生成", "输出", "保存", "提取", "重做", "重新", "做成", "做一个", "做个",
            "convert", "export", "extract", "generate", "save",
        )
    )
    pdf_layout_terms = any(
        term in text
        for term in ("图文", "图片", "文字", "带图", "保留图片", "排版", "image", "text", "layout")
    )
    if pdf_word_pair and (document_transform_action or pdf_layout_terms):
        return True
    if "pdf" in text and pdf_layout_terms and document_transform_action:
        return True
    export_terms = (
        "导出", "生成word", "生成 word", "生成docx", "生成 docx",
        "生成pdf", "生成 pdf", "生成ppt", "生成 ppt",
        "保存为", "写成文件", "输出文件", "转存word", "转存 word",
        "转成word", "转成 word", "转为word", "转为 word",
        "转换成word", "转换成 word", "转换为word", "转换为 word",
        "转存docx", "转存 docx", "转成docx", "转成 docx",
        "转为docx", "转为 docx", "转换成docx", "转换成 docx",
        "转换为docx", "转换为 docx",
        "pdf转word", "pdf 转 word", "pdf转docx", "pdf 转 docx",
        "pdf文字提取", "pdf 文本提取", "提取pdf", "提取 pdf",
        "中文版", "翻译成中文", "翻译为中文", "翻译成中文版", "翻译为中文版",
        "翻译中文版", "翻译个中文版", "转成中文", "转为中文", "中文翻译",
        ".docx", ".pdf", ".pptx", ".md",
    )
    return any(term in text for term in export_terms)


def looks_like_full_document_output_request(content: str) -> bool:
    text = content.lower()
    if not text:
        return False
    pdf_word_pair = "pdf" in text and any(term in text for term in ("word", "docx"))
    document_transform_action = any(
        term in text
        for term in (
            "导", "转", "生成", "输出", "保存", "提取", "重做", "重新", "做成", "做一个", "做个",
            "convert", "export", "extract", "generate", "save",
        )
    )
    pdf_layout_terms = any(
        term in text
        for term in ("图文", "图片", "文字", "带图", "保留图片", "排版", "image", "text", "layout")
    )
    if pdf_word_pair and (document_transform_action or pdf_layout_terms):
        return True
    if "pdf" in text and pdf_layout_terms and document_transform_action:
        return True
    transform_terms = (
        "翻译", "中文版", "转成中文", "转为中文", "中文翻译",
        "pdf转word", "pdf 转 word", "pdf转docx", "pdf 转 docx",
        "转存word", "转存 word", "转换成word", "转换为word",
        "转换成 docx", "转换为 docx", "提取pdf", "提取 pdf",
    )
    full_terms = ("全文", "完整", "全部", "整本", "全书", "全篇", "每页", "所有")
    return any(term in text for term in transform_terms) or (
        any(term in text for term in full_terms)
        and any(term in text for term in ("文档", "文件", "docx", "pdf", "word"))
    )


def looks_like_paper_task(content: str) -> bool:
    text = content.lower()
    if not text:
        return False
    paper_terms = (
        "论文", "文献综述", "系统综述", "研究设计", "研究问题", "研究假设", "研究方法",
        "摘要", "引言", "相关工作", "方法论", "讨论", "结论", "参考文献", "引用",
        "审稿", "审稿意见", "审稿回复", "投稿", "期刊", "学术", "开题", "课题",
        "paper", "literature review", "systematic review", "abstract", "citation",
        "reviewer", "journal", "doi",
    )
    return any(term in text for term in paper_terms)


def looks_like_follow_up_execution(content: str) -> bool:
    text = content.strip().lower()
    if len(text) > 40:
        return False
    terms = (
        "继续", "再执行", "再次执行", "重新执行", "重试", "再试", "试试",
        "继续优化", "继续执行", "继续处理", "接着做", "往下做", "接着改",
        "按这个改", "就这样改", "继续改", "继续做", "再来一次",
        "失败了", "没成功", "没生成", "没能成功", "没执行完", "不完整",
    )
    return any(term in text for term in terms)


def looks_like_code_change_request(content: str) -> bool:
    text = content.lower()
    if not text:
        return False

    # Analysis-only requests should NOT be treated as code change
    analysis_only_terms = (
        "分析代码", "检查代码", "看下代码", "代码逻辑", "解读代码",
        "帮我看看", "帮我分析", "帮我理解", "什么意思", "怎么工作",
        "调用工具", "能否找到原因", "排查", "定位问题",
    )
    if any(term in text for term in analysis_only_terms):
        explicit_write = ("并修复", "然后改", "然后修", "并改", "顺便改", "帮我修")
        if not any(term in text for term in explicit_write):
            return False

    code_context_terms = (
        ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".css", ".json",
        "代码", "文件", "函数", "组件", "页面", "前端", "后端", "接口", "路由",
        "端口", "配置", "样式", "布局", "按钮", "输入框", "目录", "登录",
        "报错", "bug", "ui", "css", "js", "html", "vue", "react",
        "seo", "网站", "网页", "meta", "robots.txt", "sitemap.xml",
        "canonical", "open graph", "twitter card",
    )
    direct_write_terms = (
        "帮我改", "帮我修", "帮我加", "帮我删", "开始做", "直接改", "修复",
        "改成", "改造", "改造成", "改为", "替换", "新增", "添加", "添加路由",
        "删除", "移除", "去掉", "实现", "创建页面", "创建逻辑", "独立页面",
        "修改导航", "接入", "更新", "调整", "重构", "补上", "写入", "生成",
        "变更", "恢复", "回退", "太大", "太小", "没反应", "加载不出来",
        "优化网站", "优化页面", "优化其他页", "继续优化",
        "创建robots", "生成robots", "创建sitemap", "生成sitemap",
        "添加meta", "补充meta",
    )
    broad_write_terms = ("修改", "改", "修", "加", "删")

    if any(term in text for term in direct_write_terms):
        return True
    return any(term in text for term in broad_write_terms) and any(
        term in text for term in code_context_terms
    )


def looks_like_simple_code_change(content: str) -> bool:
    text = content.lower().strip()
    if len(text) > 100:
        return False
    broad_terms = (
        "全部", "完整", "全局", "很多文件", "多文件", "重构", "实现", "接入",
        "测试", "验证", "生成报告", "计划执行",
    )
    if any(term in text for term in broad_terms):
        return False
    simple_terms = (
        "字太大", "字太小", "太大", "太小", "改小", "改大", "按钮",
        "颜色", "间距", "文案", "样式", "布局", "显示", "隐藏", "没反应",
    )
    return any(term in text for term in simple_terms)


def looks_like_dangling_action(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    tail = text[-260:].lower()
    action_terms = (
        "让我先", "我先", "接下来", "现在我", "我将", "我会", "准备",
        "开始", "需要先", "继续", "let me", "i will", "next",
    )
    toolish_terms = (
        "验证", "检查", "读取", "搜索", "查找", "扫描", "修改", "写入",
        "替换", "运行", "调用", "测试", "确认", "verify", "check",
        "read", "search", "scan", "edit", "write", "run", "test",
    )
    dangling_endings = ("：", ":", "。", ".", "先验证一下", "先检查一下", "先读取", "开始执行修改")
    has_action = any(term in tail for term in action_terms)
    has_toolish = any(term in tail for term in toolish_terms)
    if has_action and has_toolish:
        if text.endswith(("：", ":")):
            return True
        if any(tail.endswith(ending.lower()) for ending in dangling_endings):
            return True
        return True
    return False


def user_requests_code_change(content: str, mode: str | None) -> bool:
    """Check if the user message in coding mode requests a code change."""
    if mode != "coding":
        return False
    if has_no_write_instruction(content):
        return False
    text = content.lower()
    inquiry_terms = (
        "建议", "分析", "解释", "为什么", "是否", "方案", "思路",
        "怎么", "如何", "检查", "查看",
    )
    direct_write_terms = (
        "帮我改", "帮我修", "帮我加", "帮我删", "开始做", "直接改", "修复",
        "改成", "改造", "改造成", "改为", "替换", "新增", "添加", "添加路由",
        "删除", "移除", "去掉", "实现", "创建页面", "创建逻辑", "独立页面",
        "修改导航", "接入", "更新", "调整", "重构", "补上", "写入", "生成",
        "变更", "恢复", "回退", "太大", "太小", "没反应", "加载不出来",
        "优化网站", "优化页面", "优化其他页", "继续优化",
        "创建robots", "生成robots", "创建sitemap", "生成sitemap",
        "添加meta", "补充meta",
    )
    broad_write_terms = ("修改", "改", "修", "加", "删")
    code_context_terms = (
        ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".css", ".json",
        "代码", "文件", "函数", "组件", "页面", "前端", "后端", "样式", "布局",
        "按钮", "ui", "端口", "配置", "接口", "路由", "seo", "网站", "网页",
        "meta", "robots.txt", "sitemap.xml", "canonical", "open graph", "twitter card",
    )
    if has_explicit_write_instruction(content) or any(term in text for term in direct_write_terms):
        return True
    if any(term in text for term in inquiry_terms):
        return False
    return any(term in text for term in broad_write_terms) and any(
        term in text for term in code_context_terms
    )


def code_change_intent(
    content: str,
    mode: str | None,
    *,
    has_previous_write: bool = False,
) -> bool:
    """Simplified code-change intent check without conversation history.

    The full conversation-aware version remains on the handler because it
    needs to traverse message history.  This pure variant covers the
    common single-message cases and is fully testable.
    """
    if has_no_write_instruction(content):
        return False
    if user_requests_code_change(content, mode):
        return True
    if looks_like_follow_up_execution(content) and has_previous_write:
        return True
    return False


def classify_task_intent(
    content: str,
    mode: str | None,
    *,
    has_previous_write: bool = False,
    is_follow_up_with_conversation: bool = False,
) -> str:
    """Classify the user's task intent from message content.

    Parameters
    ----------
    content : str
        The user message text.
    mode : str | None
        The current assistant mode (``"coding"``, ``"terminal"``, etc.).
    has_previous_write : bool
        Whether the conversation history contains a prior write context.
    is_follow_up_with_conversation : bool
        When ``True`` and the message looks like a follow-up with a
        conversation present, the caller should do additional history
        checks.  This pure function returns ``"write_required"`` for
        follow-ups when *has_previous_write* is True.
    """
    if has_no_write_instruction(content):
        return "read_only_analysis"
    if looks_like_follow_up_execution(content) and has_previous_write:
        return "write_required"
    if user_requests_code_change(content, "coding"):
        return "write_required"
    if looks_like_document_export_request(content):
        return "document_export"
    if looks_like_paper_task(content):
        return "paper_workflow"
    if mode == "coding":
        if user_requests_code_change(content, mode):
            return "write_required"
        if looks_like_read_only_request(content):
            return "read_only_analysis"
        if looks_like_follow_up_execution(content) and is_follow_up_with_conversation:
            # Caller needs to inspect conversation history for final verdict.
            # Default to "answer_only" here; the handler overrides with history.
            return "answer_only"
        return "answer_only"
    if looks_like_read_only_request(content):
        return "read_only_analysis"
    return "answer_only"


# ---------------------------------------------------------------------------
# Tool-call processing (value transforms plus explicit accumulator updates)
# ---------------------------------------------------------------------------

def merge_tool_call_chunks(
    calls: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> None:
    """Merge streaming tool-call chunks into the *calls* accumulator list."""
    for chunk in chunks:
        try:
            index = int(chunk.get("index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        while len(calls) <= index:
            calls.append({
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            })
        target = calls[index]
        if chunk.get("id"):
            target["id"] = chunk["id"]
        if chunk.get("type"):
            target["type"] = chunk["type"]
        function = chunk.get("function") or {}
        if function.get("name"):
            target["function"]["name"] = function["name"]
        if function.get("arguments"):
            target["function"]["arguments"] += function["arguments"]


def complete_tool_calls(
    calls: list[dict[str, Any]],
    round_index: int,
) -> list[dict[str, Any]]:
    """Finalize accumulated tool calls, dropping empty entries."""
    completed: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        function = call.get("function") or {}
        if not function.get("name"):
            continue
        completed.append({
            "id": call.get("id") or f"call_{round_index}_{index}",
            "type": call.get("type") or "function",
            "function": {
                "name": function["name"],
                "arguments": function.get("arguments") or "{}",
            },
        })
    return completed


def extract_native_tool_calls(text: str, round_index: int = 0) -> list[dict[str, Any]]:
    """Parse raw tool-call markers emitted as text by some local models.

    A few OpenAI-compatible local providers stream tool calls as special text
    blocks instead of structured ``tool_calls`` deltas, for example:

    ``<|FunctionCallBegin|>[{"name":"filesystem.read_file","parameters":{...}}]<|FunctionCallEnd|>``

    The runner can convert these blocks back into normal tool calls and remove
    the raw marker text from the user-visible stream.
    """
    calls: list[dict[str, Any]] = []
    for raw_block in native_tool_call_blocks(text):
        parsed = _parse_native_tool_call_block(raw_block)
        for item in parsed:
            call = _native_item_to_tool_call(item, round_index, len(calls))
            if call:
                calls.append(call)
    for item in xml_style_tool_call_blocks(text):
        call = _native_item_to_tool_call(item, round_index, len(calls))
        if call:
            calls.append(call)
    for item in tagged_tool_call_blocks(text):
        call = _native_item_to_tool_call(item, round_index, len(calls))
        if call:
            calls.append(call)
    return calls


def has_unresolved_tool_call_markup(text: str) -> bool:
    """Return whether model text contains tool-call markup that cannot execute."""
    lowered = str(text or "").lower()
    has_marker = (
        "<toolcall" in lowered
        or NATIVE_TOOL_CALL_BEGIN.lower() in lowered
        or "<mcreference" in lowered
        or bool(XML_TOOL_CALL_PATTERN.search(str(text or "")))
    )
    return bool(has_marker and not extract_native_tool_calls(text))


def strip_native_tool_call_blocks(text: str) -> str:
    """Remove raw local-model function-call blocks from display text."""
    text = strip_xml_style_tool_call_blocks(text)
    text = strip_tagged_tool_call_blocks(text)
    if NATIVE_TOOL_CALL_BEGIN not in text:
        return text
    result: list[str] = []
    cursor = 0
    while True:
        start = text.find(NATIVE_TOOL_CALL_BEGIN, cursor)
        if start < 0:
            result.append(text[cursor:])
            break
        result.append(text[cursor:start])
        end = text.find(NATIVE_TOOL_CALL_END, start + len(NATIVE_TOOL_CALL_BEGIN))
        if end < 0:
            break
        cursor = end + len(NATIVE_TOOL_CALL_END)
    return "".join(result)


def native_tool_call_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    cursor = 0
    while True:
        start = text.find(NATIVE_TOOL_CALL_BEGIN, cursor)
        if start < 0:
            break
        start += len(NATIVE_TOOL_CALL_BEGIN)
        end = text.find(NATIVE_TOOL_CALL_END, start)
        if end < 0:
            break
        block = text[start:end].strip()
        if block:
            blocks.append(block)
        cursor = end + len(NATIVE_TOOL_CALL_END)
    return blocks


def xml_style_tool_call_blocks(text: str) -> list[dict[str, Any]]:
    """Parse XML-like function calls emitted as assistant text by some models.

    Example:
    ``<filesystem.scan_folder><arg-key>path</arg-key><arg-value>.</arg-value></filesystem.scan_folder>``
    """
    calls: list[dict[str, Any]] = []
    for match in XML_TOOL_CALL_PATTERN.finditer(text):
        body = match.group("body")
        arguments: dict[str, Any] = {}
        for arg_match in XML_TOOL_ARG_PATTERN.finditer(body):
            key = _xml_tool_text(arg_match.group("key"))
            if not key:
                continue
            arguments[key] = _xml_tool_text(arg_match.group("value"))
        if arguments:
            calls.append({"name": match.group("name"), "parameters": arguments})
    return calls


def strip_xml_style_tool_call_blocks(text: str) -> str:
    return XML_TOOL_CALL_PATTERN.sub("", text)


def tagged_tool_call_blocks(text: str) -> list[dict[str, Any]]:
    """Parse ``<toolcall>{...}</toolcall>`` blocks emitted as assistant text."""
    calls: list[dict[str, Any]] = []
    for match in TAGGED_TOOL_CALL_PATTERN.finditer(text):
        block = _xml_tool_text(match.group("body"))
        parsed = _parse_native_tool_call_block(block)
        if parsed:
            calls.extend(parsed)
        elif (
            BARE_TOOL_NAME_PATTERN.fullmatch(block)
            and canonical_tool_id(block) in BARE_TAGGED_TOOL_CALL_IDS
        ):
            calls.append({"name": block, "parameters": {}})
    return calls


def strip_tagged_tool_call_blocks(text: str) -> str:
    if "<toolcall" not in text.lower():
        return text
    text = MCP_REFERENCE_TOOL_CALL_PATTERN.sub("", text)
    text = TAGGED_TOOL_CALL_PATTERN.sub("", text)
    dangling_start = text.lower().find("<toolcall")
    if dangling_start >= 0:
        text = text[:dangling_start]
    return text


def _xml_tool_text(value: str) -> str:
    return (
        value.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .strip()
    )


def _parse_native_tool_call_block(block: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(block)
    except json.JSONDecodeError:
        return []
    if isinstance(value, dict) and isinstance(value.get("tool_calls"), list):
        value = value["tool_calls"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _native_item_to_tool_call(
    item: dict[str, Any],
    round_index: int,
    index: int,
) -> dict[str, Any] | None:
    function = item.get("function")
    function = function if isinstance(function, dict) else {}
    name = (
        item.get("name")
        or item.get("tool")
        or item.get("tool_name")
        or function.get("name")
        or ""
    )
    name = str(name).strip()
    if not name:
        return None
    if "parameters" in item:
        arguments = item.get("parameters")
    elif "params" in item:
        arguments = item.get("params")
    elif "input" in item:
        arguments = item.get("input")
    else:
        arguments = item.get("arguments", function.get("arguments", {}))
    arguments = _normalize_native_tool_arguments(arguments)
    return {
        "id": item.get("id") or f"native_{round_index}_{index}",
        "type": item.get("type") or "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def _normalize_native_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = {}
    else:
        parsed = value
    if not isinstance(parsed, dict):
        return {}
    arguments = dict(parsed)
    if "path" not in arguments:
        for alias in ("file_path", "filepath", "dir_path", "folder_path"):
            if alias in arguments:
                arguments["path"] = arguments[alias]
                break
    return arguments


def tool_signature(tool_id: str, arguments: dict[str, Any]) -> str:
    """Produce a canonical JSON signature for deduplication."""
    tool_id = canonical_tool_id(tool_id)
    normalized: dict[str, Any]
    if tool_id == "code.search_text":
        normalized = {
            "path": arguments.get("path"),
            "query": arguments.get("query"),
            "include_extensions": arguments.get("include_extensions") or [],
        }
    elif tool_id in {"filesystem.read_file", "filesystem.read_text_preview"}:
        normalized = {
            "path": arguments.get("path"),
            "start_line": arguments.get("start_line"),
            "end_line": arguments.get("end_line"),
        }
    elif tool_id in {"filesystem.scan_folder", "code.list_project_files"}:
        normalized = {
            "path": arguments.get("path"),
            "include_extensions": arguments.get("include_extensions") or [],
        }
    else:
        normalized = arguments
    return json.dumps(
        {"tool": tool_id, "input": normalized},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def messages_for_model_round(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Sanitize conversation messages when tools are unavailable."""
    if tools:
        return messages
    sanitized: list[dict[str, Any]] = []
    for item in messages:
        role = str(item.get("role") or "")
        if role == "tool":
            name = str(item.get("name") or "tool")
            content = str(item.get("content") or "")
            sanitized.append({
                "role": "assistant",
                "content": f"工具结果摘要（{name}）：{content[:3000]}",
            })
            continue
        if role == "assistant" and item.get("tool_calls"):
            calls: list[str] = []
            for call in item.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                tool_name = str(function.get("name") or "tool")
                args = str(function.get("arguments") or "{}")
                calls.append(f"{tool_name}({args[:500]})")
            content = str(item.get("content") or "").strip()
            summary = "已调用工具：" + "；".join(calls[:8])
            sanitized.append({
                "role": "assistant",
                "content": (content + "\n" if content else "") + summary,
            })
            continue
        if role in {"system", "user", "assistant"}:
            sanitized.append({
                "role": role,
                "content": str(item.get("content") or ""),
            })
    return sanitized


def parse_tool_arguments_strict(text: str) -> tuple[dict[str, Any], str | None]:
    """Parse tool arguments without guessing or repairing incomplete JSON."""
    raw = str(text or "").strip() or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}, "malformed_tool_arguments"
    if not isinstance(value, dict):
        return {}, "non_object_tool_arguments"
    return value, None


def finish_reason_indicates_truncation(reason: Any) -> bool:
    """Return whether a provider says the model output stopped at a length limit."""
    return str(reason or "").strip().lower() in {
        "length",
        "max_tokens",
        "max_output_tokens",
    }


# ---------------------------------------------------------------------------
# Progress observation
# ---------------------------------------------------------------------------

def progress_key(tool_events: list[dict[str, Any]], mode: str | None) -> str:
    """Compute a stagnation-detection key from recent tool events."""
    significant: list[dict[str, Any]] = []
    for event in tool_events[-16:]:
        tool_id = str(event.get("tool") or "")
        status = str(event.get("status") or "")
        event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
        if status != "success":
            continue
        if (
            is_write_tool(tool_id)
            or is_verification_tool(tool_id, mode)
            or is_recon_tool(tool_id)
        ):
            significant.append({
                "tool": tool_id,
                "path": event_input.get("path") or event_input.get("output_path") or event_input.get("cwd") or "",
                "query": event_input.get("query") or event_input.get("old_text") or event_input.get("old_string") or "",
                "task_id": event.get("task_id") or "",
            })
    return json.dumps(significant, ensure_ascii=False, sort_keys=True)


def round_has_only_non_progress(round_events: list[dict[str, Any]]) -> bool:
    """Return True if every event in the round is non-successful (stalled)."""
    if not round_events:
        return False
    for event in round_events:
        if event.get("status") == "success":
            return False
    return True


def consecutive_repeated_failure_count(tool_events: list[dict[str, Any]]) -> int:
    """Count identical trailing failures so the runtime can stop empty retries."""
    signature = ""
    count = 0
    for event in reversed(tool_events):
        if event.get("status") != "failure":
            break
        event_signature = _tool_failure_signature(event)
        if not signature:
            signature = event_signature
        if event_signature != signature:
            break
        count += 1
    return count


def repeated_failure_action(
    tool_events: list[dict[str, Any]],
    *,
    strategy_change_intervened: bool,
) -> str:
    """Return the convergence action without adding another strategy prompt.

    Repeated identical failures usually mean the model is not producing a
    valid executable call.  Stop and record the real failure instead of asking
    the model to reinterpret the task through another soft strategy prompt.
    The ``strategy_change_intervened`` argument is kept for API compatibility.
    """
    count = consecutive_repeated_failure_count(tool_events)
    if count < 2:
        return "none"
    return "stop"


def _tool_failure_signature(event: dict[str, Any]) -> str:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    error = " ".join(str(event.get("error") or "").lower().split())
    return json.dumps(
        {
            "tool": canonical_tool_id(str(event.get("tool") or "")),
            "reason": str(output.get("reason") or "").strip().lower(),
            "error": error,
            "input": event_input,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def has_successful_write(tool_events: list[dict[str, Any]]) -> bool:
    return any(
        is_write_tool(str(event.get("tool") or "")) and event.get("status") == "success"
        for event in tool_events
    )


def has_successful_verification(tool_events: list[dict[str, Any]], mode: str | None) -> bool:
    verification_events, written_paths = _verification_scope_after_latest_write(tool_events)
    return any(
        is_meaningful_verification_event(event, mode, written_paths=written_paths)
        for event in verification_events
    )


def successful_verification_events(
    tool_events: list[dict[str, Any]],
    mode: str | None,
) -> list[dict[str, Any]]:
    """Return verification evidence, scoped after the latest successful write."""
    verification_events, written_paths = _verification_scope_after_latest_write(tool_events)
    return [
        event
        for event in verification_events
        if is_meaningful_verification_event(event, mode, written_paths=written_paths)
    ]


def _verification_scope_after_latest_write(
    tool_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    latest_write_index = -1
    written_paths: set[str] = set()
    for index, event in enumerate(tool_events):
        if not (
            is_write_tool(str(event.get("tool") or ""))
            and str(event.get("status") or "") in {"success", "partial"}
        ):
            continue
        latest_write_index = index
        written_paths.update(_event_path_hints(event))
    if latest_write_index < 0:
        return tool_events, written_paths
    return tool_events[latest_write_index + 1 :], written_paths


def is_meaningful_verification_event(
    event: dict[str, Any],
    mode: str | None,
    *,
    written_paths: set[str] | None = None,
) -> bool:
    """Return True when a successful tool call provides real verification.

    Directory listings and file-existence probes are useful evidence, but they
    should not satisfy a code-write verification contract by themselves.
    """
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if str(event.get("status") or "") != "success":
        return False
    if tool_id in {"filesystem.read_file", "filesystem.read_text_preview"}:
        path = _event_path_hint(event)
        output = event.get("output") if isinstance(event.get("output"), dict) else {}
        if tool_id == "filesystem.read_text_preview" and output.get("truncated") is True:
            return False
        integrity = output.get("integrity") if isinstance(output.get("integrity"), dict) else {}
        if integrity.get("checked") is True and integrity.get("valid") is not True:
            return False
        return bool(path and _path_matches_any(path, written_paths or set()))
    if not is_verification_tool(tool_id, mode):
        return False
    if tool_id == "shell.run_command":
        return _shell_command_verifies_behavior(event)
    if tool_id in {"filesystem.scan_folder", "code.list_project_files"}:
        return False
    if tool_id == "code.search_text":
        event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
        return bool(event_input.get("query"))
    if tool_id in {"git.status", "git.diff"}:
        return True
    return True


def is_test_verification_event(event: dict[str, Any]) -> bool:
    """Return True for successful commands that look like tests/build/checks."""
    if canonical_tool_id(str(event.get("tool") or "")) != "shell.run_command":
        return False
    if str(event.get("status") or "") != "success":
        return False
    return _shell_command_verifies_behavior(event, require_test_marker=True)


def _successful_written_path_hints(tool_events: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for event in tool_events:
        if not (
            is_write_tool(str(event.get("tool") or ""))
            and str(event.get("status") or "") == "success"
        ):
            continue
        paths.update(_event_path_hints(event))
    return paths


def _event_path_hint(event: dict[str, Any]) -> str:
    paths = _event_path_hints(event)
    return next(iter(paths), "")


def _event_path_hints(event: dict[str, Any]) -> set[str]:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    values = output.get("paths") if isinstance(output.get("paths"), list) else []
    paths = {
        _normalize_path_hint(value)
        for value in values
        if _normalize_path_hint(value)
    }
    if paths:
        return paths
    value = (
        output.get("path")
        or output.get("output_path")
        or event_input.get("output_path")
        or event_input.get("path")
        or ""
    )
    normalized = _normalize_path_hint(value)
    return {normalized} if normalized else set()


def _normalize_path_hint(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


def _path_matches_any(path: str, candidates: set[str]) -> bool:
    normalized = _normalize_path_hint(path)
    for candidate in candidates:
        other = _normalize_path_hint(candidate)
        if not other:
            continue
        if normalized == other:
            return True
        if normalized.endswith("/" + other) or other.endswith("/" + normalized):
            return True
    return False


def _shell_command_verifies_behavior(
    event: dict[str, Any],
    *,
    require_test_marker: bool = False,
) -> bool:
    event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    if is_long_running_service_command(event_input):
        return False
    if output.get("timed_out") is True:
        return False
    try:
        exit_code = int(output.get("exit_code", 0) or 0)
    except (TypeError, ValueError):
        exit_code = 0
    if exit_code != 0:
        return False
    command = str(event_input.get("command") or "").strip().lower()
    args = event_input.get("args") if isinstance(event_input.get("args"), list) else []
    arg_text = " ".join(str(item).lower() for item in args)
    combined = f"{command} {arg_text}".strip()
    if not combined:
        return False

    existence_markers = (
        "os.listdir",
        "get-childitem",
        "get-item",
        "test-path",
        " dir ",
        " ls ",
        " stat ",
    )
    padded = f" {combined} "
    if any(marker in padded for marker in existence_markers):
        return False
    if command in {"dir", "ls", "gci", "get-childitem", "get-item"}:
        return False

    test_markers = (
        "pytest",
        "unittest",
        "py_compile",
        "node --check",
        "npm test",
        "npm run test",
        "npm run build",
        "npm run lint",
        "pnpm test",
        "pnpm build",
        "yarn test",
        "yarn build",
        "cargo check",
        "cargo test",
        "go test",
        "tsc",
        "eslint",
        "ruff",
        "mypy",
        "javac",
        "dotnet test",
        "dotnet build",
        "mvn test",
        "gradle test",
    )
    has_test_marker = any(marker in combined for marker in test_markers)
    if require_test_marker:
        return has_test_marker
    return has_test_marker or command not in {"python", "python3", "py", "node", "npm", "pnpm", "yarn"}


def is_recoverable_write_failure(tool_id: str, event: dict[str, Any]) -> bool:
    if tool_id not in {"code.apply_patch", "code.edit_file", "code.replace_text", "filesystem.write_file"}:
        return False
    if event.get("status") == "success":
        return False
    error = str(event.get("error") or "").lower()
    return any(
        marker in error
        for marker in (
            "old_text not found",
            "old_text matches",
            "path not found",
            "no such file",
            "not found in file",
            "multiple matches",
        )
    )


# ---------------------------------------------------------------------------
# Stage management
# ---------------------------------------------------------------------------

def execution_stage_sequence(
    mode: str | None,
    code_change_intent: bool,
    task_intent: str = "",
) -> list[str]:
    profile = profile_for_task_intent(
        task_intent,
        mode,
        code_change_intent=code_change_intent,
    )
    return stage_sequence_for_profile(
        profile.id,
        task_intent=task_intent,
        code_change_intent=code_change_intent,
    )


def stage_round_limit(stage: str, mode: str | None, code_change_intent: bool) -> int:
    profile = profile_for_task_intent(
        "write_required" if code_change_intent else "",
        mode,
        code_change_intent=code_change_intent,
    )
    return round_limit_for_profile(
        profile.id,
        stage,
        code_change_intent=code_change_intent,
    )


def plan_has_pending_write_step(execution_plan: Any) -> bool:
    """Check if an execution plan still has a pending write-related step."""
    if not isinstance(execution_plan, dict):
        return False
    steps = execution_plan.get("steps")
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = step.get("status")
        if status not in {None, "pending", "running", "skipped"}:
            continue
        text = " ".join(
            str(step.get(key) or "").lower()
            for key in ("title", "description", "tool_hint")
        )
        if any(term in text for term in ("write", "edit", "replace", "create", "generate", "export")):
            return True
        if any(term in text for term in ("写", "修改", "编辑", "替换", "创建", "新增", "生成", "导出", "优化")):
            return True
    return False
