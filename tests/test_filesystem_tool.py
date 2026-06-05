from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from runtime.security import PathGuard
from runtime.skills.filesystem import (
    read_file,
    read_text_preview,
    transform_text,
    write_file,
    write_temp_file,
)


@dataclass
class FakeContext:
    path_guard: PathGuard
    temp_dir: Path

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        return None


@pytest.mark.asyncio
async def test_write_file_rejects_truncated_full_html_without_overwriting(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "viewer.html"
    original = "<!DOCTYPE html><html><body>original</body></html>"
    path.write_text(original, encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    with pytest.raises(ValueError, match="refusing incomplete .html overwrite"):
        await write_file(
            {"path": str(path), "content": "<!DOCTYPE html><html><body>truncated"},
            context,
        )

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_write_and_read_file_report_valid_full_html_integrity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "viewer.html"
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")
    content = "<!DOCTYPE html><html><body><script>console.log('ok')</script></body></html>"

    write_result = await write_file({"path": str(path), "content": content}, context)
    read_result = await read_file({"path": str(path)}, context)

    assert write_result["integrity"]["valid"] is True
    assert read_result["integrity"]["valid"] is True


@pytest.mark.asyncio
async def test_write_file_rejects_escaped_html_document(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "viewer.html"
    original = "<!DOCTYPE html><html><body>original</body></html>"
    path.write_text(original, encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    with pytest.raises(ValueError, match="html appears escaped as text"):
        await write_file(
            {"path": str(path), "content": "&lt;!DOCTYPE html&gt;\n&lt;html&gt;"},
            context,
        )

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_transform_text_unescapes_html_entities_in_place(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "viewer.html"
    path.write_text("&lt;!DOCTYPE html&gt;\n&lt;html&gt;&lt;body&gt;ok&lt;/body&gt;&lt;/html&gt;", encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await transform_text(
        {"path": str(path), "transform": "html_unescape"},
        context,
    )

    assert result["changed"] is True
    assert result["integrity_before"]["valid"] is False
    assert result["integrity"]["valid"] is True
    assert path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


@pytest.mark.asyncio
async def test_transform_text_rejects_unknown_transform(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    with pytest.raises(ValueError, match="unsupported text transform"):
        await transform_text({"path": str(path), "transform": "rot13"}, context)


@pytest.mark.asyncio
async def test_read_text_preview_reports_html_integrity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "viewer.html"
    path.write_text("&lt;!DOCTYPE html&gt;\n&lt;html&gt;", encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await read_text_preview({"path": str(path), "max_bytes": 10}, context)

    assert result["truncated"] is True
    assert result["integrity"]["checked"] is True
    assert result["integrity"]["valid"] is False
    assert "html appears escaped as text" in result["integrity"]["issues"]


@pytest.mark.asyncio
async def test_write_temp_file_writes_inside_task_temp_dir(tmp_path: Path) -> None:
    temp_dir = tmp_path / "task-artifacts" / "task-1"
    context = FakeContext(PathGuard([tmp_path / "workspace"]), temp_dir)

    result = await write_temp_file(
        {"path": "scripts/analyze.py", "content": "print('ok')"},
        context,
    )

    path = Path(result["path"])
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "print('ok')"
    assert result["relative_path"] == str(Path("scripts") / "analyze.py")
    assert result["temp_dir"] == str(temp_dir.resolve())
    assert result["artifact_kind"] == "task_temp_file"


@pytest.mark.asyncio
async def test_write_temp_file_rejects_parent_traversal(tmp_path: Path) -> None:
    context = FakeContext(PathGuard([tmp_path / "workspace"]), tmp_path / "task")

    with pytest.raises(ValueError):
        await write_temp_file({"path": "../escape.py", "content": "bad"}, context)
