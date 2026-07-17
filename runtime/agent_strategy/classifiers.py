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

from .tool_result_risks import shell_success_has_stderr_warning


# ---------------------------------------------------------------------------
# Tool-ID constants
# ---------------------------------------------------------------------------

DOCUMENT_WRITE_TOOL_IDS: frozenset[str] = frozenset({
    "document.export_markdown",
    "document.export_docx",
    "document.export_draft_docx",
    "document.extract_pdf_to_docx",
    "document.translate_docx",
    "document.generate_docx_from_outline",
    "document.export_pdf",
    "document.generate_ppt",
    "document.merge_pdfs",
    "document.split_pdf",
    "document.create_bookmark_outline",
})

WEB_WRITE_TOOL_IDS: frozenset[str] = frozenset({
    "web.collect_site_assets",
    "web.capture_page",
})

WRITE_TOOL_IDS: frozenset[str] = frozenset({
    "code.apply_patch",
    "code.edit_file",
    "code.replace_text",
    "filesystem.apply_changes",
    "filesystem.copy_file",
    "filesystem.transform_text",
    "filesystem.write_file",
    "filesystem.delete_file",
    "filesystem.finalize_text_file",
    *DOCUMENT_WRITE_TOOL_IDS,
    *WEB_WRITE_TOOL_IDS,
})

