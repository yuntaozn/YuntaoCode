from __future__ import annotations

import json
from typing import Any

from runtime.debug_session import debug_session_summary, normalize_debug_session
from runtime.visual_evidence import normalize_visual_evidence, visual_evidence_summary


def tool_progress_snapshot(tool_id: str, task: Any) -> dict[str, Any]:
    logs = task.logs if getattr(task, "logs", None) else []
    snapshot: dict[str, Any] = {
        "tool": tool_id,
        "task_id": getattr(task, "id", ""),
        "status": getattr(task, "status", ""),
    }
    if logs:
        latest = logs[-1]
        snapshot["last_log_message"] = latest.get("message")
        snapshot["last_log_level"] = latest.get("level")
        snapshot["last_log_time"] = latest.get("time")

    if tool_id == "document.translate_docx":
        for log_event in reversed(logs):
            message = str(log_event.get("message") or "")
            if not (
                message.startswith("translation progress ")
                or message.startswith("translation batch started ")
                or message.startswith("translation source loaded ")
            ):
                continue
            raw_progress = message.rsplit(" ", 1)[-1]
            if "/" not in raw_progress:
                continue
            done_text, total_text = raw_progress.split("/", 1)
            try:
                done = int(done_text)
                total = int(total_text)
            except ValueError:
                continue
            data = log_event.get("data") if isinstance(log_event.get("data"), dict) else {}
            phase = "progress"
            if message.startswith("translation batch started "):
                phase = "batch_started"
            elif message.startswith("translation source loaded "):
                phase = "source_loaded"
            snapshot.update({
                "kind": "document_translation",
                "phase": phase,
                "done": done,
                "total": total,
                "percent": round((done / total) * 100, 1) if total else 0,
                "translated": data.get("translated"),
                "failed": data.get("failed"),
                "source_chars_done": data.get("source_chars_done"),
                "source_chars_total": data.get("source_chars_total"),
                "engine": data.get("engine"),
                "translation_profile": data.get("translation_profile"),
                "manifest_path": data.get("manifest_path"),
                "resumable": data.get("resumable"),
            })
            break
    elif tool_id == "document.extract_pdf_to_docx":
        for log_event in reversed(logs):
            message = str(log_event.get("message") or "")
            if not (
                message.startswith("pdf conversion started ")
                or message.startswith("pdf page converted ")
                or message.startswith("pdf docx saving ")
                or message.startswith("pdf docx saved ")
            ):
                continue
            raw_progress = message.rsplit(" ", 1)[-1]
            if "/" not in raw_progress:
                continue
            done_text, total_text = raw_progress.split("/", 1)
            try:
                done = int(done_text)
                total = int(total_text)
            except ValueError:
                continue
            data = log_event.get("data") if isinstance(log_event.get("data"), dict) else {}
            phase = str(data.get("phase") or "progress")
            if message.startswith("pdf conversion started "):
                phase = "started"
            elif message.startswith("pdf docx saving "):
                phase = "saving"
            elif message.startswith("pdf docx saved "):
                phase = "saved"
            snapshot.update({
                "kind": "pdf_to_docx",
                "phase": phase,
                "done": done,
                "total": total,
                "percent": round((done / total) * 100, 1) if total else 0,
                "source_pages": data.get("source_pages"),
                "text_block_count": data.get("text_block_count"),
                "image_count": data.get("image_count"),
                "skipped_image_count": data.get("skipped_image_count"),
                "mode": data.get("mode"),
                "file_size": data.get("file_size"),
            })
            break
    return snapshot


