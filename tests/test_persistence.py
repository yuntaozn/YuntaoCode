from pathlib import Path
from typing import Any

from runtime.conversation_store import ConversationStore
from runtime.memory_store import MemoryItem, MemoryStore
from runtime.persistence import AtomicJsonDocumentStorage
from runtime.run_store import RunStore
from runtime.task_store import TaskStore


class MemoryDocumentStorage:
    def __init__(self, value: dict[str, Any] | None = None) -> None:
        self.path: Path | None = None
        self.value = value
        self.save_count = 0

    def load(self) -> dict[str, Any] | None:
        return self.value

    def save(self, payload: dict[str, Any]) -> None:
        self.value = payload
        self.save_count += 1


def test_atomic_json_document_storage_round_trip(tmp_path) -> None:
    path = tmp_path / "runtime-data.json"
    storage = AtomicJsonDocumentStorage(path)

    storage.save({"message": "hello", "items": [1, 2]})
    storage.save({"message": "updated", "items": [3]})

    assert storage.load() == {"message": "updated", "items": [3]}
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_json_document_storage_ignores_invalid_documents(tmp_path) -> None:
    path = tmp_path / "runtime-data.json"
    path.write_text("{not json", encoding="utf-8")

    assert AtomicJsonDocumentStorage(path).load() is None


def test_core_stores_accept_document_storage_backends() -> None:
    task_storage = MemoryDocumentStorage()
    task_store = TaskStore(storage=task_storage)
    task = task_store.create("filesystem.scan_folder", {"path": "."})

    run_storage = MemoryDocumentStorage()
    run_store = RunStore(storage=run_storage)
    run = run_store.create(
        conversation_id="conversation-1",
        workspace_id="workspace-1",
        mode="terminal",
        user_content="hello",
    )

    conversation_storage = MemoryDocumentStorage()
    conversation_store = ConversationStore(storage=conversation_storage)
    conversation = conversation_store.create("workspace-1", "hello")
    message = conversation_store.add_message(conversation.id, "user", "hello")

    memory_storage = MemoryDocumentStorage()
    memory_store = MemoryStore(storage=memory_storage)
    memory = memory_store.add(MemoryItem(id="memory-1", text="remember this"))

    assert task_storage.value["tasks"][0]["id"] == task.id
    assert run_storage.value["runs"][0]["id"] == run.id
    assert conversation_storage.value["conversations"][0]["id"] == conversation.id
    assert conversation_storage.value["conversations"][0]["messages"][0]["id"] == message.id
    assert memory_storage.value["memories"][0]["id"] == memory.id
