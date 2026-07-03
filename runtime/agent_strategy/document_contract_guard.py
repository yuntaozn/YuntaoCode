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
            "文档覆盖率提示：当前任务像 PDF 转 Word / 图文文档输出，临时脚本可能导致"
            "覆盖率、图片顺序、断点恢复、进度和验证证据不足。优先考虑 "
            "document.extract_pdf_to_docx；如果用户要求图片和文字顺序保留，可使用 "
            "mode=text_with_images。若仍选择脚本路线，请确保产物、覆盖率和验证证据真实可观察。"
        )
    if suffix in SCRIPT_SUFFIXES or any(marker in content.lower() for marker in TRANSLATION_SCRIPT_MARKERS):
        return (
            "文档覆盖率提示：当前任务像全文文档输出/翻译，临时脚本可能绕开文档工具的"
            "进度、断点恢复、覆盖率统计和完成验证。优先考虑 document.translate_docx；"
            "如果源文件是 PDF 转 Word，可考虑 document.extract_pdf_to_docx。"
            "若仍选择脚本路线，请基于真实产物和验证证据判断是否完成。"
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
            "文档覆盖率提示：当前任务像 PDF 转 Word / 图文文档输出，shell 或脚本路线可能"
            "缺少覆盖率、图片顺序、断点恢复、进度和验证证据。优先考虑 "
            "document.extract_pdf_to_docx；如果用户要求图片和文字顺序保留，可使用 "
            "mode=text_with_images。若仍选择 shell 路线，请确保目标产物和验证证据真实可观察。"
        )
    if any(term in command_text for term in TRANSLATION_SHELL_TERMS):
        return (
            "文档覆盖率提示：当前任务像全文文档输出/翻译，shell 或脚本路线可能绕开"
            "文档工具的进度、断点恢复、覆盖率统计和完成验证。优先考虑 "
            "document.translate_docx。若仍选择 shell 路线，请基于真实产物和验证证据"
            "判断是否完成。"
        )
    return ""
