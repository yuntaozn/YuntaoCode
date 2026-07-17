from __future__ import annotations

from pathlib import Path
from typing import Any


SCRIPT_SUFFIXES = {".py", ".ps1", ".bat", ".cmd", ".js", ".mjs", ".ts", ".sh"}
TRANSLATION_SCRIPT_MARKERS = (
    "deep_translator",
    "googletranslator",
    "translate_to_chinese",
    "python-docx",
    "from docx import",
    "pip install",
)
PDF_TO_WORD_SCRIPT_MARKERS = (
    "pdf2docx",
    "pymupdf",
    "fitz.open",
    "from fitz import",
    "convert_pdf",
    "pdf_to_word",
)
PDF_TO_WORD_SHELL_TERMS = ("pdf2docx", "pymupdf", "fitz", "convert_pdf", "pdf_to_word")
TRANSLATION_SHELL_TERMS = (
    "pip",
    "python",
    "py ",
    "deep_translator",
    "googletranslator",
    "translate",
    ".py",
)


def document_contract_tool_guard_message(
    tool_id: str,
    arguments: dict[str, Any],
    task_contract: dict[str, Any] | None,
) -> str:
    """Return model-facing advisory evidence for document coverage risks.

    This guard is intentionally narrow. It does not choose a document strategy;
    it only explains that temporary scripts or shell workarounds may weaken
    coverage, resumability, progress, and verification evidence for
    full-document export contracts.
    """
    if not _requires_document_coverage(task_contract):
        return ""

    if tool_id == "filesystem.write_file":
        return _filesystem_write_guard_message(arguments)
    if tool_id == "shell.run_command":
        return _shell_guard_message(arguments)
    return ""


def _requires_document_coverage(task_contract: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(task_contract, dict)
        and task_contract.get("intent") == "document_export"
        and task_contract.get("expected_document_coverage")
    )


def _filesystem_write_guard_message(arguments: dict[str, Any]) -> str:
    target = str(
        arguments.get("path")
        or arguments.get("output_path")
        or arguments.get("file_path")
        or ""
    )
    suffix = Path(target).suffix.lower()
    content = str(arguments.get("content") or "")
    script_text = f"{target}\n{content}".lower()

    if suffix in SCRIPT_SUFFIXES and (
        any(marker in script_text for marker in PDF_TO_WORD_SCRIPT_MARKERS)
        or ("pdf" in script_text and any(term in script_text for term in ("docx", "word")))
    ):
        return (
            "文档覆盖证据：当前调用创建的是辅助脚本，不是目标文档本身。即使脚本写入成功，"
            "也不能证明全文覆盖、图文顺序、进度、恢复能力或目标文档验证已经完成。"
            "运行时不指定后续路线；请根据真实产物和工具结果自行判断下一步。"
        )
    if suffix in SCRIPT_SUFFIXES or any(marker in content.lower() for marker in TRANSLATION_SCRIPT_MARKERS):
        return (
            "文档覆盖证据：当前调用创建的是辅助脚本，不是目标文档本身。辅助脚本成功"
            "不等于全文处理、进度记录、断点恢复、覆盖率统计或目标文档验证已经完成。"
            "运行时不指定后续路线；请根据真实产物和工具结果自行判断下一步。"
        )
    return ""


def _shell_guard_message(arguments: dict[str, Any]) -> str:
    args = arguments.get("args") if isinstance(arguments.get("args"), list) else []
    command_text = " ".join(
        str(part)
        for part in [arguments.get("command"), *args]
        if part is not None
    ).lower()

    if any(term in command_text for term in PDF_TO_WORD_SHELL_TERMS) or (
        "pdf" in command_text and any(term in command_text for term in ("docx", "word"))
    ):
        return (
            "文档覆盖证据：当前 shell 调用本身不能证明目标文档已经完整产生。"
            "全文覆盖、图文顺序、进度、恢复能力和目标文档验证仍需由后续真实结果证明。"
            "运行时不指定后续路线；请根据工具结果自行判断下一步。"
        )
    if any(term in command_text for term in TRANSLATION_SHELL_TERMS):
        return (
            "文档覆盖证据：当前 shell 调用本身不能证明全文处理和目标文档已经完成。"
            "进度、断点恢复、覆盖率统计及目标产物验证仍需由后续真实结果证明。"
            "运行时不指定后续路线；请根据工具结果自行判断下一步。"
        )
    return ""
