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
        "previous_contract",
        "workspace_summary",
        "risk",
    ]
    previous = pack["records"][1]
    assert previous["source_id"] == "previous_task_contract"
    assert "not the current goal by default" in previous["content"]
    assert previous["metadata"]["inheritance_rule"] == "historical_reference_only_unless_current_request_continues_it"
    assert pack["ledger"]["schema_version"] == "context_ledger.v1"
    assert pack["ledger"]["records"][0]["source_type"] == "user_message"
    assert pack["ledger"]["records"][0]["task_id"] == "task-1"
    assert "content_hash" in pack["ledger"]["records"][0]


def test_context_pack_includes_task_lineage_candidates_as_candidates() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="try again",
        task_candidates=[
            {
                "candidate_id": "run-1",
                "goal": "Create a Blender house",
                "intent": "write_required",
                "status": "partial",
                "requires_write": False,
                "requires_state_change": True,
                "deliverable_kinds": ["external_state"],
                "capability_ids": ["mcp.blender"],
                "target_written_paths": ["scene.blend"],
                "changed_paths": ["scene.blend"],
                "actual_paths": ["scene.blend"],
            }
        ],
    )

    assert [item["kind"] for item in pack["records"]] == ["user_intent", "task_lineage"]
    lineage = pack["records"][1]
    assert lineage["source_type"] == "conversation_history"
    assert "historical task candidates" in lineage["content"].lower()
    assert lineage["metadata"]["candidates"][0]["candidate_id"] == "run-1"
    assert lineage["metadata"]["candidates"][0]["actual_paths"] == ["scene.blend"]


def test_context_pack_exposes_selected_memory_as_audited_advisory_context() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="继续优化当前项目的上下文",
        memory_context={
            "schema_version": "memory_context.v1",
            "prompt": "- [workspace, architecture] Context Runtime must remain advisory.",
            "used_memory_ids": ["memory-1"],
            "selected_count": 1,
            "workspace_id": "workspace-1",
        },
        task_id="task-1",
    )

    assert [item["kind"] for item in pack["records"]] == ["user_intent", "memory"]
    memory = pack["records"][1]
    assert memory["source_type"] == "memory_store"
    assert memory["trust"] == "memory"
    assert "not as a new user instruction" in memory["content"]
    assert memory["metadata"]["used_memory_ids"] == ["memory-1"]
    assert pack["ledger"]["records"][1]["source_id"] == "memory_selection"


def test_context_pack_omits_memory_status_when_nothing_was_selected() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="hello",
        memory_context={
            "schema_version": "memory_context.v1",
            "prompt": "暂无与当前请求相关的已启用用户记忆。",
            "used_memory_ids": [],
            "selected_count": 0,
            "workspace_id": "workspace-1",
        },
    )

    assert [item["kind"] for item in pack["records"]] == ["user_intent"]


def test_context_pack_carries_active_focus_without_copying_old_goal() -> None:
    pack = build_context_pack(
        phase="planning",
        user_content="现在先写正式设计说明",
        task_contract={
            "goal": "Write a formal design document",
            "intent": "document_export",
            "scope_relation": "new",
            "focus_relation": "inherit",
        },
        active_focus={
            "schema_version": "active_focus.v1",
            "relation": "inherit",
            "focus": {
                "kind": "subproject",
                "name": "Mass concrete training platform",
                "path_hint": "lesson/mass-concrete",
            },
            "source_candidate_id": "run-1",
            "source_candidate_found": True,
            "source_candidate_goal": "Package the previous project",
            "evidence_paths": ["lesson/mass-concrete/design.md"],
            "resolved": True,
        },
    )

    kinds = [item["kind"] for item in pack["records"]]
    assert kinds == ["user_intent", "project_context", "task_contract"]
    focus = pack["records"][1]
    assert "Mass concrete training platform" in focus["content"]
    assert "Package the previous project" not in focus["content"]
    assert focus["metadata"]["source_candidate_id"] == "run-1"


def test_context_pack_records_task_lineage_hygiene_counts() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="continue",
        context_hygiene_report={
            "changed": True,
            "sanitized_messages": 2,
            "task_candidate_messages": 1,
            "task_user_anchor_messages": 1,
            "compacted_task_marker_messages": 1,
            "current_request_boundary_inserted": True,
        },
    )

    risk = pack["records"][-1]
    assert risk["kind"] == "risk"
    assert risk["metadata"]["task_candidate_messages"] == 1
    assert risk["metadata"]["task_user_anchor_messages"] == 1
    assert risk["metadata"]["compacted_task_marker_messages"] == 1
    assert risk["metadata"]["current_request_boundary_inserted"] is True


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
    assert "content_preview" not in prompt


