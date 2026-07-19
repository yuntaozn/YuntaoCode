from __future__ import annotations

from runtime.core.replay_fixture import replay_fixture_from_runbook


def test_replay_fixture_from_runbook_preserves_task_evidence() -> None:
    runbook = {
        "id": "runbook-1",
        "run": {
            "id": "run-1",
            "task_id": "task-1",
            "workspace_id": "workspace-1",
            "conversation_id": "conversation-1",
            "goal": "Translate the full document",
        },
        "task_contract": {
            "schema_version": "task_contract.v1",
            "requires_write": True,
        },
        "result": {
            "artifacts": [
                {"kind": "file", "path": "translated.docx"},
            ],
        },
        "verification_evidence": [
            {"kind": "file_exists", "path": "translated.docx"},
        ],
    }

    fixture = replay_fixture_from_runbook("fixture-1", runbook)

    assert fixture.source_run_id == "run-1"
    assert fixture.runbook_id == "runbook-1"
    assert fixture.goal == "Translate the full document"
    assert fixture.task_contract["requires_write"] is True
    assert fixture.expected_artifacts == ({"kind": "file", "path": "translated.docx"},)
    assert fixture.verification_evidence == ({"kind": "file_exists", "path": "translated.docx"},)
    assert fixture.to_dict()["schema_version"] == "replay_fixture.v1"
