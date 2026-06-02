from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from runtime.security import PathGuard
from runtime.skills import pdf_parser
from runtime.skills.document import extract_pdf_to_docx


@dataclass
class FakeContext:
    path_guard: PathGuard

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        return None


@pytest.mark.asyncio
async def test_extract_pdf_to_docx_writes_docx_with_parsed_text(tmp_path: Path, monkeypatch) -> None:
    class FakePDFParser:
        async def parse(self, file_path: Path, max_pages: int = 0, context=None):
            return pdf_parser.ParseResult(
                text="第一段 PDF 文本。\n\nSecond paragraph.",
                total_pages=2,
                pages_parsed=2,
                strategy="fake",
            )

    monkeypatch.setattr(pdf_parser, "PDFParser", FakePDFParser)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_path = tmp_path / "sample.docx"

    result = await extract_pdf_to_docx(
        {
            "path": str(pdf_path),
            "output_path": str(output_path),
            "title": "PDF 提取测试",
        },
        FakeContext(PathGuard([tmp_path])),
    )

    assert result["path"] == str(output_path.resolve())
    assert result["source_path"] == str(pdf_path.resolve())
    assert result["pages_parsed"] == 2
    assert output_path.exists()
    assert output_path.stat().st_size > 0