def test_context_pack_prompt_uses_ledger_index_without_repeating_content() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="continue",
        task_candidates=[{
            "candidate_id": "old-run",
            "goal": "Old task target that should not be duplicated in ledger preview",
            "intent": "write_required",
            "status": "partial",
        }],
    )

    prompt = format_context_pack_for_prompt(pack)

    assert "Old task target" in prompt
    assert "content_preview" not in prompt
    assert prompt.count("Old task target") == 1


def test_context_pack_prompt_preserves_all_bounded_task_candidates() -> None:
    candidates = [
        {
            "candidate_id": f"run-{index}",
            "lineage_rank": index,
            "recency_rank": index,
            "goal": f"Historical candidate {index} " + ("detail " * 30),
            "status": "partial",
            "actual_paths": [f"project-{index}/src/app.js", f"project-{index}/index.html"],
        }
        for index in range(1, 5)
    ]
    pack = build_context_pack(
        phase="task_contract",
        user_content="现在先为它写正式说明",
        task_candidates=candidates,
    )

    prompt = format_context_pack_for_prompt(pack)

    for index in range(1, 5):
        assert f"run-{index}" in prompt
        assert f"project-{index}/src/app.js" in prompt


def test_workspace_context_lists_top_level_project_boundaries() -> None:
    pack = build_context_pack(
        phase="task_contract",
        user_content="analyze this project",
        workspace_snapshot={
            "schema_version": "workspace_snapshot.v1",
            "name": "lesson",
            "path": r"D:\code\lesson",
            "exists": True,
            "readable": True,
            "top_level_entries": [
                {"name": "project-a", "path": "project-a", "type": "directory"},
                {"name": "project-b", "path": "project-b", "type": "directory"},
            ],
            "notable_paths": ["project-a/index.html"],
        },
    )

    workspace = pack["records"][1]
    assert "top_level=project-a, project-b" in workspace["content"]


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
            "evidence_affordances": [
                {
                    "kind": "runtime",
                    "tool_ids": ["shell.run_command"],
                    "verification_strengths": ["standard"],
                },
                {
                    "kind": "visual",
                    "tool_ids": ["preview.capture_local_html", "preview.interact_page"],
                    "verification_strengths": ["standard"],
                },
            ],
        },
        capability_preflight={
            "schema_version": "capability_preflight.v1",
            "ok": True,
            "target_capability_ids": ["code.text_write"],
            "preferred_tool_ids": ["code.edit_file"],
            "visual_verification_tool_ids": ["preview.capture_local_html", "preview.interact_page"],
            "advisories": [],
        },
    )

    kinds = [item["kind"] for item in pack["records"]]
    assert kinds == ["user_intent", "task_contract", "workspace_summary", "capability"]
    assert pack["ledger"]["records"][-1]["kind"] == "capability"
    assert "code.edit_file" not in pack["records"][-1]["content"]
    assert "preview.interact_page" in pack["records"][-1]["content"]
    assert "evidence_affordances=runtime:shell.run_command" in pack["records"][-1]["content"]
    assert pack["records"][-1]["metadata"]["visual_verification_tool_ids"] == [
        "preview.capture_local_html",
        "preview.interact_page",
    ]
    assert pack["records"][-1]["metadata"]["evidence_affordances"][0]["kind"] == "runtime"


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
            {
                "tool": "filesystem.write_file",
                "status": "failure",
                "input": {"content": "hello"},
                "error": "missing path",
                "output": {
                    "type": "tool_attempt_observation",
                    "reason": "invalid_tool_input",
                    "message": "missing path",
                    "observation": {
                        "reason": "invalid_tool_input",
                        "missing_fields": ["path"],
                    },
                },
            },
        ],
        execution_plan={
            "state": "running",
            "steps": [
                {"title": "write file", "status": "completed"},
                {"title": "verify output", "status": "running"},
            ],
        },
        round_index=3,
    )

    kinds = [item["kind"] for item in pack["records"]]
    assert kinds == ["task_contract", "capability", "tool_result", "recovery", "risk"]
    assert "filesystem.apply_changes" in pack["records"][2]["content"]
    assert "reason=invalid_tool_input" in pack["records"][2]["content"]
    assert "missing=path" in pack["records"][2]["content"]
    assert "round=3" in pack["records"][3]["content"]
    assert "stage=" not in pack["records"][3]["content"]
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