def tool_progress_message(
    tool_id: str,
    task: Any,
    elapsed_seconds: int,
    stale_seconds: int,
    progress: dict[str, Any],
    *,
    display_name: str,
) -> str:
    del tool_id, task
    name = display_name
    if progress.get("kind") == "document_translation":
        phase = str(progress.get("phase") or "progress")
        if phase == "source_loaded":
            lead = f"{name}仍在运行：已读取源文档，等待第一批翻译"
        elif phase == "batch_started":
            lead = f"{name}仍在运行：正在翻译下一批，已完成 {progress.get('done')}/{progress.get('total')} 段"
        else:
            lead = f"{name}仍在运行：已处理 {progress.get('done')}/{progress.get('total')} 段"
        parts = [
            lead,
            f"{progress.get('percent')}%",
            f"失败 {progress.get('failed') or 0} 段",
            f"已等待 {elapsed_seconds}s",
        ]
        source_done = progress.get("source_chars_done")
        source_total = progress.get("source_chars_total")
        if isinstance(source_done, int) and isinstance(source_total, int) and source_total > 0:
            char_percent = round((source_done / source_total) * 100, 1)
            parts.insert(2, f"字符进度 {char_percent}%")
        if stale_seconds >= 60:
            parts.append(f"最近 {stale_seconds}s 没有新进度，可能正在等待模型响应")
        return "；".join(parts)

    if progress.get("kind") == "pdf_to_docx":
        phase = str(progress.get("phase") or "progress")
        done = progress.get("done")
        total = progress.get("total")
        if phase == "started":
            lead = f"{name}仍在运行：已开始解析 PDF，等待第一页结果"
        elif phase == "saving":
            lead = f"{name}仍在运行：正在保存 Word 文件，已处理 {done}/{total} 页"
        elif phase == "saved":
            lead = f"{name}仍在运行：Word 文件已保存，正在收束结果"
        else:
            lead = f"{name}仍在运行：已处理 {done}/{total} 页"
        parts = [
            lead,
            f"{progress.get('percent')}%",
            f"文字块 {progress.get('text_block_count') or 0}",
            f"图片 {progress.get('image_count') or 0}",
            f"已等待 {elapsed_seconds}s",
        ]
        skipped = progress.get("skipped_image_count")
        if isinstance(skipped, int) and skipped > 0:
            parts.insert(4, f"跳过图片 {skipped}")
        if stale_seconds >= 60:
            parts.append(f"最近 {stale_seconds}s 没有新页面进度，可能正在处理大图片或保存文件")
        return "；".join(parts)

    last_log = str(progress.get("last_log_message") or "").strip()
    if last_log:
        return f"{name}仍在运行：{last_log}；已等待 {elapsed_seconds}s"
    return f"{name}仍在运行，已等待 {elapsed_seconds}s"


