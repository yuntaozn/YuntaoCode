from copy import deepcopy

from runtime.evaluation.fixtures import build_evaluation_fixture_export
from runtime.evaluation.reports import build_evaluation_report
from runtime.run_evidence import build_run_evidence
from runtime.run_store import RunStore


def test_evaluation_report_passes_when_fixture_and_run_evidence_match(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = _create_verified_scene_run(store)
    current = store.get(run.id)
    fixture_export = build_evaluation_fixture_export(current)
    evidence = build_run_evidence(current)

    report = build_evaluation_report(fixture_export, evidence)

    assert report["schema_version"] == "evaluation_report.v1"
    assert report["status"] == "passed"
    assert report["score"] == 1.0
    assert report["fixture_id"] == fixture_export["fixture"]["id"]
    assert report["evaluated_run_id"] == run.id
    assert report["boundaries"]["executes_replay"] is False
    assert report["boundaries"]["calls_model"] is False
    assert report["boundaries"]["calls_tools"] is False
    assert _check(report, "result_status")["outcome"] == "passed"
    assert _check(report, "artifacts")["outcome"] == "passed"
    assert _check(report, "capabilities")["outcome"] == "passed"
    assert _check(report, "verification_strength")["outcome"] == "passed"
    assert _check(report, "verification_modalities")["outcome"] == "passed"


def test_evaluation_report_fails_when_required_result_and_artifact_are_missing(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    fixture_export = build_evaluation_fixture_export(store.get(_create_verified_scene_run(store).id))
    failed = store.create(
        conversation_id="conv_1",
        workspace_id="workspace_1",
        task_id="task-2",
        mode="terminal",
        user_content="Create a verified scene",
    )
    store.record_event(failed.id, {
        "event": "result",
        "result": {
            "kind": "run_result",
            "status": "failure",
            "risks": ["target_deliverable_not_observed"],
        },
    })

    report = build_evaluation_report(fixture_export, build_run_evidence(store.get(failed.id)))

    assert report["status"] == "failed"
    assert _check(report, "result_status")["outcome"] == "failed"
    assert _check(report, "artifacts")["outcome"] == "failed"


def test_evaluation_report_marks_capability_and_failure_drift_as_partial(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = _create_verified_scene_run(store)
    fixture_export = build_evaluation_fixture_export(store.get(run.id))
    evidence = deepcopy(build_run_evidence(store.get(run.id)))
    evidence["capability_evidence"]["observed_capability_ids"] = ["custom.scene"]
    evidence["result"]["artifacts"] = [{"kind": "external_state", "capability_id": "custom.scene"}]
    evidence["trace"]["failed_tool_count"] = 1

    report = build_evaluation_report(fixture_export, evidence)

    assert report["status"] == "partial"
    assert _check(report, "result_status")["outcome"] == "passed"
    assert _check(report, "artifacts")["outcome"] == "passed"
    assert _check(report, "capabilities")["outcome"] == "failed"
    assert _check(report, "capabilities")["severity"] == "warning"
    assert _check(report, "failure_regression")["outcome"] == "failed"


def test_evaluation_report_blocks_invalid_fixture_payload(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.json")
    run = _create_verified_scene_run(store)

    report = build_evaluation_report({}, build_run_evidence(store.get(run.id)))

    assert report["status"] == "blocked"
    assert report["score"] == 0.0
    assert _check(report, "input_payload")["outcome"] == "failed"


def _create_verified_scene_run(store: RunStore):
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
            "required_verification_strength": "standard",
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
                {
                    "tool": "mcp_blender.get_viewport_screenshot",
                    "path": "D:/workspace/scene.png",
                    "strength": "standard",
                    "modalities": ["visual"],
                    "sufficient": True,
                },
            ],
            "required_verification_strength": "standard",
            "required_verification_modalities": ["visual"],
            "observed_verification_modalities": ["visual"],
        },
    })
    return run


def _check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)
