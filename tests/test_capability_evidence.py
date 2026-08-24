from runtime.capability_evidence import build_capability_evidence_summary


def test_capability_evidence_distinguishes_declared_and_observed_facts() -> None:
    contract = {
        "capability_ids": ["mcp.blender"],
        "deliverables": [
            {"kind": "external_state", "capability_id": "mcp.blender"},
        ],
    }
    events = [
        {
            "tool": "mcp_blender.execute_blender_code",
            "status": "success",
            "declared_capability": "mcp.blender",
            "declared_artifacts": ["external_state"],
            "declared_effects": ["external_state_change"],
            "declared_roles": ["deliverable"],
            "output": {
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
                "artifacts": ["external_state"],
            },
        },
        {
            "tool": "mcp_blender.get_viewport_screenshot",
            "status": "success",
            "declared_capability": "mcp.blender",
            "declared_artifacts": ["screenshot"],
            "declared_roles": ["verification"],
            "declared_verification_strength": "standard",
            "output": {
                "roles": ["verification"],
                "artifact_kind": "screenshot",
                "path": "D:/workspace/scene.png",
                "verification_strength": "standard",
            },
        },
    ]

    summary = build_capability_evidence_summary(events, task_contract=contract)

    assert summary["schema_version"] == "capability_evidence_summary.v1"
    assert summary["requested_capability_ids"] == ["mcp.blender"]
    assert summary["observed_capability_ids"] == ["mcp.blender"]
    assert summary["unobserved_requested_capability_ids"] == []
    assert summary["status_counts"] == {"success": 2}
    assert summary["declared_effects"] == ["external_state_change"]
    assert summary["observed_effects"] == ["external_state_change"]
    assert summary["declared_roles"] == ["deliverable", "verification"]
    assert summary["observed_roles"] == ["deliverable", "verification"]
    assert summary["declared_artifacts"] == ["external_state", "screenshot"]
    assert summary["artifacts"] == ["external_state", "screenshot"]
    assert summary["verification_strengths"] == ["standard"]
    assert summary["events"][1]["paths"] == ["d:/workspace/scene.png"]


def test_capability_evidence_reports_unobserved_requested_capability() -> None:
    summary = build_capability_evidence_summary(
        [
            {
                "tool": "filesystem.write_file",
                "status": "success",
                "declared_capability": "code.text_write",
            },
        ],
        task_contract={"capability_ids": ["mcp.blender"]},
    )

    assert summary["requested_capability_ids"] == ["mcp.blender"]
    assert summary["observed_capability_ids"] == ["code.text_write"]
    assert summary["unobserved_requested_capability_ids"] == ["mcp.blender"]
