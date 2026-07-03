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
        "event": "workspace_snapshot",
        "snapshot": {
            "schema_version": "workspace_snapshot.v1",
            "name": "viewer-demo",
            "exists": True,
            "readable": True,
            "file_count": 3,
            "directory_count": 2,
            "extension_counts": {".html": 1, ".js": 1, ".glb": 1},
        },
    })
    store.record_event(run.id, {
        "event": "context_pack",
        "pack": {
            "schema_version": "context_pack.v1",
            "kind": "context_pack",
            "phase": "task_contract",
            "records": [
                {"kind": "user_intent", "content": "Create a 3D model viewer"},
                {"kind": "workspace_summary", "content": "Workspace viewer-demo"},
            ],
            "ledger": {
                "schema_version": "context_ledger.v1",
                "record_count": 2,
                "records": [
                    {"kind": "user_intent", "source_type": "user_message", "trust": "user_provided"},
                    {"kind": "workspace_summary", "source_type": "runtime_event", "trust": "runtime_fact"},
                ],
            },
        },
    })
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
        "event": "capability_snapshot",
        "snapshot": {
            "available_tool_ids": ["filesystem.finalize_text_file", "preview.capture_local_html"],
            "unavailable_tool_ids": ["mcp_blender.get_scene_info"],
        },
        "preflight": {
            "ok": True,
            "target_capability_ids": ["code.text_write"],
            "preferred_tool_ids": ["filesystem.finalize_text_file"],
            "visual_verification_tool_ids": ["preview.capture_local_html"],
            "advisories": [{
                "code": "tool_degraded",
                "message": "An optional external-state provider is degraded.",
                "tool_id": "mcp_blender.get_scene_info",
                "recommended_action": "restart",
            }],
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
        "event": "visual_context",
        "records": [{
            "tool": "preview.capture_local_html",
            "source_type": "local_html",
            "source_path": "viewer.html",
            "path": str(tmp_path / "viewer.png"),
            "artifact_kind": "screenshot",
            "format": "png",
            "width": 1024,
            "height": 768,
            "size": 4096,
            "model_context_eligible": True,
        }],
        "message": "visual evidence added to model context",
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
    assert workbench["context_pack"]["phase"] == "task_contract"
    assert workbench["context_pack"]["ledger"]["record_count"] == 2
    assert workbench["workspace"]["name"] == "viewer-demo"
    assert workbench["workspace"]["extension_counts"][".glb"] == 1
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
    assert workbench["audit"]["counts"]["artifacts"] == 1
    assert workbench["audit"]["counts"]["changed_paths"] == 1
    assert workbench["audit"]["counts"]["verification"] == 1
    assert workbench["audit"]["counts"]["runtime_advisories"] == 1
    assert workbench["audit"]["counts"]["visual_context"] == 1
    assert workbench["audit"]["flags"]["has_changed_paths"] is True
    assert workbench["audit"]["changed_paths"][0]["path"] == "viewer.html"
    assert workbench["audit"]["verification"]["strengths"] == ["weak"]
    assert workbench["context_evidence"]["context_pack_count"] == 1
    assert workbench["context_evidence"]["capability"]["target_capability_ids"] == ["code.text_write"]
    assert workbench["context_evidence"]["capability"]["advisory_count"] == 1
    assert workbench["context_evidence"]["runtime_advisories"][0]["code"] == "tool_degraded"
    assert workbench["context_evidence"]["visual_context"][0]["tool"] == "preview.capture_local_html"
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
