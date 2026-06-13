from __future__ import annotations

from types import SimpleNamespace

import pytest
import tornado.web

from runtime.api.memories import _is_workspace_scope, _validate_memory_scope
from runtime.memory_service import build_memory_prompt_from_store
from runtime.memory_store import MemoryItem, MemoryStore
from runtime.skills.memory import _memory_recall_handler, _memory_save_handler


def test_memory_store_lists_global_and_current_workspace_only(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memories.json")
    global_memory = store.add(MemoryItem(id="global", text="User prefers concise replies"))
    current_memory = store.add(
        MemoryItem(
            id="ws-1",
            text="This project uses SQLite for run history",
            scope="workspace",
            workspace_id="workspace-1",
        )
    )
    other_memory = store.add(
        MemoryItem(
            id="ws-2",
            text="Other project uses Postgres",
            scope="workspace",
            workspace_id="workspace-2",
        )
    )

    applicable_ids = {memory.id for memory in store.list_applicable("workspace-1")}

    assert global_memory.id in applicable_ids
    assert current_memory.id in applicable_ids
    assert other_memory.id not in applicable_ids


def test_memory_store_global_scope_clears_workspace_id(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memories.json")
    saved = store.add(
        MemoryItem(
            id="memory",
            text="User prefers Chinese replies",
            scope="global",
            workspace_id="workspace-1",
        )
    )

    assert saved.scope == "global"
    assert saved.workspace_id == ""


def test_memory_store_load_clears_workspace_id_for_global_items(tmp_path) -> None:
    store_path = tmp_path / "memories.json"
    store_path.write_text(
        (
            '{"version": 1, "memories": ['
            '{"id": "memory", "text": "remember this", "scope": "global", '
            '"workspace_id": "workspace-1"}'
            "]}"
        ),
        encoding="utf-8",
    )

    loaded = MemoryStore(store_path).get("memory")

    assert loaded is not None
    assert loaded.scope == "global"
    assert loaded.workspace_id == ""


def test_workspace_scope_detection() -> None:
    assert _is_workspace_scope("workspace") is True
    assert _is_workspace_scope("project") is True
    assert _is_workspace_scope("global") is False
    assert _is_workspace_scope("") is False


def test_memory_api_scope_validation_requires_workspace_id() -> None:
    handler = SimpleNamespace(
        runtime=SimpleNamespace(
            workspaces=SimpleNamespace(get=lambda _workspace_id: object()),
        )
    )

    with pytest.raises(tornado.web.HTTPError) as exc_info:
        _validate_memory_scope(handler, "workspace", "")

    assert exc_info.value.status_code == 400


def test_memory_api_scope_validation_rejects_unknown_workspace() -> None:
    handler = SimpleNamespace(
        runtime=SimpleNamespace(
            workspaces=SimpleNamespace(get=lambda _workspace_id: None),
        )
    )

    with pytest.raises(tornado.web.HTTPError) as exc_info:
        _validate_memory_scope(handler, "workspace", "missing-workspace")

    assert exc_info.value.status_code == 404


def test_memory_prompt_filters_other_workspace_memories(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memories.json")
    store.add(MemoryItem(id="global", text="User prefers concise replies"))
    store.add(
        MemoryItem(
            id="current",
            text="Current workspace stores attachments under local app data",
            scope="workspace",
            workspace_id="workspace-1",
        )
    )
    store.add(
        MemoryItem(
            id="other",
            text="Other workspace secret project detail",
            scope="workspace",
            workspace_id="workspace-2",
        )
    )

    prompt, used_ids = build_memory_prompt_from_store(store, workspace_id="workspace-1")

    assert "User prefers concise replies" in prompt
    assert "Current workspace stores attachments" in prompt
    assert "Other workspace secret" not in prompt
    assert set(used_ids) == {"global", "current"}


@pytest.mark.asyncio
async def test_memory_save_uses_workspace_scope_for_project_tags(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memories.json")
    context = SimpleNamespace(
        settings=SimpleNamespace(memory_store=store),
        workspace_id="workspace-1",
    )

    result = await _memory_save_handler(
        {
            "text": "This project uses SQLite for run history",
            "tags": "project, tech_stack",
        },
        context,
    )

    assert result["success"] is True
    assert result["scope"] == "workspace"
    assert result["workspace_id"] == "workspace-1"
    saved = store.get(result["id"])
    assert saved is not None
    assert saved.scope == "workspace"
    assert saved.workspace_id == "workspace-1"


@pytest.mark.asyncio
async def test_memory_recall_filters_to_current_workspace(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memories.json")
    store.add(MemoryItem(id="global", text="User prefers concise replies"))
    store.add(
        MemoryItem(
            id="current",
            text="Current workspace has document tools",
            scope="workspace",
            workspace_id="workspace-1",
        )
    )
    store.add(
        MemoryItem(
            id="other",
            text="Other workspace should not appear",
            scope="workspace",
            workspace_id="workspace-2",
        )
    )
    context = SimpleNamespace(
        settings=SimpleNamespace(memory_store=store),
        workspace_id="workspace-1",
    )

    result = await _memory_recall_handler({"limit": 10}, context)
    recalled_ids = {memory["id"] for memory in result["memories"]}

    assert recalled_ids == {"global", "current"}
