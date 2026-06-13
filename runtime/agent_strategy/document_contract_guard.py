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
    """Return a model-facing correction when a document contract is bypassed.

    This guard is intentionally narrow. It does not choose a document strategy;
    it only prevents a full-document export contract from silently becoming a
    temporary script or shell workaround.
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
            "当前任务是 PDF 转 Word / 图文文档输出，不能通过临时脚本绕过内置文档工具。"
            "请直接调用 document.extract_pdf_to_docx；如果用户要求图片和文字顺序保留，请传入 mode=text_with_images。"
        )
    if suffix in SCRIPT_SUFFIXES or any(marker in content.lower() for marker in TRANSLATION_SCRIPT_MARKERS):
        return (
            "当前任务是全文文档输出/翻译，不能通过临时脚本实现。"
            "请直接调用 document.translate_docx；如果源文件是 PDF 转 Word，请调用 document.extract_pdf_to_docx。"
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
            "当前任务是 PDF 转 Word / 图文文档输出，不能用 shell 或脚本绕过内置文档工具。"
            "请直接调用 document.extract_pdf_to_docx；如果用户要求图片和文字顺序保留，请传入 mode=text_with_images。"
        )
    if any(term in command_text for term in TRANSLATION_SHELL_TERMS):
        return (
            "当前任务是全文文档输出/翻译，不能用 shell 或脚本绕过内置文档工具。"
            "请直接调用 document.translate_docx，并让工具负责覆盖率与完成状态。"
        )
    return ""
