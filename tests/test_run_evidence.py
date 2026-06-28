from runtime.run_evidence import build_run_evidence
from runtime.run_store import RunStore


def test_build_run_evidence_collects_runtime_facts_once(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="Create viewer.html",
        task_id="task-1",
    )
    store.record_event(run.id, {
        "event": "workspace_snapshot",
        "snapshot": {
            "schema_version": "workspace_snapshot.v1",
            "name": "demo",
            "path": str(tmp_path),
            "exists": True,
            "readable": True,
            "file_count": 2,
            "directory_count": 1,
            "extension_counts": {".html": 1, ".js": 1},
        },
    })
    store.record_event(run.id, {
        "event": "task_contract",
        "contract": {
            "requires_write": True,
            "requires_verification": True,
            "capability_ids": ["code.text_write"],
            "deliverables": [{"kind": "file", "path_hint": "viewer.html"}],
        },
    })
    store.record_event(run.id, {
        "event": "capability_snapshot",
        "snapshot": {"available_tool_ids": ["filesystem.write_file"], "unavailable_tool_ids": []},
        "preflight": {"ok": True, "target_capability_ids": ["code.text_write"]},
    })
    store.record_event(run.id, {
        "event": "tool",
        "tool": "filesystem.write_file",
        "status": "success",
        "declared_capability": "code.text_write",
        "declared_effects": ["file_write"],
        "declared_roles": ["deliverable"],
        "input": {"path": "viewer.html"},
        "output": {
            "path": "viewer.html",
            "artifacts": ["file"],
            "effects": ["file_write"],
            "roles": ["deliverable"],
        },
    })
    store.record_event(run.id, {
        "event": "checkpoint",
        "checkpoint": {"id": "checkpoint-1", "state": "partial"},
    })
    store.record_event(run.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "partial",
            "risks": ["write_not_verified"],
            "verification_evidence": [],
        },
    })
    store.record_event(run.id, {
        "event": "completion_decision",
        "decision": {
            "schema_version": "completion_decision.v1",
            "action": "final_answer_candidate",
            "source": "model_observed_behavior",
        },
    })

    current = store.get(run.id)
    evidence = build_run_evidence(current)

    assert evidence["schema_version"] == "run_evidence.v1"
    assert evidence["kind"] == "run_evidence"
    assert evidence["run"]["id"] == run.id
    assert evidence["run"]["task_id"] == "task-1"
    assert evidence["workspace_snapshot"]["name"] == "demo"
    assert evidence["workspace_snapshot"]["extension_counts"][".html"] == 1
    assert evidence["task_contract"]["capability_ids"] == ["code.text_write"]
    assert evidence["trace"]["schema_version"] == "run_trace_summary.v1"
    assert evidence["trace"]["result_status"] == "partial"
    assert evidence["capability_evidence"]["observed_capability_ids"] == ["code.text_write"]
    assert evidence["capability_snapshot"]["target_capability_ids"] == ["code.text_write"]
    assert evidence["tool_steps"][0]["declared_capability"] == "code.text_write"
    assert evidence["completion_decisions"][0]["action"] == "final_answer_candidate"
    assert evidence["risks"] == ["write_not_verified"]
    assert evidence["recovery"]["checkpoint_count"] == 1
    assert evidence["recovery"]["latest_checkpoint"]["id"] == "checkpoint-1"
    assert evidence["replay_seed"]["source_run_id"] == run.id
    assert evidence["replay_seed"]["boundary"] == "manual_start_required"


def test_build_run_evidence_keeps_result_status_separate_from_done_status(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="Analyze current project",
        task_id="task-1",
    )
    store.record_event(run.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "no_tool_activity",
            "risks": [],
        },
    })
    store.record_event(run.id, {
        "event": "done",
        "run_status": "success",
    })

    current = store.get(run.id)
    evidence = build_run_evidence(current)

    assert evidence["trace"]["run_status"] == "success"
    assert evidence["trace"]["result_status"] == "no_tool_activity"
