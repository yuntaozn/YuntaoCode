from __future__ import annotations

import pytest

from runtime.core.capability import CapabilityContract, PermissionSet, needs_user_confirmation
from runtime.core.context import ContextRecord, ContextSnapshot, EvidenceRecord, select_records_for_phase
from runtime.core.events import build_trace_event
from runtime.core.result import RUN_RESULT_SCHEMA_VERSION, RuntimeResult
from runtime.core.task import ProductTask, TaskPlan, TaskStep, can_transition


def test_product_task_transition_and_serialization() -> None:
    task = ProductTask(
        id="task-1",
        goal="Analyze the project",
        conversation_id="conv-1",
        workspace_id="workspace-1",
    )

    running = task.transition("running")

    assert running.state == "running"
    assert can_transition("running", "verifying")
    assert running.to_dict()["record_kind"] == "task"
    with pytest.raises(ValueError):
        running.transition("created")


def test_task_plan_serializes_steps() -> None:
    plan = TaskPlan(
        id="plan-1",
        task_id="task-1",
        title="Project review",
        steps=(
            TaskStep(id="step-1", title="Read docs", tool_hint="filesystem.read_file"),
        ),
    )

    data = plan.to_dict()

    assert data["schema_version"] == "plan.v1"
    assert data["steps"][0]["schema_version"] == "step.v1"
    assert data["steps"][0]["tool_hint"] == "filesystem.read_file"


def test_trace_event_normalizes_unknown_event_name() -> None:
    event = build_trace_event(
        "unknown.event",
        run_id="run-1",
        task_id="task-1",
        payload={"message": "ok"},
    )

    data = event.to_dict()

    assert data["event_name"] == "run.status"
    assert data["event_family"] == "run"
    assert data["payload"] == {"message": "ok"}


def test_context_snapshot_keeps_evidence_and_unresolved_items() -> None:
    records = (
        ContextRecord(kind="user_intent", content="Create a model viewer", trust="user_provided"),
        ContextRecord(kind="tool_result", content="index.html written", trust="runtime_fact"),
        ContextRecord(kind="memory", content="User prefers foundation work", trust="memory"),
    )
    selected = select_records_for_phase(records, "verification")
    snapshot = ContextSnapshot(
        task_id="task-1",
        phase="verification",
        records=selected,
        evidence=(
            EvidenceRecord(
                source_id="file:D:/ifctool/index.html",
                path="D:/ifctool/index.html",
                summary="Generated HTML model viewer.",
                ranges=("all",),
            ),
        ),
        unresolved=("No browser verification observed",),
    )

    data = snapshot.to_dict()

    assert [item["kind"] for item in data["records"]] == ["tool_result"]
    assert data["evidence"][0]["path"].endswith("index.html")
    assert data["unresolved"] == ["No browser verification observed"]


def test_capability_contract_confirmation_rules() -> None:
    contract = CapabilityContract(
        capability_id="document.pdf_to_docx",
        tool_id="document.extract_pdf_to_docx",
        output_artifacts=("docx",),
        effect_types=("file_write",),
        task_roles=("deliverable",),
        permissions=PermissionSet(filesystem="workspace", shell="confirm_each"),
    )

    data = contract.to_dict()

    assert data["schema_version"] == "capability_contract.v1"
    assert data["output_artifacts"] == ["docx"]
    assert data["effect_types"] == ["file_write"]
    assert data["task_roles"] == ["deliverable"]
    assert needs_user_confirmation(contract)


def test_runtime_result_schema_is_core_owned() -> None:
    result = RuntimeResult(
        status="partial",
        counts={"tool_events": 2, "failures": 1},
        risks=("write_not_verified",),
    )

    data = result.to_dict()

    assert data["schema_version"] == RUN_RESULT_SCHEMA_VERSION
    assert data["kind"] == "run_result"
    assert data["risks"] == ["write_not_verified"]
