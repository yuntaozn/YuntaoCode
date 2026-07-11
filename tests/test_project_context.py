from runtime.agent_strategy.project_context import (
    build_active_focus_snapshot,
    normalize_focus_reference,
    normalize_focus_relation,
)


def test_focus_relation_is_independent_from_new_task_relation() -> None:
    snapshot = build_active_focus_snapshot(
        {
            "source": "model",
            "scope_relation": "new",
            "focus_relation": "inherit",
            "referenced_focus_candidate_id": "run-1",
            "focus": {
                "kind": "subproject",
                "name": "大体积混凝土智能温控仿真实训平台",
                "path_hint": r"D:\code\lesson\大体积混凝土智能温控仿真实训平台",
            },
        },
        [{
            "candidate_id": "run-1",
            "goal": "Analyze the subproject against the submission notice",
            "actual_paths": ["大体积混凝土智能温控仿真实训平台/设计脚本.md"],
        }],
        workspace_snapshot={"path": r"D:\code\lesson"},
    )

    assert snapshot["relation"] == "inherit"
    assert snapshot["resolved"] is True
    assert snapshot["focus"]["name"] == "大体积混凝土智能温控仿真实训平台"
    assert snapshot["source_candidate_found"] is True
    assert snapshot["evidence_paths"] == ["大体积混凝土智能温控仿真实训平台/设计脚本.md"]
    assert snapshot["source_candidate_goal"].startswith("Analyze the subproject")


def test_active_focus_does_not_copy_old_task_goal_as_current_focus() -> None:
    snapshot = build_active_focus_snapshot(
        {
            "source": "model",
            "scope_relation": "new",
            "focus_relation": "inherit",
            "referenced_focus_candidate_id": "run-1",
            "focus": {},
        },
        [{
            "candidate_id": "run-1",
            "goal": "Package the old task as an executable",
            "actual_paths": ["tauri-exe/example/src-tauri/Cargo.toml"],
        }],
    )

    assert snapshot["focus"] == {}
    assert snapshot["resolved"] is False
    assert snapshot["source_candidate_goal"] == "Package the old task as an executable"


def test_focus_normalization_is_bounded_and_advisory() -> None:
    assert normalize_focus_relation("unknown") == "unresolved"
    assert normalize_focus_reference("project") == {}
    assert normalize_focus_reference({"name": " Demo   Project ", "path": "./demo"}) == {
        "kind": "other",
        "name": "Demo Project",
        "path_hint": "./demo",
    }
