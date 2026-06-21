from runtime.evaluation.fixtures import (
    build_evaluation_fixture_export,
    build_evaluation_fixture_from_evidence,
)
from runtime.run_evidence import build_run_evidence
from runtime.run_store import RunStore


def test_evaluation_fixture_export_uses_run_evidence_without_executing_replay(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        task_id="task-1",
        mode="terminal",
        user_content="Create a verified scene",
    )
    store.record_event(run.id, {
        "event": "task_contract",
        "contract": {
            "requires_state_change": True,
            "requires_verification": True,
            "required_verification_modalities": ["visual"],
            "capability_ids": ["mcp.blender"],
            "deliverables": [
                {
                    "kind": "external_state",
                    "description": "Blender scene",
                    "capability_id": "mcp.blender",
                },
            ],
        },
    })
    store.record_event(run.id, {
        "event": "tool",
        "tool": "mcp_blender.execute_blender_code",
        "status": "success",
        "declared_capability": "mcp.blender",
        "declared_effects": ["external_state_change"],
        "declared_roles": ["deliverable"],
        "output": {
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
            "artifacts": ["external_state"],
        },
    })
    store.record_event(run.id, {
        "event": "tool",
        "tool": "mcp_blender.get_viewport_screenshot",
        "status": "success",
        "declared_capability": "mcp.blender",
        "declared_roles": ["verification"],
        "declared_verification_strength": "standard",
        "output": {
            "roles": ["verification"],
            "artifact_kind": "screenshot",
            "path": "D:/workspace/scene.png",
            "verification_strength": "standard",
        },
    })
    store.record_event(run.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "success",
            "artifacts": [{"kind": "external_state", "capability_id": "mcp.blender"}],
            "verification_evidence": [
                {"tool": "mcp_blender.get_viewport_screenshot", "path": "D:/workspace/scene.png"},
            ],
            "required_verification_modalities": ["visual"],
        },
    })

    current = store.get(run.id)
    exported = build_evaluation_fixture_export(current)
    fixture = exported["fixture"]

    assert exported["schema_version"] == "evaluation_fixture_export.v1"
    assert exported["export_policy"]["manual_export"] is True
    assert exported["export_policy"]["executes_replay"] is False
    assert exported["export_policy"]["contains_full_event_log"] is False
    assert fixture["schema_version"] == "evaluation_fixture.v1"
    assert fixture["source_run_id"] == run.id
    assert fixture["goal"] == "Create a verified scene"
    assert fixture["expected"]["result_status"] == "success"
    assert fixture["expected"]["required_verification_modalities"] == ["visual"]
    assert fixture["capabilities"]["requested"] == ["mcp.blender"]
    assert fixture["capabilities"]["observed"] == ["mcp.blender"]
    assert fixture["capabilities"]["artifacts"] == ["external_state", "screenshot"]
    assert fixture["baseline"]["tool_event_count"] == 2
    assert fixture["verification_evidence"][0]["path"] == "D:/workspace/scene.png"
    assert fixture["replay_seed"]["boundary"] == "manual_start_required"
    assert fixture["boundaries"]["manual_replay_required"] is True
    assert fixture["boundaries"]["promotes_skill"] is False


def test_evaluation_fixture_falls_back_to_contract_deliverables(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        task_id="task-1",
        mode="terminal",
        user_content="Create viewer.html",
    )
    store.record_event(run.id, {
        "event": "task_contract",
        "contract": {
            "requires_write": True,
            "deliverables": [{"kind": "file", "path_hint": "viewer.html"}],
        },
    })
    evidence = build_run_evidence(store.get(run.id))

    fixture = build_evaluation_fixture_from_evidence("fixture-1", evidence)

    assert fixture["id"] == "fixture-1"
    assert fixture["expected"]["artifacts"] == [{"kind": "file", "path": "viewer.html"}]
    assert fixture["baseline"]["run_evidence_schema_version"] == "run_evidence.v1"
