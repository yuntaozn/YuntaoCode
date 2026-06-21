from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from runtime.security import PathGuard
from runtime.skills.spreadsheet import inspect_workbook


class FakeContext:
    def __init__(self, root: Path):
        self.path_guard = PathGuard([root])


def _write_minimal_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Items" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>Name</t></si><si><t>Qty</t></si><si><t>Pipe</t></si>
</sst>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
    <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>3</v></c></row>
  </sheetData>
</worksheet>""",
        )


@pytest.mark.asyncio
async def test_inspect_workbook_reads_xlsx_preview(tmp_path: Path) -> None:
    path = tmp_path / "demo.xlsx"
    _write_minimal_xlsx(path)

    result = await inspect_workbook({"path": str(path), "max_rows": 5}, FakeContext(tmp_path))

    assert result["type"] == "spreadsheet_preview"
    assert result["format"] == "xlsx"
    assert result["sheet_count"] == 1
    sheet = result["sheets"][0]
    assert sheet["name"] == "Items"
    assert sheet["preview_rows"] == [["Name", "Qty"], ["Pipe", "3"]]


@pytest.mark.asyncio
async def test_inspect_workbook_reads_csv_preview(tmp_path: Path) -> None:
    path = tmp_path / "demo.csv"
    path.write_text("name,qty\npipe,3\n", encoding="utf-8")

    result = await inspect_workbook({"path": str(path)}, FakeContext(tmp_path))

    assert result["format"] == "csv"
    assert result["sheets"][0]["preview_rows"] == [["name", "qty"], ["pipe", "3"]]


@pytest.mark.asyncio
async def test_inspect_workbook_rejects_xls_with_clear_message(tmp_path: Path) -> None:
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"not parsed")

    with pytest.raises(ValueError, match="legacy .xls"):
        await inspect_workbook({"path": str(path)}, FakeContext(tmp_path))
