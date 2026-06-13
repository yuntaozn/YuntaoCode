from runtime.run_recovery import build_result_context_snapshot, format_recovery_context


def test_result_context_snapshot_keeps_verified_facts_and_unresolved_risks() -> None:
    snapshot = build_result_context_snapshot(
        task_id="task-1",
        run_id="run-1",
        task_contract={"goal": "Create viewer", "requires_write": True},
        run_result={
            "status": "partial",
            "written_paths": ["viewer.html"],
            "target_written_paths": ["viewer.html"],
            "observed_written_paths": ["viewer.html"],
            "verified": [],
            "risks": ["write_not_verified"],
            "failures": [],
            "counts": {"write_successes": 1},
        },
    )

    assert snapshot["schema_version"] == "context_snapshot.v1"
    assert snapshot["metadata"]["observed_written_paths"] == ["viewer.html"]
    assert snapshot["evidence"][0]["path"] == "viewer.html"
    assert snapshot["unresolved"] == ["write_not_verified"]


def test_format_recovery_context_warns_against_repeating_failed_steps() -> None:
    text = format_recovery_context(
        {
            "id": "checkpoint-1",
            "run_id": "run-1",
            "state": "partial",
        },
        {
            "snapshot": {
                "metadata": {"observed_written_paths": ["viewer.html"]},
                "evidence": [{"path": "viewer.html", "summary": "Written but unverified"}],
                "unresolved": ["write_not_verified"],
            },
        },
    )

    assert "checkpoint-1" in text
    assert "viewer.html" in text
    assert "write_not_verified" in text
    assert "do not assume old outputs are still valid" in text
