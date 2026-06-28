from runtime.context_pack import (
    build_context_pack,
    context_pack_summary,
    format_context_pack_for_prompt,
    is_context_pack_prompt_for_phase,
)


def test_context_pack_builds_phase_selected_records() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="replace the lesson scene ground with exterior wall panels",
        workspace_snapshot={
            "schema_version": "workspace_snapshot.v1",
            "name": "lesson",
            "path": r"D:\code\lesson",
            "exists": True,
            "readable": True,
            "file_count": 3,
            "directory_count": 2,
            "extension_counts": {".html": 1, ".js": 1, ".glb": 1},
            "observed_patterns": [{"id": "code_files"}, {"id": "three_d_assets"}],
            "notable_paths": ["index.html", "assets/models/wall.glb"],
        },
        previous_contract={
            "goal": "replace the current model with panel-truck.glb",
            "intent": "write_required",
            "requires_write": False,
            "requires_state_change": True,
            "capability_ids": ["mcp.blender"],
            "deliverables": [{"kind": "external_state"}],
        },
        context_hygiene_report={"changed": True, "sanitized_messages": 1},
        task_id="task-1",
    )

    assert pack["schema_version"] == "context_pack.v1"
    assert pack["phase"] == "task_contract"
    assert [item["kind"] for item in pack["records"]] == [
        "user_intent",
        "workspace_summary",
        "task_contract",
        "risk",
    ]
    assert pack["ledger"]["schema_version"] == "context_ledger.v1"
    assert pack["ledger"]["records"][0]["source_type"] == "user_message"
    assert "content_hash" in pack["ledger"]["records"][0]


def test_context_pack_prompt_marks_records_as_facts_not_route() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="analyze the current project",
        workspace_snapshot={
            "schema_version": "workspace_snapshot.v1",
            "name": "demo",
            "exists": True,
            "readable": True,
        },
    )

    prompt = format_context_pack_for_prompt(pack)

    assert "Context Pack for this model call" in prompt
    assert "not hard instructions or a forced route" in prompt
    assert "workspace_summary" in prompt


def test_planning_context_pack_includes_contract_and_capability_facts() -> None:
    pack = build_context_pack(
        phase="planning",
        user_content="create a lesson page",
        workspace_snapshot={
            "schema_version": "workspace_snapshot.v1",
            "name": "lesson",
            "exists": True,
            "readable": True,
            "extension_counts": {".html": 1},
        },
        task_contract={
            "goal": "create a lesson page",
            "intent": "write_required",
            "requires_write": True,
            "requires_state_change": True,
            "requires_verification": True,
            "capability_ids": ["code.text_write"],
            "deliverables": [{"kind": "code", "path_hint": "index.html"}],
            "success_conditions": ["target_deliverable_success"],
        },
        capability_snapshot={
            "schema_version": "capability_snapshot.v1",
            "tool_count": 4,
            "available_tool_count": 3,
        },
        capability_preflight={
            "schema_version": "capability_preflight.v1",
            "ok": True,
            "target_capability_ids": ["code.text_write"],
            "preferred_tool_ids": ["code.edit_file"],
            "advisories": [],
        },
    )

    kinds = [item["kind"] for item in pack["records"]]
    assert kinds == ["user_intent", "workspace_summary", "task_contract", "capability"]
    assert pack["ledger"]["records"][-1]["kind"] == "capability"
    assert "code.edit_file" in pack["records"][-1]["content"]


def test_verification_context_pack_includes_run_result_facts() -> None:
    pack = build_context_pack(
        phase="verification",
        user_content="create a lesson page",
        task_contract={
            "goal": "create a lesson page",
            "intent": "write_required",
            "requires_verification": True,
        },
        capability_snapshot={"tool_count": 5, "available_tool_count": 5},
        capability_preflight={"ok": True, "target_capability_ids": ["code.text_write"]},
        run_result={
            "status": "partial",
            "artifacts": [{"path": "index.html"}],
            "verification_evidence": [
                {"tool": "code.read_file", "path": "index.html", "strength": "weak"}
            ],
            "risks": ["missing_behavioral_verification"],
            "failure_details": [],
        },
    )

    kinds = [item["kind"] for item in pack["records"]]
    assert kinds == ["task_contract", "capability", "tool_result"]
    assert "index.html" in pack["records"][-1]["content"]
    assert "missing_behavioral_verification" in pack["records"][-1]["content"]


def test_execution_context_pack_includes_recent_tools_and_state() -> None:
    pack = build_context_pack(
        phase="execution",
        user_content="create a lesson page",
        task_contract={
            "goal": "create a lesson page",
            "intent": "write_required",
            "requires_write": True,
            "capability_ids": ["code.text_write"],
        },
        capability_snapshot={"tool_count": 5, "available_tool_count": 5},
        capability_preflight={
            "ok": True,
            "target_capability_ids": ["code.text_write"],
            "preferred_tool_ids": ["filesystem.apply_changes"],
        },
        tool_events=[
            {
                "tool": "filesystem.apply_changes",
                "status": "success",
                "input": {"path": "index.html"},
                "output": {"path": "index.html", "size": 1200},
                "declared_roles": ["deliverable"],
            },
            {
                "tool": "shell.run_command",
                "status": "failure",
                "input": {"command": "npm test"},
                "error": "command exited with code 1",
            },
        ],
        execution_plan={
            "state": "running",
            "steps": [
                {"title": "write file", "status": "completed"},
                {"title": "verify output", "status": "running"},
            ],
        },
        current_stage="verifier",
        round_index=3,
    )

    kinds = [item["kind"] for item in pack["records"]]
    assert kinds == ["task_contract", "capability", "tool_result", "recovery", "risk"]
    assert "filesystem.apply_changes" in pack["records"][2]["content"]
    assert "round=3" in pack["records"][3]["content"]
    assert "verify output" in pack["records"][3]["content"]
    assert "command exited with code 1" in pack["records"][4]["content"]

    prompt = format_context_pack_for_prompt(pack)
    assert is_context_pack_prompt_for_phase(prompt, "execution")
    assert not is_context_pack_prompt_for_phase(prompt, "planning")


def test_summary_context_pack_includes_final_answer_preview() -> None:
    pack = build_context_pack(
        phase="summary",
        user_content="create a lesson page",
        task_contract={
            "goal": "create a lesson page",
            "intent": "write_required",
        },
        run_result={"status": "success", "risks": []},
        assistant_content="Created index.html and completed basic verification.",
    )

    kinds = [item["kind"] for item in pack["records"]]
    assert kinds == ["user_intent", "task_contract", "tool_result", "tool_result"]
    assert pack["ledger"]["phase"] == "summary"
    assert "Final answer candidate preview" in pack["records"][-1]["content"]


def test_context_pack_summary_keeps_ledger_without_full_records() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="hello",
        workspace_snapshot={"schema_version": "workspace_snapshot.v1", "name": "demo"},
    )
    summary = context_pack_summary(pack)

    assert summary["schema_version"] == "context_pack.v1"
    assert summary["record_kinds"] == ["user_intent", "workspace_summary"]
    assert "records" not in summary
    assert summary["ledger"]["record_count"] == 2
