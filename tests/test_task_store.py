import json

from runtime.task_store import TaskStore, ToolTaskRecord, ToolTaskStore


def test_task_store_public_records_are_marked_as_tool_tasks(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    task = store.create("filesystem.scan_folder", {"path": "."})

    public = task.to_public_dict()

    assert public["schema_version"] == "0.1"
    assert public["record_kind"] == "tool_task"
    assert public["kind"] == "tool_task"
    assert public["tool"] == "filesystem.scan_folder"
    assert public["tool_id"] == "filesystem.scan_folder"


def test_task_store_persists_schema_version_and_kind(tmp_path) -> None:
    path = tmp_path / "tasks.json"
    store = TaskStore(path)

    store.create("filesystem.scan_folder", {"path": "."})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "0.1"
    assert data["record_kind"] == "tool_task_store"
    assert data["tasks"][0]["record_kind"] == "tool_task"


def test_tool_task_aliases_preserve_backwards_compatibility() -> None:
    assert ToolTaskRecord.__name__ == "TaskRecord"
    assert ToolTaskStore.__name__ == "TaskStore"


def test_task_store_marks_running_tasks_interrupted_on_startup(tmp_path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "record_kind": "tool_task_store",
                "tasks": [
                    {
                        "id": "task-1",
                        "tool": "document.translate_docx",
                        "input": {"path": "source.docx"},
                        "status": "running",
                        "created_at": "2026-06-02T00:00:00+00:00",
                        "updated_at": "2026-06-02T00:00:00+00:00",
                        "logs": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = TaskStore(path)
    task = store.get("task-1")

    assert task is not None
    assert task.status == "failure"
    assert task.error == "task interrupted before runtime startup"
    assert task.logs[-1]["data"]["reason"] == "runtime_startup_recovery"
