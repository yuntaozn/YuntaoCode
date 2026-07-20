from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from runtime.tool_registry import ToolRegistry, ToolSpec


_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


async def inspect_workbook(input_data: dict[str, Any], context: Any) -> dict[str, Any]:
    path = context.path_guard.resolve(input_data.get("path"))
    max_rows = max(1, min(int(input_data.get("max_rows") or 20), 200))
    max_sheets = max(1, min(int(input_data.get("max_sheets") or 8), 50))
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return _inspect_xlsx(path, max_rows=max_rows, max_sheets=max_sheets)
    if suffix in {".csv", ".tsv"}:
        return _inspect_delimited(path, max_rows=max_rows, delimiter="\t" if suffix == ".tsv" else ",")
    if suffix == ".xls":
        raise ValueError("legacy .xls files are not supported by the built-in reader; convert to .xlsx or .csv first")
    raise ValueError("spreadsheet.inspect_workbook supports .xlsx, .csv, and .tsv files")


def _inspect_delimited(path: Path, *, max_rows: int, delimiter: str) -> dict[str, Any]:
    text = _read_text_with_fallback(path)
    rows: list[list[str]] = []
    for row in csv.reader(text.splitlines(), delimiter=delimiter):
        rows.append([str(cell) for cell in row])
        if len(rows) >= max_rows:
            break
    return {
        "type": "spreadsheet_preview",
        "path": str(path),
        "format": path.suffix.lower().lstrip("."),
        "sheet_count": 1,
        "sheets": [{
            "name": path.stem,
            "preview_rows": rows,
            "preview_row_count": len(rows),
            "preview_column_count": max((len(row) for row in rows), default=0),
        }],
    }


def _inspect_xlsx(path: Path, *, max_rows: int, max_sheets: int) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _load_shared_strings(archive)
        relationships = _load_workbook_relationships(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets: list[dict[str, Any]] = []
        for sheet_node in workbook.findall("main:sheets/main:sheet", _NS)[:max_sheets]:
            name = str(sheet_node.attrib.get("name") or "Sheet")
            rel_id = sheet_node.attrib.get(f"{{{_NS['rel']}}}id") or ""
            target = relationships.get(rel_id)
            if not target:
                sheets.append({"name": name, "warning": "sheet relationship not found"})
                continue
            sheet_path = _normalize_xlsx_part_path(target)
            if sheet_path not in archive.namelist():
                sheets.append({"name": name, "warning": f"sheet part not found: {sheet_path}"})
                continue
            preview = _read_sheet_preview(
                archive.read(sheet_path),
                shared_strings=shared_strings,
                max_rows=max_rows,
            )
            preview["name"] = name
            sheets.append(preview)
    return {
        "type": "spreadsheet_preview",
        "path": str(path),
        "format": "xlsx",
        "sheet_count": len(sheets),
        "sheets": sheets,
    }


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", _NS):
        texts = [node.text or "" for node in item.findall(".//main:t", _NS)]
        values.append("".join(texts))
    return values


def _load_workbook_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    rel_path = "xl/_rels/workbook.xml.rels"
    if rel_path not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read(rel_path))
    relationships: dict[str, str] = {}
    for item in root.findall("pkgrel:Relationship", _NS):
        rel_id = str(item.attrib.get("Id") or "")
        target = str(item.attrib.get("Target") or "")
        if rel_id and target:
            relationships[rel_id] = target
    return relationships


def _normalize_xlsx_part_path(target: str) -> str:
    cleaned = target.replace("\\", "/").lstrip("/")
    if cleaned.startswith("xl/"):
        return cleaned
    return f"xl/{cleaned}"


def _read_sheet_preview(
    data: bytes,
    *,
    shared_strings: list[str],
    max_rows: int,
) -> dict[str, Any]:
    root = ET.fromstring(data)
    rows: list[list[str]] = []
    max_column = 0
    total_rows = 0
    for row_node in root.findall("main:sheetData/main:row", _NS):
        total_rows += 1
        parsed_cells: dict[int, str] = {}
        for cell in row_node.findall("main:c", _NS):
            ref = str(cell.attrib.get("r") or "")
            column = _column_index_from_cell_ref(ref) or (len(parsed_cells) + 1)
            parsed_cells[column] = _cell_text(cell, shared_strings)
            max_column = max(max_column, column)
        if len(rows) < max_rows:
            if parsed_cells:
                width = max(parsed_cells)
                rows.append([parsed_cells.get(index, "") for index in range(1, width + 1)])
            else:
                rows.append([])
    return {
        "row_count": total_rows,
        "column_count": max_column,
        "preview_rows": rows,
        "preview_row_count": len(rows),
        "truncated": total_rows > len(rows),
    }


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", _NS))
    value_node = cell.find("main:v", _NS)
    value = value_node.text if value_node is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return value or ""
    return value or ""


def _column_index_from_cell_ref(ref: str) -> int:
    match = re.match(r"([A-Za-z]+)", ref or "")
    if not match:
        return 0
    value = 0
    for char in match.group(1).upper():
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


def _read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def register_spreadsheet_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            id="spreadsheet.inspect_workbook",
            name="Inspect spreadsheet workbook",
            description=(
                "Read spreadsheet structure and preview rows from .xlsx, .csv, or .tsv files. "
                "Use this for Excel/table data instead of Word document tools. "
                "Legacy .xls is not parsed directly; convert it to .xlsx or .csv first."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Spreadsheet path (.xlsx, .csv, or .tsv)"},
                    "max_rows": {"type": "integer", "default": 20, "description": "Preview rows per sheet"},
                    "max_sheets": {"type": "integer", "default": 8, "description": "Maximum sheets to inspect"},
                },
                "required": ["path"],
            },
            requires_confirmation=False,
            capability="spreadsheet.local_files",
            artifacts=["spreadsheet_preview"],
            roles=["evidence", "verification"],
            verification_strength="weak",
            idempotent=True,
        ),
        inspect_workbook,
    )