def tool_output_preview(tool_id: str, output: Any) -> dict[str, Any] | None:
    """Extract a small preview of tool output for frontend rich rendering."""
    if not output or not isinstance(output, dict):
        return None
    preview: dict[str, Any] = {}
    if tool_id == "shell.run_command":
        stdout = str(output.get("stdout") or "")[:4000]
        stderr = str(output.get("stderr") or "")[:2000]
        debug_session = debug_session_summary(normalize_debug_session(output))
        preview = {
            "type": "shell",
            "exit_code": output.get("exit_code"),
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": bool(output.get("timed_out")),
            "timeout": output.get("timeout"),
            "failure_message": output.get("failure_message"),
            "diagnostics": (output.get("diagnostics") or [])[:5],
            "debug_session": debug_session,
        }
    elif tool_id == "code.apply_patch":
        preview = {
            "type": "patch",
            "path": output.get("path"),
            "paths": (output.get("paths") or [])[:40],
            "file_count": output.get("file_count"),
            "operation_count": output.get("operation_count"),
            "hunk_count": output.get("hunk_count"),
            "encoding_risks": output.get("encoding_risks"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "code.edit_file":
        preview = {
            "type": "diff",
            "path": output.get("path"),
            "diff_preview": str(output.get("diff_preview") or "")[:4000],
            "encoding": output.get("encoding"),
            "encoding_risks": output.get("encoding_risks"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "code.replace_text":
        preview = {
            "type": "bulk_replace",
            "root": output.get("root"),
            "old_text": output.get("old_text"),
            "new_text": output.get("new_text"),
            "dry_run": bool(output.get("dry_run")),
            "changed_files": (output.get("changed_files") or [])[:80],
            "changed_file_count": output.get("changed_file_count"),
            "matched_file_count": output.get("matched_file_count"),
            "replacement_count": output.get("replacement_count"),
            "truncated": bool(output.get("truncated")),
            "backup": output.get("_backup"),
        }
    elif tool_id == "filesystem.write_file":
        preview = {
            "type": "file_write",
            "path": output.get("path"),
            "created": bool(output.get("created")),
            "size": output.get("size"),
            "encoding": output.get("encoding"),
            "integrity": output.get("integrity"),
            "encoding_risks": output.get("encoding_risks"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "filesystem.apply_changes":
        preview = {
            "type": "file_change_set",
            "paths": (output.get("paths") or [])[:40],
            "changed_paths": (output.get("changed_paths") or [])[:40],
            "created_paths": (output.get("created_paths") or [])[:40],
            "updated_paths": (output.get("updated_paths") or [])[:40],
            "deleted_paths": (output.get("deleted_paths") or [])[:40],
            "operation_count": output.get("operation_count"),
            "changed_file_count": output.get("changed_file_count"),
            "effects": list(output.get("effects") or [])[:12],
            "roles": list(output.get("roles") or [])[:12],
            "verification_strength": output.get("verification_strength"),
            "encoding_risks": output.get("encoding_risks"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "filesystem.transform_text":
        preview = {
            "type": "file_transform",
            "path": output.get("path"),
            "transform": output.get("transform"),
            "changed": bool(output.get("changed")),
            "before_size": output.get("before_size"),
            "after_size": output.get("after_size"),
            "encoding": output.get("encoding"),
            "integrity_before": output.get("integrity_before"),
            "integrity": output.get("integrity"),
            "encoding_risks": output.get("encoding_risks"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "filesystem.delete_file":
        preview = {
            "type": "file_delete",
            "path": output.get("path"),
            "deleted": bool(output.get("deleted")),
            "existed": bool(output.get("existed")),
            "missing_ok": bool(output.get("missing_ok")),
            "size": output.get("size"),
            "effects": list(output.get("effects") or [])[:12],
            "roles": list(output.get("roles") or [])[:12],
            "verification_strength": output.get("verification_strength"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "filesystem.finalize_text_file":
        preview = {
            "type": "file_write",
            "path": output.get("path"),
            "created": bool(output.get("created")),
            "size": output.get("size"),
            "draft_id": output.get("draft_id"),
            "draft_stats": output.get("draft_stats"),
            "validation": output.get("validation"),
            "artifact_kind": output.get("artifact_kind"),
            "encoding": output.get("encoding"),
            "encoding_risks": output.get("encoding_risks"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "document.extract_pdf_to_docx":
        preview = {
            "type": "file_write",
            "path": output.get("path"),
            "created": True,
            "size": output.get("pages_parsed"),
            "mode": output.get("mode") or "text_only",
            "image_count": output.get("image_count"),
            "text_block_count": output.get("text_block_count"),
            "file_size": output.get("file_size"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "document.extract_docx_outline":
        preview = {
            "type": "docx_outline",
            "path": output.get("path"),
            "paragraph_count": output.get("paragraph_count"),
            "text_chars": output.get("text_chars"),
            "table_count": output.get("table_count"),
            "strategy": output.get("strategy"),
        }
    elif tool_id == "spreadsheet.inspect_workbook":
        preview = {
            "type": "spreadsheet_preview",
            "path": output.get("path"),
            "format": output.get("format"),
            "sheet_count": output.get("sheet_count"),
            "sheets": (output.get("sheets") or [])[:6],
        }
    elif tool_id == "document.export_docx":
        preview = {
            "type": "file_write",
            "path": output.get("path"),
            "created": True,
            "content_chars": output.get("content_chars"),
            "paragraph_count": output.get("paragraph_count"),
            "nonempty_paragraph_count": output.get("nonempty_paragraph_count"),
            "file_size": output.get("file_size"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "document.export_draft_docx":
        draft_stats = output.get("draft_stats") if isinstance(output.get("draft_stats"), dict) else {}
        preview = {
            "type": "file_write",
            "path": output.get("path"),
            "created": True,
            "draft_id": output.get("draft_id"),
            "content_chars": output.get("content_chars"),
            "paragraph_count": output.get("paragraph_count"),
            "section_count": draft_stats.get("section_count"),
            "block_count": draft_stats.get("block_count"),
            "text_chars": draft_stats.get("text_chars"),
            "file_size": output.get("file_size"),
            "backup": output.get("_backup"),
        }
    elif tool_id in {
        "document.create_draft",
        "document.append_draft_section",
        "document.add_draft_citation",
        "document.inspect_draft",
    }:
        stats = output.get("stats") if isinstance(output.get("stats"), dict) else {}
        preview = {
            "type": "document_draft",
            "draft_id": output.get("draft_id"),
            "title": output.get("title") or stats.get("title"),
            "section_count": stats.get("section_count"),
            "block_count": stats.get("block_count"),
            "citation_count": stats.get("citation_count"),
            "text_chars": stats.get("text_chars"),
            "unknown_citation_ids": stats.get("unknown_citation_ids") or output.get("unknown_citation_ids"),
        }
    elif tool_id == "document.translate_docx":
        preview = {
            "type": "file_write",
            "path": output.get("path"),
            "created": True,
            "complete": bool(output.get("complete")),
            "status": output.get("status"),
            "partial_resumable": bool(output.get("partial_resumable")),
            "source_nonempty_paragraph_count": output.get("source_nonempty_paragraph_count"),
            "target_nonempty_goal": output.get("target_nonempty_goal"),
            "translated_paragraph_count": output.get("translated_paragraph_count"),
            "failed_paragraph_count": output.get("failed_paragraph_count"),
            "source_chars_done": output.get("source_chars_done"),
            "source_chars_total": output.get("source_chars_total"),
            "manifest_path": output.get("manifest_path"),
            "stopped_reason": output.get("stopped_reason"),
            "file_size": output.get("file_size"),
            "backup": output.get("_backup"),
        }
    elif tool_id == "filesystem.read_file":
        preview = {
            "type": "file_read",
            "path": output.get("path"),
            "total_lines": output.get("total_lines"),
            "start_line": output.get("start_line"),
            "end_line": output.get("end_line"),
            "truncated": bool(output.get("truncated")),
            "remaining_lines": output.get("remaining_lines"),
            "next_start_line": output.get("next_start_line"),
            "next_end_line": output.get("next_end_line"),
            "encoding": output.get("encoding"),
            "integrity": output.get("integrity"),
            "encoding_risks": output.get("encoding_risks"),
        }
    elif tool_id == "filesystem.read_text_preview":
        preview = {
            "type": "file_preview",
            "path": output.get("path"),
            "size": output.get("size"),
            "encoding": output.get("encoding"),
            "truncated": bool(output.get("truncated")),
            "integrity": output.get("integrity"),
            "encoding_risks": output.get("encoding_risks"),
        }
    elif tool_id == "attachment.extract_text":
        preview = {
            "type": "attachment_text",
            "attachment": output.get("attachment"),
            "content": str(output.get("content") or "")[:4000],
            "text_chars": output.get("text_chars"),
            "truncated": bool(output.get("truncated")),
        }
    elif tool_id == "git.diff":
        preview = {"type": "diff", "diff_preview": str(output.get("diff") or "")[:4000]}
    elif tool_id == "git.status":
        preview = {"type": "git_status", "files": (output.get("files") or [])[:40]}
    elif tool_id == "git.log":
        preview = {"type": "git_log", "commits": (output.get("commits") or [])[:10]}
    elif tool_id.startswith("web."):
        visual_evidence = visual_evidence_summary(normalize_visual_evidence(output))
        debug_session = debug_session_summary(normalize_debug_session(output))
        preview = {
            "type": "web",
            "url": output.get("url") or output.get("final_url"),
            "final_url": output.get("final_url") or output.get("url"),
            "status_code": output.get("status_code"),
            "title": output.get("title") or "",
            "path": output.get("path"),
            "format": output.get("format"),
            "artifact_kind": output.get("artifact_kind"),
            "text": str(output.get("text") or "")[:4000],
            "links": (output.get("links") or [])[:20],
            "truncated": bool(output.get("truncated")),
            "visual_evidence": visual_evidence,
            "debug_session": debug_session,
        }
    elif tool_id.startswith("preview."):
        visual_evidence = visual_evidence_summary(normalize_visual_evidence(output))
        debug_session = debug_session_summary(normalize_debug_session(output))
        preview = {
            "type": "preview",
            "status": output.get("status"),
            "error": bool(output.get("error")),
            "file_preview_type": output.get("file_preview_type"),
            "via_tool": output.get("via_tool"),
            "source_type": output.get("source_type"),
            "source_path": output.get("source_path"),
            "served_via": output.get("served_via"),
            "served_root": output.get("served_root"),
            "url": output.get("url"),
            "status_code": output.get("status_code"),
            "title": output.get("title") or "",
            "path": output.get("path"),
            "format": output.get("format"),
            "size": output.get("size"),
            "width": output.get("width"),
            "height": output.get("height"),
            "full_page": bool(output.get("full_page")),
            "artifact_kind": output.get("artifact_kind"),
            "roles": list(output.get("roles") or [])[:12],
            "artifacts": list(output.get("artifacts") or [])[:12],
            "verification_strength": output.get("verification_strength"),
            "interaction": output.get("interaction"),
            "text": str(output.get("text") or "")[:4000],
            "text_chars": output.get("text_chars"),
            "console_errors": (output.get("console_errors") or [])[:10],
            "console_warnings": (output.get("console_warnings") or [])[:10],
            "page_errors": (output.get("page_errors") or [])[:10],
            "page_error_details": (output.get("page_error_details") or [])[:10],
            "failed_requests": (output.get("failed_requests") or [])[:10],
            "resource_responses": (output.get("resource_responses") or [])[:20],
            "has_runtime_errors": bool(output.get("has_runtime_errors")),
            "dom_snapshot": _preview_dom_snapshot_summary(output.get("dom_snapshot")),
            "runtime_diagnostics": (output.get("runtime_diagnostics") or [])[:12],
            "visual_evidence": visual_evidence,
            "debug_session": debug_session,
        }
    elif any(output.get(key) for key in ("effects", "roles", "artifacts", "verification_strength")):
        visual_evidence = visual_evidence_summary(normalize_visual_evidence(output))
        debug_session = debug_session_summary(normalize_debug_session(output))
        preview = {
            "type": "capability_result",
            "content": str(output.get("content") or "")[:4000],
            "path": output.get("path"),
            "format": output.get("format"),
            "artifact_kind": output.get("artifact_kind"),
            "effects": list(output.get("effects") or [])[:12],
            "roles": list(output.get("roles") or [])[:12],
            "artifacts": list(output.get("artifacts") or [])[:12],
            "verification_strength": output.get("verification_strength"),
            "visual_evidence": visual_evidence,
            "debug_session": debug_session,
        }
    else:
        return None
    return preview


TOOL_PAYLOAD_CHAR_LIMIT = 40_000
TOOL_TEXT_BUDGETS: dict[str, int] = {
    "filesystem.read_file.content": 20_000,
    "filesystem.read_file.raw_content": 12_000,
    "filesystem.read_text_preview.content": 20_000,
    "filesystem.read_text_preview.raw_content": 12_000,
    "shell.run_command.stdout": 12_000,
    "shell.run_command.stderr": 6_000,
    "document.extract_docx_outline.text": 24_000,
    "web.text": 24_000,
    "web.html_preview": 8_000,
}


def compact_tool_payload(payload: dict[str, Any], limit: int = TOOL_PAYLOAD_CHAR_LIMIT) -> str:
    text = json.dumps(summarize_tool_payload(payload), ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... 工具结果过长，已截断 ..."


def _budget(tool_id: str, field: str, default: int) -> int:
    if tool_id.startswith("web."):
        return TOOL_TEXT_BUDGETS.get(f"web.{field}", default)
    return TOOL_TEXT_BUDGETS.get(f"{tool_id}.{field}", default)


def _bounded_text(value: Any, limit: int, *, suffix: str) -> tuple[str, bool]:
    text = str(value or "")
    if len(text) <= limit:
        return text, False
    return text[:limit] + suffix, True


def summarize_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tool_id = str(payload.get("tool") or "")
    output = payload.get("output")
    if not isinstance(output, dict):
        return payload

    compacted = dict(payload)
    if tool_id == "filesystem.scan_folder":
        compacted["output"] = {
            "root": output.get("root"),
            "folder_count": output.get("folder_count"),
            "file_count": output.get("file_count"),
            "folders": (output.get("folders") or [])[:120],
            "files": (output.get("files") or [])[:260],
            "truncated_for_context": True,
        }
    elif tool_id == "code.list_project_files":
        compacted["output"] = {
            "root": output.get("root"),
            "file_count": output.get("file_count"),
            "truncated": output.get("truncated"),
            "files": (output.get("files") or [])[:500],
            "truncated_for_context": True,
        }
    elif tool_id == "code.search_text":
        compacted["output"] = {
            "root": output.get("root"),
            "query": output.get("query"),
            "match_count": output.get("match_count"),
            "truncated": output.get("truncated"),
            "matches": (output.get("matches") or [])[:80],
            "truncated_for_context": True,
        }
    elif tool_id in {"filesystem.read_file", "filesystem.read_text_preview"}:
        key = "content" if "content" in output else "text"
        text = str(output.get(key) or "")
        max_chars = _budget(tool_id, "content", 20_000)
        compact_text, text_truncated = _bounded_text(
            text,
            max_chars,
            suffix="\n... 文件内容过长，已压缩；如需更多内容，请按行号范围读取 ...",
        )
        raw_text = str(output.get("raw_content") or "")
        raw_budget = _budget(tool_id, "raw_content", 12_000)
        compact_raw, raw_truncated = _bounded_text(
            raw_text,
            raw_budget,
            suffix="\n... raw_content 已按上下文预算截断，请按行号范围读取更多原文 ...",
        )
        compact_output = {
            key: compact_text,
            "path": output.get("path"),
            "size": output.get("size"),
            "total_lines": output.get("total_lines"),
            "start_line": output.get("start_line"),
            "end_line": output.get("end_line"),
            "encoding": output.get("encoding"),
            "truncated": output.get("truncated") or text_truncated,
            "remaining_lines": output.get("remaining_lines"),
            "next_start_line": output.get("next_start_line"),
            "next_end_line": output.get("next_end_line"),
            "suggested_next_call": output.get("suggested_next_call"),
            "truncated_for_context": text_truncated or raw_truncated,
            "raw_content": compact_raw,
            "raw_content_truncated_for_context": raw_truncated,
            "usage_hint": output.get("usage_hint"),
            "integrity": output.get("integrity"),
            "encoding_risks": output.get("encoding_risks"),
        }
        compacted["output"] = compact_output
    elif tool_id == "shell.run_command":
        stdout, stdout_truncated = _bounded_text(
            output.get("stdout"),
            _budget(tool_id, "stdout", 12_000),
            suffix="\n... stdout 已按上下文预算截断 ...",
        )
        stderr, stderr_truncated = _bounded_text(
            output.get("stderr"),
            _budget(tool_id, "stderr", 6_000),
            suffix="\n... stderr 已按上下文预算截断 ...",
        )
        compacted["output"] = {
            **output,
            "stdout": stdout,
            "stderr": stderr,
            "truncated_for_context": stdout_truncated or stderr_truncated,
            "debug_session": debug_session_summary(normalize_debug_session(output)),
        }
    elif tool_id == "document.extract_docx_outline":
        text = str(output.get("text") or "")
        compact_text, text_truncated = _bounded_text(
            text,
            _budget(tool_id, "text", 24_000),
            suffix="\n... 文档内容过长，已截断；如需全文处理，请使用专门的文档转换/翻译工具或分批读取 ... ",
        )
        compacted["output"] = {
            **output,
            "text": compact_text,
            "text_chars": output.get("text_chars") or len(text),
            "truncated_for_context": text_truncated,
        }
    elif tool_id == "spreadsheet.inspect_workbook":
        compacted["output"] = {
            **output,
            "sheets": (output.get("sheets") or [])[:8],
        }
    elif tool_id.startswith("web."):
        visual_evidence = visual_evidence_summary(normalize_visual_evidence(output))
        debug_session = debug_session_summary(normalize_debug_session(output))
        text, text_truncated = _bounded_text(
            output.get("text"),
            _budget(tool_id, "text", 24_000),
            suffix="\n... 网页正文已按上下文预算截断 ...",
        )
        html_preview, html_truncated = _bounded_text(
            output.get("html_preview"),
            _budget(tool_id, "html_preview", 8_000),
            suffix="\n... HTML 预览已按上下文预算截断 ...",
        )
        compacted["output"] = {
            **output,
            "text": text,
            "html_preview": html_preview,
            "links": (output.get("links") or [])[:80],
            "truncated_for_context": text_truncated or html_truncated or len(output.get("links") or []) > 80,
            "visual_evidence": visual_evidence,
            "debug_session": debug_session,
        }
    elif tool_id.startswith("preview."):
        text, text_truncated = _bounded_text(
            output.get("text"),
            12_000,
            suffix="\n... preview text 已按上下文预算截断 ...",
        )
        compacted["output"] = {
            "type": output.get("type"),
            "status": output.get("status"),
            "error": output.get("error"),
            "file_preview_type": output.get("file_preview_type"),
            "via_tool": output.get("via_tool"),
            "source_type": output.get("source_type"),
            "source_path": output.get("source_path"),
            "served_via": output.get("served_via"),
            "served_root": output.get("served_root"),
            "url": output.get("url"),
            "status_code": output.get("status_code"),
            "title": output.get("title"),
            "path": output.get("path"),
            "format": output.get("format"),
            "size": output.get("size"),
            "width": output.get("width"),
            "height": output.get("height"),
            "full_page": output.get("full_page"),
            "artifact_kind": output.get("artifact_kind"),
            "artifacts": output.get("artifacts"),
            "effects": output.get("effects"),
            "roles": output.get("roles"),
            "verification_strength": output.get("verification_strength"),
            "interaction": output.get("interaction"),
            "text": text,
            "text_chars": output.get("text_chars"),
            "truncated_for_context": text_truncated,
            "has_runtime_errors": output.get("has_runtime_errors"),
            "console_errors": (output.get("console_errors") or [])[:10],
            "console_warnings": (output.get("console_warnings") or [])[:10],
            "page_errors": (output.get("page_errors") or [])[:10],
            "page_error_details": (output.get("page_error_details") or [])[:10],
            "failed_requests": (output.get("failed_requests") or [])[:10],
            "resource_responses": (output.get("resource_responses") or [])[:20],
            "runtime_diagnostics": (output.get("runtime_diagnostics") or [])[:12],
            "dom_snapshot": _preview_dom_snapshot_summary(output.get("dom_snapshot")),
            "visual_evidence": visual_evidence_summary(normalize_visual_evidence(output)),
            "debug_session": debug_session_summary(normalize_debug_session(output)),
        }
    return compacted


def _preview_dom_snapshot_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    body_text = str(value.get("body_text") or "")
    return {
        "ready_state": value.get("ready_state"),
        "title": value.get("title"),
        "body_text": body_text[:2000],
        "body_text_chars": value.get("body_text_chars"),
        "loading_visible": bool(value.get("loading_visible")),
        "loading_texts": (value.get("loading_texts") or [])[:6],
        "headings": (value.get("headings") or [])[:8],
        "buttons": (value.get("buttons") or [])[:12],
        "external_resource_hosts": (value.get("external_resource_hosts") or [])[:10],
        "importmap_hosts": (value.get("importmap_hosts") or [])[:10],
    }
