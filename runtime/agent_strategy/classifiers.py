"""Strategy helpers extracted from ConversationMessagesStreamHandler.

Functions in this module have no ``self`` dependency and perform no I/O.
Most are pure value transforms; functions such as ``merge_tool_call_chunks``
intentionally update caller-provided accumulators in place.
They can be tested in isolation without a Tornado handler or runtime context.
"""

from __future__ import annotations

import json
from typing import Any

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
    "document.generate_docx_from_outline",
    "document.export_pdf",
    "document.generate_ppt",
    "document.merge_pdfs",
    "document.split_pdf",
    "document.create_bookmark_outline",
})

WRITE_TOOL_IDS: frozenset[str] = frozenset({
    "code.edit_file",
    "code.replace_text",
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

TOOL_ID_ALIASES: dict[str, str] = {
    "code.search": "code.search_text",
    "code.find": "code.search_text",
    "code.grep": "code.search_text",
    "code.list_files": "code.list_project_files",
    "code.list_project": "code.list_project_files",
    "filesystem.list_dir": "filesystem.scan_folder",
    "filesystem.list_directory": "filesystem.scan_folder",
    "filesystem.listdir": "filesystem.scan_folder",
    "filesystem.scan": "filesystem.scan_folder",
    "filesystem.read": "filesystem.read_file",
    "filesystem.read_text": "filesystem.read_file",
    "filesystem.write": "filesystem.write_file",
    "shell.execute": "shell.run_command",
    "shell.run": "shell.run_command",
    "git.show_diff": "git.diff",
}

POST_WRITE_READ_TOOL_IDS: frozenset[str] = frozenset({
    "filesystem.read_file",
    "filesystem.read_text_preview",
    "filesystem.scan_folder",
})

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
    tool_id = str(value or "").strip().replace("__", ".")
    return TOOL_ID_ALIASES.get(tool_id, tool_id)


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
    export_terms = (
        "导出", "生成word", "生成 word", "生成docx", "生成 docx",
        "生成pdf", "生成 pdf", "生成ppt", "生成 ppt",
        "保存为", "写成文件", "输出文件",
        ".docx", ".pdf", ".pptx", ".md",
    )
    return any(term in text for term in export_terms)


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
        "按这个改", "就这样改", "继续改", "继续做",
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
    return calls


def strip_native_tool_call_blocks(text: str) -> str:
    """Remove raw local-model function-call blocks from display text."""
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
    arguments = (
        item.get("parameters")
        if "parameters" in item
        else item.get("arguments", function.get("arguments", {}))
    )
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


def try_fix_json(text: str) -> dict[str, Any]:
    """Attempt to repair truncated or malformed JSON from model tool calls."""
    text = text.strip()
    if not text:
        return {}
    # Try closing unclosed braces/brackets
    opens = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    fixed = text
    if open_brackets > 0:
        fixed += "]" * open_brackets
    if opens > 0:
        fixed += "}" * opens
    try:
        result = json.loads(fixed)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, ValueError):
        pass
    # Try adding a closing quote if string is unclosed
    if fixed.count('"') % 2 != 0:
        fixed += '"'
        if open_brackets > 0:
            fixed += "]" * open_brackets
        if opens > 0:
            fixed += "}" * opens
        try:
            result = json.loads(fixed)
            return result if isinstance(result, dict) else {}
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


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


def has_successful_write(tool_events: list[dict[str, Any]]) -> bool:
    return any(
        is_write_tool(str(event.get("tool") or "")) and event.get("status") == "success"
        for event in tool_events
    )


def has_successful_verification(tool_events: list[dict[str, Any]], mode: str | None) -> bool:
    return any(
        is_verification_tool(str(event.get("tool") or ""), mode) and event.get("status") == "success"
        for event in tool_events
    )


def is_recoverable_write_failure(tool_id: str, event: dict[str, Any]) -> bool:
    if tool_id not in {"code.edit_file", "code.replace_text", "filesystem.write_file"}:
        return False
    if event.get("status") == "success":
        return False
    error = str(event.get("error") or "").lower()
    return any(
        marker in error
        for marker in (
            "old_text not found",
            "old_text matches",
            "path is required",
            "content is required",
            "missing required",
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
