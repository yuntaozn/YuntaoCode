from __future__ import annotations

import pytest

from runtime.core.skill_evolution import (
    SkillCandidate,
    SkillReplayResult,
    can_transition,
    replay_fixture_from_runbook,
    skill_readiness,
)


def test_skill_candidate_transition_rules() -> None:
    candidate = SkillCandidate(id="skill-1", name="Document translator")

    assert can_transition("draft", "testing")
    assert candidate.transition("testing").state == "testing"
    assert not can_transition("enabled", "draft")

    with pytest.raises(ValueError):
        candidate.transition("enabled")


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


def test_skill_readiness_requires_tested_candidate_and_no_failures() -> None:
    candidate = SkillCandidate(id="skill-1", name="Document translator", state="tested")
    results = [
        SkillReplayResult(id="r1", candidate_id="skill-1", fixture_id="f1", status="passed", score=0.95),
        SkillReplayResult(id="r2", candidate_id="other", fixture_id="f1", status="failed", score=0.0),
    ]

    readiness = skill_readiness(candidate, results)

    assert readiness["fixture_count"] == 1
    assert readiness["passed"] == 1
    assert readiness["average_score"] == 0.95
    assert readiness["promotable"] is True
    assert readiness["boundary"] == "manual_enable_required"


def test_skill_readiness_blocks_failures_and_drafts() -> None:
    draft = SkillCandidate(id="skill-1", name="Document translator", state="draft")
    failed = SkillReplayResult(id="r1", candidate_id="skill-1", fixture_id="f1", status="failed", score=0.2)

    assert skill_readiness(draft, [failed])["promotable"] is False
    assert skill_readiness(draft.transition("testing").transition("tested"), [failed])["promotable"] is False
