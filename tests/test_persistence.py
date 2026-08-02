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


def test_conversation_store_compacts_duplicate_run_evidence_in_assistant_metadata() -> None:
    storage = MemoryDocumentStorage()
    store = ConversationStore(storage=storage)
    conversation = store.create("workspace-1", "hello")
    pack = {
        "schema_version": "context_pack.v1",
        "kind": "context_pack",
        "phase": "summary",
        "records": [{"kind": "run_result"}],
        "ledger": {"schema_version": "context_ledger.v1", "record_count": 1},
    }
    metadata = {
        "run_id": "run-1",
        "task_contract": {"goal": "create viewer", "intent": "write_required"},
        "run_result": {"status": "partial", "changed_paths": ["viewer.html"]},
        "tool_events": [{"tool": "filesystem.write_file", "status": "success"}],
        "context_pack": pack,
        "context_packs": [pack],
        "capability_snapshot": {
            "schema_version": "capability_snapshot.v1",
            "tool_count": 48,
            "available_tool_count": 45,
            "unavailable_tool_ids": ["preview.capture_file"],
            "capabilities": [{"id": "large-record-that-belongs-in-run-events"}],
            "available_evidence_kinds": ["runtime", "visual"],
        },
        "capability_preflight": {
            "schema_version": "capability_preflight.v2",
            "ok": True,
            "target_capability_ids": ["code.text_write"],
            "advisories": [{"code": "visual_unavailable", "message": "no screenshot"}],
            "evidence_affordances": [{"tool_ids": ["preview.capture_file"]}],
        },
        "completion_decisions": [{"action": "final_answer_candidate"}],
        "task_route_evidence": {"kind": "task_route_evidence", "proposal_count": 1},
    }

    message = store.add_message(conversation.id, "assistant", "done", metadata)

    assert message.metadata["run_id"] == "run-1"
    assert message.metadata["task_contract"] == metadata["task_contract"]
    assert message.metadata["run_result"] == metadata["run_result"]
    assert message.metadata["tool_events"] == metadata["tool_events"]
    assert "context_pack" not in message.metadata
    assert "context_packs" not in message.metadata
    assert message.metadata["context_pack_summary"]["phase"] == "summary"
    assert "capability_snapshot" not in message.metadata
    assert message.metadata["capability_snapshot_summary"]["tool_count"] == 48
    assert "capability_preflight" not in message.metadata
    assert message.metadata["capability_preflight_summary"]["advisory_count"] == 1
    assert "completion_decisions" not in message.metadata
    assert "task_route_evidence" not in message.metadata


def test_conversation_store_compacts_legacy_assistant_metadata_on_load() -> None:
    storage = MemoryDocumentStorage({
        "conversations": [{
            "id": "conversation-1",
            "workspace_id": "workspace-1",
            "title": "legacy",
            "messages": [{
                "id": "message-1",
                "role": "assistant",
                "content": "done",
                "metadata": {
                    "context_packs": [{
                        "schema_version": "context_pack.v1",
                        "kind": "context_pack",
                        "phase": "execution",
                        "records": [],
                        "ledger": {},
                    }],
                    "capability_snapshot": {
                        "schema_version": "capability_snapshot.v1",
                        "tool_count": 50,
                        "available_tool_count": 50,
                    },
                },
            }],
        }],
    })

    store = ConversationStore(storage=storage)
    metadata = store.get("conversation-1").messages[0].metadata

    assert "context_packs" not in metadata
    assert metadata["context_pack_summary"]["phase"] == "execution"
    assert metadata["capability_snapshot_summary"]["tool_count"] == 50
