from __future__ import annotations

import pytest

from runtime.core.automation import (
    Automation,
    AutomationTaskTemplate,
    AutomationTrigger,
    automation_task_seed,
    can_trigger_automation,
)
from runtime.core.capability import CapabilityContract, PermissionSet, needs_user_confirmation
from runtime.core.context import ContextRecord, ContextSnapshot, EvidenceRecord, select_records_for_phase
from runtime.core.events import build_trace_event
from runtime.core.experience import ExperienceDigest, experience_sample_from_runbook
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


def test_automation_serializes_trigger_and_task_template() -> None:
    automation = Automation(
        id="automation-1",
        name="Weekly project summary",
        state="active",
        trigger=AutomationTrigger(kind="weekly", days_of_week=("mon",), time_of_day="09:00"),
        task_template=AutomationTaskTemplate(
            goal="Summarize project changes from the last week",
            workspace_id="workspace-1",
            model="model-1",
            planning_policy="auto",
            confirmation_policy="auto",
        ),
    )

    data = automation.to_dict()

    assert data["schema_version"] == "automation.v1"
    assert data["record_kind"] == "automation"
    assert data["trigger"]["schema_version"] == "automation_trigger.v1"
    assert data["trigger"]["kind"] == "weekly"
    assert data["task_template"]["schema_version"] == "automation_task_template.v1"
    assert data["task_template"]["goal"].startswith("Summarize")


def test_automation_creates_run_seed_without_executing_tools() -> None:
    automation = Automation(
        id="automation-1",
        name="Check failures",
        state="active",
        trigger=AutomationTrigger(kind="interval", interval_seconds=3600),
        task_template=AutomationTaskTemplate(
            goal="Review failed task records",
            workspace_id="workspace-1",
            access_scope="project_only",
        ),
    )

    seed = automation_task_seed(automation)

    assert can_trigger_automation(automation, active_runs=0)
    assert not can_trigger_automation(automation, active_runs=1)
    assert seed["content"] == "Review failed task records"
    assert seed["automation_triggered"] is True
    assert "tool_id" not in seed


def test_automation_queue_next_does_not_start_parallel_run() -> None:
    automation = Automation(
        id="automation-queue",
        name="Queued review",
        state="active",
        concurrency_policy="queue_next",
        trigger=AutomationTrigger(kind="daily", time_of_day="09:00"),
        task_template=AutomationTaskTemplate(goal="Review project status"),
    )

    assert not can_trigger_automation(automation, active_runs=1)


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


def test_trace_event_accepts_runtime_canonical_event_names() -> None:
    event = build_trace_event(
        "capability.snapshot",
        run_id="run-1",
        payload={"ok": True},
    )

    data = event.to_dict()

    assert data["event_name"] == "capability.snapshot"
    assert data["event_family"] == "capability"


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
        verification_strength="standard",
        permissions=PermissionSet(filesystem="workspace", shell="confirm_each"),
    )

    data = contract.to_dict()

    assert data["schema_version"] == "capability_contract.v1"
    assert data["output_artifacts"] == ["docx"]
    assert data["effect_types"] == ["file_write"]
    assert data["task_roles"] == ["deliverable"]
    assert data["verification_strength"] == "standard"
    assert needs_user_confirmation(contract)


def test_runtime_result_schema_is_core_owned() -> None:
    result = RuntimeResult(
        status="partial",
        counts={"tool_events": 2, "failures": 1},
        verification_evidence=({"tool": "pytest", "strength": "strong"},),
        failure_details=({"tool": "lint", "impact": "incidental"},),
        risks=("write_not_verified",),
    )

    data = result.to_dict()

    assert data["schema_version"] == RUN_RESULT_SCHEMA_VERSION
    assert data["kind"] == "run_result"
    assert data["risks"] == ["write_not_verified"]
    assert data["verification_evidence"][0]["strength"] == "strong"
    assert data["failure_details"][0]["impact"] == "incidental"


def test_experience_sample_is_between_runbook_and_skill_candidate() -> None:
    runbook = {
        "run": {
            "id": "run-1",
            "task_id": "task-1",
            "workspace_id": "workspace-1",
            "conversation_id": "conversation-1",
            "goal": "Create a verified report",
            "updated_at": "2026-06-13T00:01:00Z",
        },
        "task_contract": {"requires_write": True},
        "result": {"status": "partial", "risks": ["write_not_verified"]},
        "risks": ["write_not_verified"],
        "verification_evidence": [{"kind": "file_exists", "path": "report.docx"}],
    }

    sample = experience_sample_from_runbook("experience-1", runbook)

    data = sample.to_dict()
    assert data["schema_version"] == "experience_sample.v1"
    assert data["record_kind"] == "experience_sample"
    assert data["outcome"] == "partial"
    assert data["run_result"]["status"] == "partial"
    assert data["risks"] == ["write_not_verified"]


def test_experience_digest_serializes_reviewed_patterns() -> None:
    digest = ExperienceDigest(
        id="digest-1",
        sample_ids=("experience-1",),
        pattern_name="Document generation verification",
        summary="Generated documents need post-write evidence.",
        capability_ids=("document.word_export",),
        evidence_requirements=("file_exists", "content_coverage"),
        failure_modes=("document_output_too_short",),
    )

    data = digest.to_dict()

    assert data["schema_version"] == "experience_digest.v1"
    assert data["record_kind"] == "experience_digest"
    assert data["sample_ids"] == ["experience-1"]
    assert data["failure_modes"] == ["document_output_too_short"]
