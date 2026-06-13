from __future__ import annotations

from types import SimpleNamespace

from runtime.skill_sample_export import build_skill_sample_export


def test_skill_sample_export_contains_fixture_without_full_runbook() -> None:
    run = SimpleNamespace(
        id="run-1",
        conversation_id="conversation-1",
        workspace_id="workspace-1",
        task_id="task-1",
        parent_run_id="",
        source_run_id="",
        attempt=1,
        resume_from_checkpoint_id="",
        mode="terminal",
        status="success",
        stage="done",
        user_content="Translate the full document",
        created_at="2026-06-13T00:00:00Z",
        updated_at="2026-06-13T00:01:00Z",
        events=[
            {
                "event": "task_contract",
                "contract": {
                    "schema_version": "task_contract.v1",
                    "requires_write": True,
                },
            },
            {
                "event": "result",
                "result": {
                    "status": "success",
                    "artifacts": [
                        {"kind": "file", "path": "translated.docx"},
                    ],
                    "verification_evidence": [
                        {"kind": "file_exists", "path": "translated.docx"},
                    ],
                },
            },
        ],
    )

    exported = build_skill_sample_export(run)

    assert exported["schema_version"] == "skill_sample_export.v1"
    assert exported["kind"] == "skill_replay_fixture_export"
    assert exported["source"]["run_id"] == "run-1"
    assert exported["fixture"]["source_run_id"] == "run-1"
    assert exported["fixture"]["goal"] == "Translate the full document"
    assert exported["fixture"]["expected_artifacts"] == [{"kind": "file", "path": "translated.docx"}]
    assert exported["sample_policy"]["contains_full_runbook"] is False
    assert exported["sample_policy"]["contains_file_contents"] is False
    assert "runbook" not in exported
