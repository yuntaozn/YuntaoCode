from runtime.run_store import RunStore
from runtime.run_workbench import build_run_workbench


def test_build_run_workbench_presents_artifacts_risks_and_timeline(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv-1",
        workspace_id="workspace-1",
        mode="terminal",
        user_content="Create a 3D model viewer",
        task_id="task-1",
    )
    store.record_event(run.id, {
        "event": "task_contract",
        "contract": {
            "goal": "Create a 3D model viewer",
            "intent": "write_required",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "success_conditions": ["target_deliverable_success", "final_answer_with_evidence"],
        },
    })
    store.record_event(run.id, {
        "event": "plan",
        "plan": {
            "title": "Build viewer",
            "state": "running",
            "steps": [
                {"title": "Write HTML", "status": "done", "tool_hint": "filesystem.finalize_text_file"}
            ],
        },
    })
    store.record_event(run.id, {
        "event": "status",
        "status": "thinking",
        "message": "model is preparing the file",
        "time": "2026-06-25T00:00:01+00:00",
    })
    store.record_event(run.id, {
        "event": "tool",
        "tool": "filesystem.finalize_text_file",
        "status": "success",
        "time": "2026-06-25T00:00:02+00:00",
        "input": {"output_path": "viewer.html"},
        "output": {
            "path": "viewer.html",
            "size": 4096,
            "artifact_kind": "text_file",
            "validation": {"valid": True, "text_chars": 3200, "line_count": 80},
        },
    })
    store.record_event(run.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "partial",
            "artifacts": [
                {
                    "kind": "text_file",
                    "path": "viewer.html",
                    "tool": "filesystem.finalize_text_file",
                    "status": "success",
                    "size": 4096,
                    "validation": {"valid": True, "text_chars": 3200},
                }
            ],
            "risks": ["write_not_verified"],
            "verification_evidence": [
                {"tool": "filesystem.read_text_preview", "path": "viewer.html", "strength": "weak"}
            ],
        },
    })
    store.record_event(run.id, {
        "event": "completion_decision",
        "decision": {
            "schema_version": "completion_decision.v1",
            "action": "continue_with_tools",
            "source": "model_observed_behavior",
            "tool_call_count": 1,
            "result_status": "partial",
        },
    })

    workbench = build_run_workbench(store.get(run.id))

    assert workbench["schema_version"] == "run_workbench.v1"
    assert workbench["kind"] == "run_workbench"
    assert workbench["run"]["id"] == run.id
    assert workbench["task"]["goal"] == "Create a 3D model viewer"
    assert workbench["task"]["requires_write"] is True
    assert workbench["status"]["result_status"] == "partial"
    assert workbench["artifacts"] == [
        {
            "kind": "text_file",
            "path": "viewer.html",
            "tool": "filesystem.finalize_text_file",
            "status": "success",
            "size": 4096,
            "validation": {"valid": True, "text_chars": 3200},
        }
    ]
    assert workbench["verification"][0]["tool"] == "filesystem.read_text_preview"
    assert workbench["risks"][0]["code"] == "write_not_verified"
    assert workbench["plan"]["steps"][0]["title"] == "Write HTML"
    assert workbench["completion_decisions"][0]["action"] == "continue_with_tools"
    assert [item["kind"] for item in workbench["timeline"]] == ["status", "tool"]
    assert workbench["actions"]["can_continue"] is True
    assert workbench["actions"]["can_replay"] is True


def test_build_run_workbench_falls_back_to_written_paths_for_old_results(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv-1",
        workspace_id="workspace-1",
        mode="terminal",
        user_content="Write report",
    )
    store.record_event(run.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "success",
            "written_paths": ["report.md"],
            "risks": [],
        },
    })

    workbench = build_run_workbench(store.get(run.id))

    assert workbench["artifacts"] == [
        {"kind": "file", "path": "report.md", "tool": "", "status": "observed"}
    ]