DELIVERABLE_VERIFICATION_TOOL_IDS: frozenset[str] = frozenset({
    "shell.run_command",
    "git.status",
    "git.diff",
    "code.search_text",
    "code.list_project_files",
    "git.log",
    "spreadsheet.inspect_workbook",
    "web.capture_page",
    "preview.capture_url",
    "preview.capture_local_html",
    "preview.capture_file",
    "preview.interact_page",
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

DELIVERABLE_READ_TOOL_IDS: frozenset[str] = frozenset({
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
    "document.inspect_draft",
    "spreadsheet.inspect_workbook",
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
        "spreadsheet.inspect_workbook",
        "code.search_text",
        "code.list_project_files",
    }
    if mode in {"coding", "terminal"}:
        base |= {"git.status", "git.log"}
    return base


def verification_tool_ids(mode: str | None) -> set[str]:
    """Return the set of tool IDs that count as verification."""
    ids: set[str] = set(DELIVERABLE_VERIFICATION_TOOL_IDS)
    if mode in {"document", "paper"}:
        ids |= {
            "filesystem.scan_folder",
            "filesystem.read_file",
            "filesystem.read_text_preview",
            "document.extract_docx_outline",
            "document.extract_pdf_text_preview",
            "spreadsheet.inspect_workbook",
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


def looks_like_diagnostic_feedback(content: str) -> bool:
    """Return whether the user pasted runtime evidence from a recent task.

    This does not decide that a repair is required. It only tells the context
    layer that the message is likely evidence about something that just ran, so
    the model-side task contract should see the previous task anchor.
    """
    text = str(content or "").strip().lower()
    if len(text) < 8:
        return False
    direct_markers = (
        "traceback (most recent call last)",
        "uncaught ",
        "typeerror",
        "referenceerror",
        "syntaxerror",
        "module not found",
        "modulenotfounderror",
        "importerror",
        "valueerror",
        "keyerror",
        "attributeerror",
        "winerror",
        "failed to load resource",
        "method not allowed",
        "unexpected end of json",
        "cannot set properties of null",
        "cannot read properties of null",
        "command exited with code",
        "failed to execute command",
        "tool call failed",
        "unknown tool",
        "missing required argument",
        "工具调用缺少必填参数",
        "失败原因",
    )
    if any(marker in text for marker in direct_markers):
        return True
    broad_failure_terms = ("调用失败", "执行失败", "报错", "错误", "异常")
    structural_failure_hints = (
        "traceback",
        "failed",
        "error:",
        "exception",
        "winerror",
        "失败原因",
    )
    if any(term in text for term in broad_failure_terms) and any(
        hint in text for hint in structural_failure_hints
    ):
        return True
    if re.search(r"\bat\s+[\w./\\-]+\.(?:js|ts|tsx|jsx|py|html|css):\d+(?::\d+)?", text):
        return True
    if re.search(r"\b(?:4\d\d|5\d\d)\b.*(?:error|failed|not found|method not allowed|server)", text):
        return True
    if re.search(r"(?:error|exception|failed).*?(?:line\s+\d+|\.js:\d+|\.py:\d+|\b4\d\d\b|\b5\d\d\b)", text, re.DOTALL):
        return True
    return False


def plan_has_pending_write_step(execution_plan: Any) -> bool:
    """Check whether a plan explicitly contains a pending local write step.

    Contract promotion should follow concrete execution evidence: either a
    known write tool or an explicit file-writing phrase. Broad task words such
    as "generate" are not enough because analysis tasks may also generate an
    answer without changing local state.
    """
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
        tool_hint = str(step.get("tool_hint") or "").lower().replace("__", ".")
        for candidate in BARE_TOOL_NAME_PATTERN.findall(tool_hint):
            if is_write_tool(candidate):
                return True
        text = " ".join(
            str(step.get(key) or "").lower()
            for key in ("title", "description", "tool_hint")
        )
        if any(
            term in text
            for term in (
                "write file",
                "write to",
                "edit file",
                "replace text",
                "create file",
                "generate file",
                "export file",
                "save file",
                "overwrite",
                "modify file",
            )
        ):
            return True
        if any(
            term in text
            for term in (
                "\u5199\u5165",
                "\u5199\u51fa",
                "\u8986\u76d6",
                "\u66ff\u6362",
                "\u7f16\u8f91\u6587\u4ef6",
                "\u4fee\u6539\u6587\u4ef6",
                "\u65b0\u5efa\u6587\u4ef6",
                "\u521b\u5efa\u6587\u4ef6",
                "\u751f\u6210\u6587\u4ef6",
                "\u5bfc\u51fa\u6587\u4ef6",
                "\u4fdd\u5b58\u4e3a",
            )
        ):
            return True
    return False


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


def tool_call_arguments_size(calls: list[dict[str, Any]]) -> int:
    """Return the total streamed argument size for accumulated tool calls."""
    total = 0
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else {}
        if not isinstance(function, dict):
            continue
        total += len(str(function.get("arguments") or ""))
    return total


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


def failure_route_attempt_count_since_progress(tool_events: list[dict[str, Any]]) -> int:
    """Count same failed execution route attempts since the last real progress.

    This is intentionally route-oriented instead of turn-oriented.  A model may
    try a different route after a failure; if that route produces a successful
    tool event, the self-correction budget should reset.  If it only alternates
    between failures and eventually returns to the same failed tool+arguments,
    the route is still being repeated without progress.
    """
    latest = tool_events[-1] if tool_events else {}
    if latest.get("status") != "failure":
        return 0
    target_signature = _tool_failure_signature(latest)
    count = 0
    is_latest = True
    for event in reversed(tool_events):
        if not is_latest and _is_progress_event(event):
            break
        is_latest = False
        if event.get("status") != "failure":
            continue
        if _tool_failure_signature(event) == target_signature:
            count += 1
    return count


def repeated_failure_action(
    tool_events: list[dict[str, Any]],
) -> str:
    """Return the convergence action for repeated failed execution routes.

    The first repeated route is evidence that the current route is not working,
    not proof that the task should stop.  Give the model a wider bounded
    self-correction budget in the current no-progress window, then stop only if
    it keeps returning to the same failed route without producing new evidence.
    """
    route_attempts = failure_route_attempt_count_since_progress(tool_events)
    if route_attempts < 2:
        return "none"
    if route_attempts >= 7:
        return "stop"
    return "report_repetition"


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


def _is_progress_event(event: dict[str, Any]) -> bool:
    return str(event.get("status") or "") in {"success", "partial"}


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


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _artifact_write_has_verification_facts(
    event: dict[str, Any],
    *,
    written_paths: set[str],
) -> bool:
    tool_id = canonical_tool_id(str(event.get("tool") or ""))
    if not is_write_tool(tool_id):
        return False
    path = _event_path_hint(event)
    if not path or (written_paths and not _path_matches_any(path, written_paths)):
        return False
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    draft_stats = output.get("draft_stats") if isinstance(output.get("draft_stats"), dict) else {}
    integrity = output.get("integrity") if isinstance(output.get("integrity"), dict) else {}
    validation = output.get("validation") if isinstance(output.get("validation"), dict) else {}
    if validation.get("valid") is True:
        return True
    if integrity.get("checked") is True:
        return integrity.get("valid") is True
    file_size = max(_nonnegative_int(output.get("file_size")), _nonnegative_int(output.get("size")))
    content_measure = max(
        _nonnegative_int(output.get("content_chars")),
        _nonnegative_int(output.get("text_chars")),
        _nonnegative_int(output.get("paragraph_count")),
        _nonnegative_int(output.get("nonempty_paragraph_count")),
        _nonnegative_int(draft_stats.get("text_chars")),
        _nonnegative_int(draft_stats.get("block_count")),
    )
    if tool_id.startswith("document.") and content_measure > 0:
        return True
    return file_size > 0 and content_measure > 0


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
    return tool_events[latest_write_index:], written_paths


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
    if _artifact_write_has_verification_facts(event, written_paths=written_paths or set()):
        return True
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
    """Return True for successful commands that exercise behavior.

    Syntax-only and static checks such as ``python -m py_compile`` or
    ``node --check`` are meaningful verification evidence, but they are
    structural checks. They should not satisfy task contracts that explicitly
    require behavioral verification, such as generated web/API services.
    """
    if canonical_tool_id(str(event.get("tool") or "")) != "shell.run_command":
        return False
    if str(event.get("status") or "") != "success":
        return False
    return _shell_command_verifies_behavior(
        event,
        require_test_marker=True,
        structural_checks_are_tests=False,
    )


def is_structural_verification_event(event: dict[str, Any]) -> bool:
    """Return True for successful syntax, type, lint, or build checks."""
    if canonical_tool_id(str(event.get("tool") or "")) != "shell.run_command":
        return False
    if str(event.get("status") or "") != "success":
        return False
    return _shell_command_has_structural_check_marker(event)


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
    structural_checks_are_tests: bool = True,
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
    if shell_success_has_stderr_warning(output):
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

    behavioral_markers = (
        "pytest",
        "unittest",
        "npm test",
        "npm run test",
        "pnpm test",
        "yarn test",
        "cargo test",
        "go test",
        "dotnet test",
        "mvn test",
        "gradle test",
        "curl ",
        "invoke-webrequest",
        "invoke-restmethod",
        "requests.get",
        "httpx.get",
        "urllib.request",
        "testclient",
    )
    has_test_marker = any(marker in combined for marker in behavioral_markers)
    if structural_checks_are_tests:
        has_test_marker = has_test_marker or _shell_command_has_structural_check_marker(event)
    if require_test_marker:
        return has_test_marker
    return has_test_marker or command not in {"python", "python3", "py", "node", "npm", "pnpm", "yarn"}


def _shell_command_has_structural_check_marker(event: dict[str, Any]) -> bool:
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
    if shell_success_has_stderr_warning(output):
        return False
    command = str(event_input.get("command") or "").strip().lower()
    args = event_input.get("args") if isinstance(event_input.get("args"), list) else []
    arg_text = " ".join(str(item).lower() for item in args)
    combined = f"{command} {arg_text}".strip()
    if not combined:
        return False
    structural_markers = (
        "py_compile",
        "compileall",
        "node --check",
        "npm run build",
        "npm run lint",
        "pnpm build",
        "yarn build",
        "cargo check",
        "tsc",
        "eslint",
        "ruff",
        "mypy",
        "javac",
        "dotnet build",
        "mvn package",
        "gradle build",
    )
    return any(marker in combined for marker in structural_markers)


def is_recoverable_write_failure(tool_id: str, event: dict[str, Any]) -> bool:
    if tool_id not in {
        "code.apply_patch",
        "code.edit_file",
        "code.replace_text",
        "filesystem.write_file",
        "filesystem.create_text_draft",
        "filesystem.append_text_chunk",
        "filesystem.finalize_text_file",
    }:
        return False
    if event.get("status") == "success":
        return False
    error = str(event.get("error") or "").lower()
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    reason = str(output.get("reason") or "").lower()
    if reason == "truncated_tool_call":
        return True
    if (
        "output limit" in error
        or "stopped at its output limit" in error
        or "incomplete arguments" in error
        or "truncated_tool_call" in error
    ):
        return True
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
