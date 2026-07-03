from __future__ import annotations

import re
from typing import Any


TOOL_ID_ALIASES: dict[str, str] = {
    "code.find": "code.search_text",
    "code.find_text": "code.search_text",
    "code.grep": "code.search_text",
    "code.search": "code.search_text",
    "code.search_code": "code.search_text",
    "code.search_files": "code.search_text",
    "code.list_files": "code.list_project_files",
    "code.list_project": "code.list_project_files",
    "code.project_files": "code.list_project_files",
    "code.replace": "code.replace_text",
    "code.edit": "code.edit_file",
    "code.patch": "code.apply_patch",
    "document.docx_outline": "document.extract_docx_outline",
    "document.extract_docx": "document.extract_docx_outline",
    "document.extract_word": "document.extract_docx_outline",
    "document.read_docx": "document.extract_docx_outline",
    "document.read_word": "document.extract_docx_outline",
    "document.extract_pdf": "document.extract_pdf_text_preview",
    "document.extract_pdf_text": "document.extract_pdf_text_preview",
    "document.extract_pdf_to_word": "document.extract_pdf_to_docx",
    "document.pdf_extract": "document.extract_pdf_text_preview",
    "document.pdf_extract_text": "document.extract_pdf_text_preview",
    "document.pdf_text": "document.extract_pdf_text_preview",
    "document.pdf_to_docx": "document.extract_pdf_to_docx",
    "document.pdf_to_word": "document.extract_pdf_to_docx",
    "document.read_pdf": "document.extract_pdf_text_preview",
    "document.extract_excel": "spreadsheet.inspect_workbook",
    "document.read_excel": "spreadsheet.inspect_workbook",
    "document.read_xlsx": "spreadsheet.inspect_workbook",
    "document.convert_pdf_to_docx": "document.extract_pdf_to_docx",
    "document.convert_pdf_to_word": "document.extract_pdf_to_docx",
    "document.translate_word": "document.translate_docx",
    "document.translate_document": "document.translate_docx",
    "document.translate_to_chinese": "document.translate_docx",
    "document.docx_translate": "document.translate_docx",
    "document.export_md": "document.export_markdown",
    "document.markdown_export": "document.export_markdown",
    "document.export_word": "document.export_docx",
    "document.create_docx": "document.generate_docx_from_outline",
    "document.generate_docx": "document.generate_docx_from_outline",
    "document.generate_powerpoint": "document.generate_ppt",
    "document.create_ppt": "document.generate_ppt",
    "document.export_ppt": "document.generate_ppt",
    "document.merge_pdf": "document.merge_pdfs",
    "document.pdf_merge": "document.merge_pdfs",
    "document.split_pdfs": "document.split_pdf",
    "document.pdf_split": "document.split_pdf",
    "document.bookmark_outline": "document.create_bookmark_outline",
    "document.create_pdf_bookmarks": "document.create_bookmark_outline",
    "filesystem.list": "filesystem.scan_folder",
    "filesystem.list_dir": "filesystem.scan_folder",
    "filesystem.list_directory": "filesystem.scan_folder",
    "filesystem.list_files": "filesystem.scan_folder",
    "filesystem.list_project_files": "code.list_project_files",
    "filesystem.listdir": "filesystem.scan_folder",
    "filesystem.ls": "filesystem.scan_folder",
    "filesystem.scan": "filesystem.scan_folder",
    "filesystem.read": "filesystem.read_file",
    "filesystem.read_text": "filesystem.read_file",
    "filesystem.preview": "filesystem.read_text_preview",
    "filesystem.preview_text": "filesystem.read_text_preview",
    "filesystem.read_preview": "filesystem.read_text_preview",
    "filesystem.write": "filesystem.write_file",
    "filesystem.write_text": "filesystem.write_file",
    "filesystem.apply": "filesystem.apply_changes",
    "filesystem.apply_change_set": "filesystem.apply_changes",
    "filesystem.apply_changeset": "filesystem.apply_changes",
    "filesystem.change_set": "filesystem.apply_changes",
    "filesystem.write_changes": "filesystem.apply_changes",
    "filesystem.copy": "filesystem.copy_file",
    "filesystem.copy_asset": "filesystem.copy_file",
    "filesystem.copy_file_to": "filesystem.copy_file",
    "filesystem.cp": "filesystem.copy_file",
    "filesystem.delete": "filesystem.delete_file",
    "filesystem.delete_text": "filesystem.delete_file",
    "filesystem.remove": "filesystem.delete_file",
    "filesystem.remove_file": "filesystem.delete_file",
    "filesystem.unlink": "filesystem.delete_file",
    "filesystem.write_temp": "filesystem.write_temp_file",
    "filesystem.write_temporary_file": "filesystem.write_temp_file",
    "filesystem.create_temp_file": "filesystem.write_temp_file",
    "filesystem.temp_write": "filesystem.write_temp_file",
    "git.get_status": "git.status",
    "git.show_status": "git.status",
    "git.get_diff": "git.diff",
    "git.show_diff": "git.diff",
    "git.history": "git.log",
    "git.show_log": "git.log",
    "git.commit_changes": "git.commit",
    "memory.remember": "memory.save",
    "memory.search": "memory.recall",
    "memory.retrieve": "memory.recall",
    "shell.command": "shell.run_command",
    "shell.exec": "shell.run_command",
    "shell.execute": "shell.run_command",
    "shell.run": "shell.run_command",
    "spreadsheet.inspect": "spreadsheet.inspect_workbook",
    "spreadsheet.read": "spreadsheet.inspect_workbook",
    "spreadsheet.read_excel": "spreadsheet.inspect_workbook",
    "spreadsheet.read_workbook": "spreadsheet.inspect_workbook",
    "spreadsheet.preview": "spreadsheet.inspect_workbook",
    "web.fetch": "web.fetch_url",
    "web.get_url": "web.fetch_url",
    "web.read_url": "web.extract_text",
    "web.scrape": "web.extract_text",
    "web.render": "web.render_page",
    "preview.screenshot": "preview.capture_url",
    "preview.capture_page": "preview.capture_url",
    "preview.capture_pdf": "preview.capture_file",
    "preview.capture_image": "preview.capture_file",
    "preview.capture_file_preview": "preview.capture_file",
    "preview.file": "preview.capture_file",
    "preview.file_preview": "preview.capture_file",
    "preview.capture_html": "preview.capture_local_html",
    "preview.browser_interaction": "preview.interact_page",
    "preview.interact": "preview.interact_page",
    "preview.local_html": "preview.capture_local_html",
    "preview.run_actions": "preview.interact_page",
    "preview.screenshot_html": "preview.capture_local_html",
    "preview.verify_ui": "preview.interact_page",
}


_TOOL_ID_PREFIX_PATTERN = re.compile(r"^[A-Za-z][\w]*(?:[._][\w]+)+")


def normalize_tool_syntax(value: Any) -> str:
    tool_id = str(value or "").strip().replace("__", ".")
    return _strip_markup_suffix(tool_id)


def normalize_tool_id(value: Any) -> str:
    tool_id = normalize_tool_syntax(value)
    return TOOL_ID_ALIASES.get(tool_id, tool_id)


def _strip_markup_suffix(value: str) -> str:
    """Recover a tool id when model-side XML fragments leak into the name.

    Some local/OpenAI-compatible providers can stream malformed tool calls where
    XML-ish parameter text is appended to the function name, for example
    ``filesystem.read_file</parameter><parameter ...``.  Keep only a syntactic
    tool-id prefix and let ToolRegistry decide whether it is actually known.
    """
    if "<" not in value:
        return value
    match = _TOOL_ID_PREFIX_PATTERN.match(value)
    if not match:
        return value
    prefix = match.group(0)
    if value[len(prefix):].lstrip().startswith("<"):
        return prefix
    return value
