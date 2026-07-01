from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from runtime.security import PathGuard
from runtime.skills.filesystem import (
    apply_changes,
    append_text_chunk,
    copy_file,
    create_text_draft,
    delete_file,
    finalize_text_file,
    inspect_text_draft,
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
    backups: list[Path] = field(default_factory=list)

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        return None

    def backup_file(self, path: Path) -> None:
        self.backups.append(path)


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
async def test_read_file_detects_gb18030_beyond_initial_ascii_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "app.js"
    content = "const filler = '" + ("a" * 9000) + "';\nconst label = '正在加载施工机械模型.';\n"
    path.write_bytes(content.encode("gb18030"))
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await read_file({"path": str(path)}, context)

    assert result["encoding"] == "gb18030"
    assert "正在加载施工机械模型" in result["raw_content"]
    assert "�" not in result["raw_content"]


@pytest.mark.asyncio
async def test_write_file_preserves_existing_gb18030_encoding(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "app.js"
    path.write_bytes("const label = '正在加载施工机械模型.';\n".encode("gb18030"))
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await write_file(
        {"path": str(path), "content": "const label = '施工机械模型已加载.';\n"},
        context,
    )

    raw = path.read_bytes()
    assert result["encoding"] == "gb18030"
    assert "施工机械模型已加载" in raw.decode("gb18030")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")


@pytest.mark.asyncio
async def test_write_file_reports_html_charset_risk_without_blocking(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "viewer.html"
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await write_file(
        {
            "path": str(path),
            "content": "<!doctype html><html><body>正在加载施工机械模型.</body></html>",
        },
        context,
    )

    risk_codes = {risk["code"] for risk in result["encoding_risks"]}
    assert "html_charset_missing" in risk_codes


@pytest.mark.asyncio
async def test_delete_file_removes_file_with_structured_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "notes.md"
    path.write_text("temporary", encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await delete_file({"path": str(path)}, context)

    assert not path.exists()
    assert result["deleted"] is True
    assert result["existed"] is True
    assert result["effects"] == ["file_delete", "local_state_change"]
    assert result["roles"] == ["deliverable", "verification"]
    assert result["verification_strength"] == "standard"


@pytest.mark.asyncio
async def test_copy_file_creates_destination_and_returns_artifact_facts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "other" / "standing.glb"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"glb-data")
    destination = workspace / "project" / "assets" / "standing.glb"
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await copy_file(
        {
            "source_path": str(source),
            "destination_path": str(destination),
        },
        context,
    )

    assert destination.read_bytes() == b"glb-data"
    assert result["type"] == "file_copy"
    assert result["source_path"] == str(source)
    assert result["path"] == str(destination)
    assert result["paths"] == [str(destination)]
    assert result["created"] is True
    assert result["integrity"]["valid"] is True
    assert result["roles"] == ["deliverable", "verification"]
    assert result["effects"] == ["file_write", "local_state_change"]
    assert context.backups == []


@pytest.mark.asyncio
async def test_copy_file_backs_up_existing_destination(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "source.txt"
    destination = workspace / "destination.txt"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await copy_file(
        {
            "source_path": str(source),
            "destination_path": str(destination),
        },
        context,
    )

    assert destination.read_text(encoding="utf-8") == "new"
    assert result["overwritten"] is True
    assert context.backups == [destination]


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
async def test_apply_changes_creates_replaces_and_deletes_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    old_path = workspace / "old.txt"
    old_path.write_text("remove me", encoding="utf-8")
    page_path = workspace / "page.html"
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    result = await apply_changes(
        {
            "reason": "create demo page and remove stale file",
            "operations": [
                {
                    "type": "create_file",
                    "path": str(page_path),
                    "content": "<!doctype html><html><body>hello</body></html>",
                },
                {
                    "type": "replace_text",
                    "path": str(page_path),
                    "old_text": "hello",
                    "new_text": "world",
                },
                {"type": "delete_file", "path": str(old_path)},
            ],
        },
        context,
    )

    assert page_path.read_text(encoding="utf-8") == "<!doctype html><html><body>world</body></html>"
    assert not old_path.exists()
    assert result["type"] == "file_change_set"
    assert result["operation_count"] == 3
    assert result["changed_file_count"] == 2
    assert str(page_path) in result["created_paths"]
    assert str(old_path) in result["deleted_paths"]
    assert result["roles"] == ["deliverable", "verification"]
    assert result["verification_strength"] == "standard"


@pytest.mark.asyncio
async def test_apply_changes_preflights_before_writing_any_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "created.txt"
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    with pytest.raises(ValueError, match="old_text not found"):
        await apply_changes(
            {
                "operations": [
                    {"type": "create_file", "path": str(target), "content": "new file"},
                    {
                        "type": "replace_text",
                        "path": str(target),
                        "old_text": "missing",
                        "new_text": "replacement",
                    },
                ],
            },
            context,
        )

    assert not target.exists()


@pytest.mark.asyncio
async def test_apply_changes_rejects_truncated_html_without_overwriting(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / "viewer.html"
    original = "<!doctype html><html><body>ok</body></html>"
    path.write_text(original, encoding="utf-8")
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    with pytest.raises(ValueError, match="refusing incomplete .html change"):
        await apply_changes(
            {
                "operations": [
                    {"type": "overwrite_file", "path": str(path), "content": "<!doctype html><html><body>bad"}
                ],
            },
            context,
        )

    assert path.read_text(encoding="utf-8") == original


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


@pytest.mark.asyncio
async def test_text_draft_can_append_and_finalize_html_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    created = await create_text_draft(
        {
            "title": "Homepage",
            "path_hint": str(workspace / "index.html"),
            "language": "html",
        },
        context,
    )
    draft_id = created["draft_id"]
    await append_text_chunk(
        {"draft_id": draft_id, "content": "<!doctype html><html><body>\n"},
        context,
    )
    await append_text_chunk(
        {"draft_id": draft_id, "content": "<main>ok</main>\n</body></html>"},
        context,
    )

    inspected = await inspect_text_draft({"draft_id": draft_id}, context)
    finalized = await finalize_text_file(
        {
            "draft_id": draft_id,
            "output_path": str(workspace / "index.html"),
        },
        context,
    )

    path = Path(finalized["path"])
    assert inspected["stats"]["chunk_count"] == 2
    assert finalized["validation"]["valid"] is True
    assert finalized["draft_stats"]["text_chars"] == len(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    assert path.read_text(encoding="utf-8").endswith("</body></html>")


@pytest.mark.asyncio
async def test_text_draft_stores_body_in_file_not_metadata_json(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    created = await create_text_draft(
        {
            "title": "Large CSS",
            "path_hint": str(workspace / "styles.css"),
            "language": "css",
        },
        context,
    )
    content = ".panel { color: #234; }\n" * 200
    await append_text_chunk(
        {"draft_id": created["draft_id"], "content": content, "sequence": 1},
        context,
    )

    draft_root = tmp_path / "task" / "runtime-data" / "text-artifact-drafts"
    metadata = json.loads((draft_root / f"{created['draft_id']}.json").read_text(encoding="utf-8"))
    body = draft_root / f"{created['draft_id']}.txt"

    assert body.read_text(encoding="utf-8") == content
    assert metadata["chunks"][0]["storage"] == "file"
    assert "content" not in metadata["chunks"][0]
    assert metadata["text_chars"] == len(content)


@pytest.mark.asyncio
async def test_text_draft_rejects_invalid_json_on_finalize(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "config.json"
    context = FakeContext(PathGuard([workspace]), tmp_path / "task")

    created = await create_text_draft(
        {
            "title": "Bad JSON",
            "path_hint": str(target),
            "content": '{"missing": ',
        },
        context,
    )

    with pytest.raises(ValueError, match="invalid json"):
        await finalize_text_file({"draft_id": created["draft_id"], "output_path": str(target)}, context)

    assert not target.exists()
