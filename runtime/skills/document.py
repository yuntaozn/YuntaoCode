from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, List

from runtime.tool_registry import ToolRegistry, ToolSpec


def _resolve_output_path(input_data: dict[str, Any], context: Any, default_title: str, ext: str) -> "Path":
    """Flexibly resolve output path from various possible field names.
    If no path is found, auto-generate from title in workspace root."""
    raw_path = (
        input_data.get("path")
        or input_data.get("output_path")
        or input_data.get("file_path")
        or input_data.get("filename")
    )
    if not raw_path:
        title = input_data.get("title", default_title) or default_title
        safe_name = re.sub(r'[<>:"/\\|?*]', '', title)[:60].strip() or default_title
        raw_path = f"{safe_name}{ext}"
    path = context.path_guard.resolve(raw_path)
    if path.suffix.lower() != ext:
        path = path.with_suffix(ext)
    return path


def _backup_output(path: Path, context: Any) -> None:
    backup_file = getattr(context, "backup_file", None)
    if callable(backup_file):
        backup_file(path)


async def extract_docx_outline(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    suffix = path.suffix.lower()
    if suffix not in (".docx", ".doc"):
        raise ValueError("仅支持 .docx 和 .doc 格式")

    from .docx_parser import DocxParser
    parser = DocxParser()

    extract_text = input_data.get("extract_text", True)
    result = await parser.parse(
        path,
        extract_text=extract_text,
        extract_headings=True,
    )

    output: dict[str, Any] = {
        "path": str(path),
        "paragraph_count": result.paragraph_count,
        "headings": result.headings,
        "strategy": result.strategy,
    }
    if extract_text:
        output["text"] = result.text
    if result.table_count > 0:
        output["table_count"] = result.table_count
    if result.warnings:
        output["warnings"] = result.warnings
    return output


async def extract_pdf_text_preview(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    if path.suffix.lower() != ".pdf":
        raise ValueError("only .pdf files are supported")

    max_pages = int(input_data.get("max_pages", 50))

    from .pdf_parser import PDFParser, ParseResult
    parser = PDFParser()
    result: ParseResult = await parser.parse(path, max_pages=max_pages, context=context)

    output: dict[str, Any] = {
        "path": str(path),
        "page_count": result.total_pages,
        "pages_parsed": result.pages_parsed,
        "text": result.text,
        "strategy": result.strategy,
        "garbled_ratio": round(result.garbled_ratio, 4),
        "ocr_used": result.ocr_used,
    }
    if result.ocr_pages > 0:
        output["ocr_pages"] = result.ocr_pages
    if result.cid_garbled:
        output["cid_garbled_detected"] = True
    if result.warnings:
        output["warnings"] = result.warnings
    return output


async def export_markdown(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    title = input_data.get("title", "AI生成文档")
    path = _resolve_output_path(input_data, context, title, ".md")
    content = input_data.get("content", "")
    
    content = content.strip()
    if not content.startswith("#"):
        content = f"# {title}\n\n{content}"
    
    _backup_output(path, context)
    path.write_text(content + "\n", encoding="utf-8")
    
    return {
        "path": str(path.resolve()),
        "size": len(content),
        "title": title,
    }


async def export_docx(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    title = input_data.get("title", "AI生成文档")
    path = _resolve_output_path(input_data, context, title, ".docx")
    content = input_data.get("content", "")
    
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError as exc:
        raise RuntimeError("python-docx is required for document.export_docx") from exc
    
    doc = Document()
    
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.font.size = Pt(10.5)
    
    for style_name in ("Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[style_name]
        style.font.name = "Microsoft YaHei"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    
    markdown = content.strip()
    if not markdown.lstrip().startswith("#"):
        doc.add_heading(title, level=1)
    
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    in_code = False
    code_lines: List[str] = []
    
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        
        if stripped.startswith("```"):
            if in_code:
                p = doc.add_paragraph()
                p.style = "No Spacing"
                run = p.add_run("\n".join(code_lines))
                font = run.font
                font.name = "Consolas"
                code_lines = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        
        if not stripped:
            doc.add_paragraph()
            index += 1
            continue
        
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            level = min(len(heading_match.group(1)), 3)
            doc.add_heading(heading_match.group(2), level=level)
            index += 1
            continue
        
        doc.add_paragraph(stripped)
        index += 1
    
    if in_code and code_lines:
        p = doc.add_paragraph()
        p.style = "No Spacing"
        run = p.add_run("\n".join(code_lines))
        font = run.font
        font.name = "Consolas"
    
    _backup_output(path, context)
    doc.save(str(path))
    
    return {
        "path": str(path.resolve()),
        "title": title,
    }


async def generate_docx_from_outline(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    title = input_data.get("title", "文档")
    path = _resolve_output_path(input_data, context, title, ".docx")
    outline = input_data.get("outline", [])
    
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.shared import Pt
    except ImportError as exc:
        raise RuntimeError("python-docx is required for document.generate_docx_from_outline") from exc
    
    doc = Document()
    
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.font.size = Pt(10.5)
    
    for style_name in ("Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[style_name]
        style.font.name = "Microsoft YaHei"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    
    doc.add_heading(title, level=1)
    
    for item in outline:
        level = min(int(item.get("level", 1)), 3)
        text = item.get("text", "")
        if text:
            doc.add_heading(text, level=level)
    
    _backup_output(path, context)
    doc.save(str(path))
    
    return {
        "path": str(path.resolve()),
        "title": title,
        "outline_count": len(outline),
    }


async def export_pdf(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    title = input_data.get("title", "AI生成文档")
    path = _resolve_output_path(input_data, context, title, ".pdf")
    content = input_data.get("content", "")
    
    try:
        from markdown import markdown
    except ImportError as exc:
        raise RuntimeError("markdown library is required for document.export_pdf") from exc
    
    html_content = markdown(content)
    
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is required for document.export_pdf. "
            "Install: pip install playwright && playwright install chromium"
        ) from exc
    
    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; color: #111827; line-height: 1.72; font-size: 14px; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1, h2, h3, h4 {{ color: #0f172a; line-height: 1.35; margin: 20px 0 10px; }}
        h1 {{ font-size: 22px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
        h2 {{ font-size: 18px; }}
        h3 {{ font-size: 16px; }}
        pre {{ background: #f3f4f6; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 13px; }}
        code {{ font-family: Consolas, "Courier New", monospace; background: #f3f4f6; padding: 2px 4px; border-radius: 3px; font-size: 13px; }}
        pre code {{ background: none; padding: 0; }}
        blockquote {{ border-left: 4px solid #d1d5db; margin: 12px 0; padding: 8px 16px; color: #6b7280; }}
        table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
        th, td {{ border: 1px solid #d1d5db; padding: 8px 12px; text-align: left; }}
        th {{ background: #f9fafb; font-weight: 600; }}
        img {{ max-width: 100%; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {html_content}
</body>
</html>"""
    
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1240, "height": 1754})
            await page.set_content(full_html, wait_until="load")
            _backup_output(path, context)
            await page.pdf(
                path=str(path),
                format="A4",
                print_background=True,
                margin={"top": "18mm", "right": "18mm", "bottom": "18mm", "left": "18mm"},
            )
        finally:
            await browser.close()
    
    return {
        "path": str(path.resolve()),
        "title": title,
    }


async def generate_ppt(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    title = input_data.get("title", "演示文稿")
    path = _resolve_output_path(input_data, context, title, ".pptx")

    slides = input_data.get("slides", [])
    outline = input_data.get("outline", [])
    content = input_data.get("content", "")
    
    # 兼容多种输入格式：优先slides，其次outline，最后纯内容
    if not slides and outline:
        # 从大纲自动生成幻灯片
        slides = []
        # 封面页
        slides.append({"title": title, "content": "AI 生成演示文稿"})
        # 内容页
        current_slide = {"title": "", "content": []}
        for item in outline:
            level = item.get("level", 1)
            text = item.get("text", "").strip()
            if not text:
                continue
            if level == 1:
                if current_slide["title"]:
                    slides.append({
                        "title": current_slide["title"],
                        "content": "\n- " + "\n- ".join(current_slide["content"])
                    })
                current_slide = {"title": text, "content": []}
            else:
                current_slide["content"].append(text)
        if current_slide["title"]:
            slides.append({
                "title": current_slide["title"],
                "content": "\n- " + "\n- ".join(current_slide["content"])
            })
    elif not slides and content:
        # 从纯文本自动生成幻灯片
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        slides = []
        # 封面页
        slides.append({"title": title, "content": "AI 生成演示文稿"})
        # 内容页
        current_title = ""
        current_content = []
        for line in lines:
            if line.startswith("# "):
                if current_title:
                    slides.append({
                        "title": current_title,
                        "content": "\n".join(current_content)
                    })
                current_title = line[2:].strip()
                current_content = []
            elif line.startswith("## "):
                if current_title:
                    slides.append({
                        "title": current_title,
                        "content": "\n".join(current_content)
                    })
                current_title = line[3:].strip()
                current_content = []
            else:
                current_content.append(line)
        if current_title:
            slides.append({
                "title": current_title,
                "content": "\n".join(current_content)
            })
    
    if not slides:
        raise ValueError("slides/outline/content is required: provide at least one content source")
    
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
    except ImportError as exc:
        raise RuntimeError("python-pptx is required for document.generate_ppt") from exc
    
    prs = Presentation()
    
    # 设置默认字体为微软雅黑，支持中文
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text_frame"):
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = "Microsoft YaHei"
                        run.font.element.rPr.rFonts.set(prs.nsdecls['w'], "Microsoft YaHei")
    
    for i, slide_data in enumerate(slides):
        if i == 0:
            # 封面页用布局0
            slide_layout = prs.slide_layouts[0]
        else:
            # 内容页用布局1，带标题和内容
            slide_layout = prs.slide_layouts[1]
        
        slide = prs.slides.add_slide(slide_layout)
        
        title_text = slide_data.get("title", "")
        if title_text and slide.shapes.title:
            title_shape = slide.shapes.title
            title_shape.text = title_text
            # 标题字体设置
            for paragraph in title_shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.name = "Microsoft YaHei"
                    run.font.element.rPr.rFonts.set(prs.nsdecls['w'], "Microsoft YaHei")
                    run.font.size = Pt(24 if i == 0 else 20)
                    if i == 0:
                        run.font.bold = True
        
        content_text = slide_data.get("content", "")
        if content_text and slide.shapes.placeholders:
            # 找到内容占位符（idx=1）
            content_placeholder = None
            for placeholder in slide.shapes.placeholders:
                if placeholder.placeholder_format.idx == 1:
                    content_placeholder = placeholder
                    break
            
            if content_placeholder:
                content_placeholder.text = content_text
                # 内容字体设置
                for paragraph in content_placeholder.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = "Microsoft YaHei"
                        run.font.element.rPr.rFonts.set(prs.nsdecls['w'], "Microsoft YaHei")
                        run.font.size = Pt(14)
    
    _backup_output(path, context)
    prs.save(str(path))
    
    return {
        "path": str(path.resolve()),
        "title": title,
        "slide_count": len(slides),
        "input_type": "slides" if input_data.get("slides") else "outline" if input_data.get("outline") else "content"
    }


async def merge_pdfs(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    output_path = context.path_guard.resolve(input_data.get("output_path"))
    input_paths = input_data.get("input_paths", [])
    
    try:
        from PyPDF2 import PdfMerger
    except ImportError as exc:
        raise RuntimeError("PyPDF2 is required for document.merge_pdfs") from exc
    
    merger = PdfMerger()
    
    for path_str in input_paths:
        path = context.path_guard.resolve(path_str)
        merger.append(str(path))
    
    _backup_output(output_path, context)
    try:
        merger.write(str(output_path))
    finally:
        merger.close()
    
    return {
        "output_path": str(output_path.resolve()),
        "merged_count": len(input_paths),
    }


async def split_pdf(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    output_dir = context.path_guard.resolve(input_data.get("output_dir", path.parent))
    
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError("PyPDF2 is required for document.split_pdf") from exc
    
    reader = PdfReader(str(path))
    output_dir.mkdir(exist_ok=True)
    
    split_files = []
    
    for i, page in enumerate(reader.pages):
        writer = PdfWriter()
        writer.add_page(page)
        
        output_path = output_dir / f"{path.stem}_page_{i+1}.pdf"
        _backup_output(output_path, context)
        with open(output_path, "wb") as f:
            writer.write(f)
        
        split_files.append(str(output_path))
    
    return {
        "source_path": str(path),
        "output_dir": str(output_dir),
        "split_files": split_files,
    }


async def create_bookmark_outline(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    bookmarks = input_data.get("bookmarks", [])
    
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError("PyPDF2 is required for document.create_bookmark_outline") from exc
    
    reader = PdfReader(str(path))
    writer = PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
    
    def add_bookmarks(bookmarks_list: list[dict[str, Any]], parent: Any = None) -> None:
        for item in bookmarks_list:
            title = item.get("title", "")
            page_num = max(0, int(item.get("page", 1)) - 1)
            if page_num < len(reader.pages):
                dest = writer.add_outline_item(title, page_num, parent)
                children = item.get("children", [])
                if children:
                    add_bookmarks(children, dest)
    
    add_bookmarks(bookmarks)
    
    output_path = path.parent / f"{path.stem}_with_bookmarks.pdf"
    _backup_output(output_path, context)
    with open(output_path, "wb") as f:
        writer.write(f)
    
    return {
        "output_path": str(output_path.resolve()),
        "bookmark_count": len(bookmarks),
    }


def register_document_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="document.extract_docx_outline",
            name="智能提取 Word 文档",
            description="智能提取 Word 文档内容（大纲 + 全文 + 表格）。支持 .docx 和 .doc 格式，自动处理损坏/非标准文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Word 文档路径（.docx 或 .doc）"},
                    "extract_text": {"type": "boolean", "default": True, "description": "是否提取全文内容（包含段落和表格）"},
                },
                "required": ["path"],
            },
            optional_dependencies=["docx"],
        ),
        extract_docx_outline,
    )
    registry.register(
        ToolSpec(
            id="document.extract_pdf_text_preview",
            name="智能提取 PDF 文本",
            description="智能提取 PDF 文本内容（自动乱码检测 + 多引擎兜底 + AI OCR 回退）。支持扫描版和加密字体 PDF。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "PDF 文件路径"},
                    "max_pages": {"type": "integer", "default": 50, "description": "最大解析页数，0表示不限"},
                },
                "required": ["path"],
            },
            optional_dependencies=["PyPDF2"],
        ),
        extract_pdf_text_preview,
    )
    registry.register(
        ToolSpec(
            id="document.export_markdown",
            name="导出 Markdown 文档",
            description="将文本内容保存为 .md 文件，会自动添加标题。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "title": {"type": "string", "default": "AI生成文档"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
        ),
        export_markdown,
    )
    registry.register(
        ToolSpec(
            id="document.export_docx",
            name="导出 Word 文档",
            description="将 Markdown 内容导出为 .docx 文档，支持基本的标题、段落和代码块。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "title": {"type": "string", "default": "AI生成文档"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
            optional_dependencies=["docx"],
        ),
        export_docx,
    )
    registry.register(
        ToolSpec(
            id="document.generate_docx_from_outline",
            name="从大纲生成 Word",
            description="根据大纲标题列表快速生成 .docx 文档框架。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "title": {"type": "string", "default": "文档"},
                    "outline": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "level": {"type": "integer", "default": 1},
                                "text": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["path", "outline"],
            },
            requires_confirmation=True,
            optional_dependencies=["docx"],
        ),
        generate_docx_from_outline,
    )
    registry.register(
        ToolSpec(
            id="document.export_pdf",
            name="导出 PDF 文档",
            description="将 Markdown 内容导出为 .pdf 文档。需要安装 playwright。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "title": {"type": "string", "default": "AI生成文档"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
            optional_dependencies=["markdown", "playwright"],
        ),
        export_pdf,
    )
    registry.register(
        ToolSpec(
            id="document.generate_ppt",
            name="生成 PowerPoint",
            description="根据幻灯片内容列表快速生成 .pptx 演示文稿。每张幻灯片需要 title（标题）和 content（正文，多条用换行分隔）。第一张使用封面版式，其余使用标题+内容版式。",
            optional_dependencies=["pptx"],
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "输出的 .pptx 文件路径"},
                    "title": {"type": "string", "default": "演示文稿", "description": "演示文稿总标题"},
                    "slides": {
                        "type": "array",
                        "description": "幻灯片列表，每项为一张幻灯片",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "幻灯片标题"},
                                "content": {"type": "string", "description": "幻灯片正文内容，多条要点用换行符分隔"},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["path", "slides"],
            },
            requires_confirmation=True,
        ),
        generate_ppt,
    )
    registry.register(
        ToolSpec(
            id="document.merge_pdfs",
            name="合并 PDF 文件",
            description="将多个 PDF 文件合并为一个。",
            input_schema={
                "type": "object",
                "properties": {
                    "output_path": {"type": "string"},
                    "input_paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["output_path", "input_paths"],
            },
            requires_confirmation=True,
            optional_dependencies=["PyPDF2"],
        ),
        merge_pdfs,
    )
    registry.register(
        ToolSpec(
            id="document.split_pdf",
            name="拆分 PDF 文件",
            description="将 PDF 按页拆分为多个文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "output_dir": {"type": "string"},
                },
                "required": ["path"],
            },
            requires_confirmation=True,
            optional_dependencies=["PyPDF2"],
        ),
        split_pdf,
    )
    registry.register(
        ToolSpec(
            id="document.create_bookmark_outline",
            name="创建 PDF 书签",
            description="为 PDF 文件添加书签导航。",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "bookmarks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "page": {"type": "integer"},
                                "children": {"type": "array", "items": {"type": "object"}},
                            },
                        },
                    },
                },
                "required": ["path", "bookmarks"],
            },
            requires_confirmation=True,
            optional_dependencies=["PyPDF2"],
        ),
        create_bookmark_outline,
    )
