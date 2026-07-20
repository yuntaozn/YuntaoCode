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
        "event": "context_pack",
        "pack": {
            "schema_version": "context_pack.v1",
            "kind": "context_pack",
            "phase": "task_contract",
            "records": [
                {"kind": "user_intent", "content": "Create viewer.html"},
                {"kind": "workspace_summary", "content": "Workspace demo"},
            ],
            "ledger": {
                "schema_version": "context_ledger.v1",
                "record_count": 2,
                "records": [
                    {"kind": "user_intent", "source_type": "user_message"},
                    {"kind": "workspace_summary", "source_type": "runtime_event"},
                ],
            },
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
        "snapshot": {
            "available_tool_ids": ["filesystem.write_file", "shell.run_command"],
            "unavailable_tool_ids": [],
            "available_evidence_kinds": ["content", "runtime", "verification"],
            "evidence_affordances": [
                {
                    "kind": "runtime",
                    "tool_ids": ["shell.run_command"],
                    "verification_strengths": ["standard"],
                }
            ],
        },
        "preflight": {
            "ok": True,
            "target_capability_ids": ["code.text_write"],
            "preferred_tool_ids": ["filesystem.write_file"],
            "visual_verification_tool_ids": ["preview.capture_local_html"],
            "evidence_affordances": [
                {
                    "kind": "runtime",
                    "tool_ids": ["shell.run_command"],
                    "verification_strengths": ["standard"],
                }
            ],
            "advisories": [{
                "code": "visual_verification_path_uncertain",
                "message": "visual verification route is uncertain",
            }],
        },
    })
    store.record_event(run.id, {
        "event": "context_pack",
        "pack": {
            "schema_version": "context_pack.v1",
            "kind": "context_pack",
            "phase": "planning",
            "records": [
                {"kind": "user_intent", "content": "Create viewer.html"},
                {"kind": "task_contract", "content": "Current task contract"},
                {"kind": "capability", "content": "Capability boundary facts"},
            ],
            "ledger": {
                "schema_version": "context_ledger.v1",
                "record_count": 3,
                "records": [
                    {"kind": "user_intent", "source_type": "user_message"},
                    {"kind": "task_contract", "source_type": "runtime_event"},
                    {"kind": "capability", "source_type": "runtime_event"},
                ],
            },
        },
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
        "event": "context_pack",
        "pack": {
            "schema_version": "context_pack.v1",
            "kind": "context_pack",
            "phase": "execution",
            "records": [
                {"kind": "task_contract", "content": "Current task contract"},
                {"kind": "capability", "content": "Capability boundary facts"},
                {"kind": "tool_result", "content": "Recent tool result facts"},
                {"kind": "recovery", "content": "Execution state facts"},
            ],
            "ledger": {
                "schema_version": "context_ledger.v1",
                "record_count": 4,
                "records": [
                    {"kind": "task_contract", "source_type": "runtime_event"},
                    {"kind": "capability", "source_type": "runtime_event"},
                    {"kind": "tool_result", "source_type": "run_event"},
                    {"kind": "recovery", "source_type": "runtime_event"},
                ],
            },
        },
    })
    store.record_event(run.id, {
        "event": "checkpoint",
        "checkpoint": {"id": "checkpoint-1", "state": "partial"},
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
            "width": 1280,
            "height": 720,
            "size": 2048,
            "model_context_eligible": True,
        }],
        "message": "visual evidence added to model context",
    })
    store.record_event(run.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "partial",
            "risks": ["write_not_verified"],
            "verification_evidence": [],
            "debug_sessions": [
                {
                    "schema_version": "debug_session.v1",
                    "kind": "debug_session",
                    "source_type": "preview.capture_page",
                    "command": "playwright capture http://127.0.0.1:1234/viewer.html",
                    "executable": "playwright.chromium",
                    "service": {"kind": "browser_preview", "status_code": 200},
                    "diagnostic_count": 0,
                    "status": "success",
                    "has_runtime_errors": False,
                }
            ],
        },
    })
    store.record_event(run.id, {
        "event": "context_pack",
        "pack": {
            "schema_version": "context_pack.v1",
            "kind": "context_pack",
            "phase": "verification",
            "records": [
                {"kind": "task_contract", "content": "Current task contract"},
                {"kind": "capability", "content": "Capability boundary facts"},
                {"kind": "tool_result", "content": "Run result facts"},
            ],
            "ledger": {
                "schema_version": "context_ledger.v1",
                "record_count": 3,
                "records": [
                    {"kind": "task_contract", "source_type": "runtime_event"},
                    {"kind": "capability", "source_type": "runtime_event"},
                    {"kind": "tool_result", "source_type": "run_result"},
                ],
            },
        },
    })
    store.record_event(run.id, {
        "event": "context_pack",
        "pack": {
            "schema_version": "context_pack.v1",
            "kind": "context_pack",
            "phase": "summary",
            "records": [
                {"kind": "user_intent", "content": "Create viewer.html"},
                {"kind": "task_contract", "content": "Current task contract"},
                {"kind": "tool_result", "content": "Run result facts"},
                {"kind": "tool_result", "content": "Final answer candidate preview"},
            ],
            "ledger": {
                "schema_version": "context_ledger.v1",
                "record_count": 4,
                "records": [
                    {"kind": "user_intent", "source_type": "user_message"},
                    {"kind": "task_contract", "source_type": "runtime_event"},
                    {"kind": "tool_result", "source_type": "run_result"},
                    {"kind": "tool_result", "source_type": "assistant_message"},
                ],
            },
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
    assert evidence["context_pack"]["phase"] == "summary"
    assert evidence["context_pack"]["record_kinds"] == [
        "user_intent",
        "task_contract",
        "tool_result",
        "tool_result",
    ]
    assert [item["phase"] for item in evidence["context_packs"]] == [
        "task_contract",
        "planning",
        "execution",
        "verification",
        "summary",
    ]
    assert evidence["workspace_snapshot"]["name"] == "demo"
    assert evidence["workspace_snapshot"]["extension_counts"][".html"] == 1
    assert evidence["task_contract"]["capability_ids"] == ["code.text_write"]
    assert evidence["trace"]["schema_version"] == "run_trace_summary.v1"
    assert evidence["trace"]["result_status"] == "partial"
    assert evidence["capability_evidence"]["observed_capability_ids"] == ["code.text_write"]
    assert evidence["capability_snapshot"]["target_capability_ids"] == ["code.text_write"]
    assert evidence["capability_snapshot"]["advisories"][0]["code"] == "visual_verification_path_uncertain"
    assert evidence["capability_snapshot"]["preferred_tool_ids"] == ["filesystem.write_file"]
    assert evidence["capability_snapshot"]["available_evidence_kinds"] == [
        "content",
        "runtime",
        "verification",
    ]
    assert evidence["capability_snapshot"]["evidence_affordances"][0]["tool_ids"] == [
        "shell.run_command",
    ]
    assert evidence["visual_context"][0]["tool"] == "preview.capture_local_html"
    assert evidence["visual_context"][0]["injected_into_model_context"] is True
    assert evidence["visual_verification"]["schema_version"] == "visual_verification.v1"
    assert evidence["visual_verification"]["counts"]["model_context_records"] == 1
    assert evidence["visual_verification"]["flags"]["model_context_injected"] is True
    assert evidence["debug_audit"]["schema_version"] == "debug_audit.v1"
    assert evidence["debug_audit"]["counts"]["preview_sessions"] == 1
    assert evidence["debug_audit"]["flags"]["has_preview_service"] is True
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


def test_run_evidence_keeps_representative_context_packs_for_long_runs(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        mode="terminal",
        user_content="Long task",
        task_id="task-1",
    )
    for phase in ("task_contract", "planning"):
        store.record_event(run.id, {
            "event": "context_pack",
            "pack": {
                "schema_version": "context_pack.v1",
                "kind": "context_pack",
                "phase": phase,
                "records": [{"kind": "task_contract", "content": phase}],
                "ledger": {"schema_version": "context_ledger.v1", "records": []},
            },
        })
    for index in range(12):
        store.record_event(run.id, {
            "event": "context_pack",
            "pack": {
                "schema_version": "context_pack.v1",
                "kind": "context_pack",
                "phase": "execution",
                "records": [{"kind": "tool_result", "content": f"round {index}"}],
                "ledger": {"schema_version": "context_ledger.v1", "records": []},
            },
        })
    for phase in ("verification", "summary"):
        store.record_event(run.id, {
            "event": "context_pack",
            "pack": {
                "schema_version": "context_pack.v1",
                "kind": "context_pack",
                "phase": phase,
                "records": [{"kind": "tool_result", "content": phase}],
                "ledger": {"schema_version": "context_ledger.v1", "records": []},
            },
        })

    evidence = build_run_evidence(store.get(run.id))

    phases = [item["phase"] for item in evidence["context_packs"]]
    assert "task_contract" in phases
    assert "planning" in phases
    assert "execution" in phases
    assert "verification" in phases
    assert "summary" in phases
    assert len(phases) <= 8
