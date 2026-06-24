from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from runtime.security import PathGuard
from runtime.skills.code import apply_patch, edit_file


@dataclass
class FakeContext:
    path_guard: PathGuard
    backups: list[Path] = field(default_factory=list)

    def log(self, level: str, message: str, data: dict | None = None) -> None:
        return None

    def backup_file(self, path: Path) -> None:
        self.backups.append(path)


@pytest.mark.asyncio
async def test_apply_patch_updates_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "app.js"
    path.write_text("const value = 1;\nconsole.log(value);\n", encoding="utf-8")
    context = FakeContext(PathGuard([tmp_path]))

    result = await apply_patch(
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Update File: app.js\n"
                "@@\n"
                "-const value = 1;\n"
                "+const value = 2;\n"
                " console.log(value);\n"
                "*** End Patch"
            ),
        },
        context,
    )

    assert path.read_text(encoding="utf-8") == "const value = 2;\nconsole.log(value);\n"
    assert result["paths"] == [str(path)]
    assert result["hunk_count"] == 1
    assert context.backups == [path]


@pytest.mark.asyncio
async def test_apply_patch_adds_complete_file(tmp_path: Path) -> None:
    context = FakeContext(PathGuard([tmp_path]))

    result = await apply_patch(
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: notes.md\n"
                "+# Notes\n"
                "+\n"
                "+Done.\n"
                "*** End Patch"
            ),
        },
        context,
    )

    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# Notes\n\nDone.\n"
    assert result["file_count"] == 1


@pytest.mark.asyncio
async def test_apply_patch_rejects_incomplete_patch_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "app.js"
    path.write_text("const value = 1;\n", encoding="utf-8")
    context = FakeContext(PathGuard([tmp_path]))

    with pytest.raises(ValueError, match="must start"):
        await apply_patch(
            {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: app.js\n"
                    "@@\n"
                    "-const value = 1;\n"
                    "+const value = 2;\n"
                ),
            },
            context,
        )

    assert path.read_text(encoding="utf-8") == "const value = 1;\n"
    assert context.backups == []


@pytest.mark.asyncio
async def test_apply_patch_validates_all_files_before_writing(tmp_path: Path) -> None:
    first = tmp_path / "first.js"
    first.write_text("const first = 1;\n", encoding="utf-8")
    context = FakeContext(PathGuard([tmp_path]))

    with pytest.raises(ValueError, match="file not found"):
        await apply_patch(
            {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: first.js\n"
                    "@@\n"
                    "-const first = 1;\n"
                    "+const first = 2;\n"
                    "*** Update File: missing.js\n"
                    "@@\n"
                    "-const missing = 1;\n"
                    "+const missing = 2;\n"
                    "*** End Patch"
                ),
            },
            context,
        )

    assert first.read_text(encoding="utf-8") == "const first = 1;\n"
    assert context.backups == []


@pytest.mark.asyncio
async def test_edit_file_preserves_gb18030_when_non_ascii_appears_after_probe_window(tmp_path: Path) -> None:
    path = tmp_path / "app.js"
    prefix = "const filler = '" + ("a" * 9000) + "';\n"
    original = prefix + "const label = '正在加载施工机械模型.';\n"
    path.write_bytes(original.encode("gb18030"))
    context = FakeContext(PathGuard([tmp_path]))

    result = await edit_file(
        {
            "path": str(path),
            "edits": [
                {
                    "old_text": "const label = '正在加载施工机械模型.';",
                    "new_text": "const label = '施工机械模型已加载.';",
                }
            ],
        },
        context,
    )

    raw = path.read_bytes()
    assert "施工机械模型已加载" in raw.decode("gb18030")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert result["encoding"] == "gb18030"
