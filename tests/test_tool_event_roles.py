from runtime.agent_strategy.tool_event_roles import (
    DELIVERABLE,
    EVIDENCE,
    VERIFICATION,
    classify_tool_event_role,
    deliverable_verification_events,
    failed_tool_event_role,
    missing_required_verification_modalities,
    sufficient_deliverable_verification_events,
    successful_deliverable_events,
    verification_evidence_modalities,
    verification_evidence_strength,
)


def _contract() -> dict:
    return {
        "requires_write": True,
        "requires_verification": True,
        "workspace_path": "D:/workspace/site",
        "deliverables": [
            {
                "kind": "code",
                "path_hint": "D:/workspace/site/index.html",
                "description": "Homepage HTML",
            }
        ],
    }


def test_web_asset_collection_is_evidence_when_contract_targets_index_html() -> None:
    event = {
        "tool": "web.collect_site_assets",
        "status": "success",
        "input": {"url": "www.example.com", "output_dir": "D:/workspace/site/site_assets"},
        "output": {"index_path": "D:/workspace/site/site_assets/site-index.json"},
    }

    assert classify_tool_event_role(
        event,
        task_contract=_contract(),
        workspace_path="D:/workspace/site",
    ) == EVIDENCE


def test_finalize_matching_contract_path_is_deliverable() -> None:
    event = {
        "tool": "filesystem.finalize_text_file",
        "status": "success",
        "input": {"output_path": "D:/workspace/site/index.html"},
        "output": {
            "path": "D:/workspace/site/index.html",
            "draft_stats": {"text_chars": 4000},
            "validation": {"valid": True, "text_chars": 4000},
        },
    }

    assert classify_tool_event_role(
        event,
        task_contract=_contract(),
        workspace_path="D:/workspace/site",
    ) == DELIVERABLE


def test_default_path_hint_allows_same_kind_alternative_deliverable() -> None:
    event = {
        "tool": "filesystem.finalize_text_file",
        "status": "success",
        "input": {"output_path": "D:/workspace/site/index-v2.html"},
        "output": {
            "path": "D:/workspace/site/index-v2.html",
            "validation": {"valid": True},
        },
    }

    assert classify_tool_event_role(
        event,
        task_contract=_contract(),
        workspace_path="D:/workspace/site",
    ) == DELIVERABLE


def test_exact_path_policy_rejects_alternative_deliverable_path() -> None:
    contract = _contract()
    contract["deliverables"][0]["path_policy"] = "exact"
    event = {
        "tool": "filesystem.finalize_text_file",
        "status": "success",
        "input": {"output_path": "D:/workspace/site/index-v2.html"},
        "output": {"path": "D:/workspace/site/index-v2.html"},
    }

    assert classify_tool_event_role(
        event,
        task_contract=contract,
        workspace_path="D:/workspace/site",
    ) != DELIVERABLE


def test_reading_contract_deliverable_after_write_counts_as_verification() -> None:
    events = [
        {
            "tool": "web.collect_site_assets",
            "status": "success",
            "input": {"output_dir": "D:/workspace/site/site_assets"},
            "output": {"index_path": "D:/workspace/site/site_assets/site-index.json"},
        },
        {
            "tool": "filesystem.finalize_text_file",
            "status": "success",
            "input": {"output_path": "D:/workspace/site/index.html"},
            "output": {
                "path": "D:/workspace/site/index.html",
                "draft_stats": {"text_chars": 4000},
                "validation": {"valid": True, "text_chars": 4000},
            },
        },
        {
            "tool": "filesystem.read_text_preview",
            "status": "success",
            "input": {"path": "D:/workspace/site/index.html"},
            "output": {
                "path": "D:/workspace/site/index.html",
                "truncated": False,
                "integrity": {"checked": True, "valid": True},
            },
        },
    ]

    deliverables = successful_deliverable_events(
        events,
        task_contract=_contract(),
        workspace_path="D:/workspace/site",
    )
    verifications = deliverable_verification_events(
        events,
        task_contract=_contract(),
        workspace_path="D:/workspace/site",
    )

    assert [event["tool"] for event in deliverables] == ["filesystem.finalize_text_file"]
    assert [event["tool"] for event in verifications] == [
        "filesystem.finalize_text_file",
        "filesystem.read_text_preview",
    ]
    assert classify_tool_event_role(
        events[-1],
        task_contract=_contract(),
        workspace_path="D:/workspace/site",
    ) == VERIFICATION


def test_external_state_effect_satisfies_external_state_deliverable() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [
            {
                "kind": "external_state",
                "path_hint": "",
                "description": "Current Blender scene",
            }
        ],
    }
    events = [
        {
            "tool": "mcp_blender.execute_blender_code",
            "status": "success",
            "output": {
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
            },
        },
        {
            "tool": "mcp_blender.get_scene_info",
            "status": "success",
            "output": {"roles": ["evidence", "verification"]},
        },
    ]

    deliverables = successful_deliverable_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    )
    verifications = deliverable_verification_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    )

    assert [event["tool"] for event in deliverables] == [
        "mcp_blender.execute_blender_code"
    ]
    assert [event["tool"] for event in verifications] == [
        "mcp_blender.get_scene_info"
    ]


def test_external_state_effect_does_not_satisfy_file_deliverable() -> None:
    event = {
        "tool": "mcp_blender.execute_blender_code",
        "status": "success",
        "output": {
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
        },
    }

    assert classify_tool_event_role(
        event,
        task_contract=_contract(),
        workspace_path="D:/workspace/site",
    ) != DELIVERABLE


def test_weak_external_state_inspection_is_not_sufficient_verification() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Scene"}],
    }
    events = [
        {
            "tool": "mcp_demo.execute",
            "status": "success",
            "output": {
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
            },
        },
        {
            "tool": "mcp_demo.inspect",
            "status": "success",
            "output": {
                "roles": ["evidence", "verification"],
                "verification_strength": "weak",
            },
        },
    ]

    assert verification_evidence_strength(events[-1]) == "weak"
    assert deliverable_verification_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == [events[-1]]
    assert sufficient_deliverable_verification_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == []


def test_structured_external_state_inspection_upgrades_weak_verification() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Scene"}],
    }
    events = [
        {
            "tool": "mcp_demo.execute",
            "status": "success",
            "output": {
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
            },
        },
        {
            "tool": "mcp_demo.scene_info",
            "status": "success",
            "output": {
                "roles": ["evidence", "verification"],
                "verification_strength": "weak",
                "structured_content": {
                    "object_count": 11,
                    "objects": ["house", "roof"],
                },
            },
        },
    ]

    assert verification_evidence_strength(events[-1]) == "weak"
    assert verification_evidence_strength(
        events[-1],
        task_contract=contract,
    ) == "standard"
    assert sufficient_deliverable_verification_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == [events[-1]]


def test_text_external_state_summary_upgrades_weak_verification() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Scene"}],
    }
    event = {
        "tool": "mcp_demo.scene_info",
        "status": "success",
        "output": {
            "roles": ["evidence", "verification"],
            "verification_strength": "weak",
            "content": "Scene has 11 objects and 4 materials",
        },
    }

    assert verification_evidence_strength(event) == "weak"
    assert verification_evidence_strength(event, task_contract=contract) == "standard"


def test_spreadsheet_preview_is_content_evidence() -> None:
    event = {
        "tool": "spreadsheet.inspect_workbook",
        "status": "success",
        "output": {
            "type": "spreadsheet_preview",
            "path": "D:/workspace/data.xlsx",
            "sheets": [{"name": "Sheet1", "preview_rows": [["name", "qty"]]}],
        },
    }

    assert classify_tool_event_role(
        event,
        task_contract={"requires_verification": True},
        workspace_path="D:/workspace",
    ) == EVIDENCE
    assert verification_evidence_strength(event) == "standard"
    assert verification_evidence_modalities(event) == ("content",)


def test_declared_tool_output_counts_as_standard_verification() -> None:
    event = {
        "tool": "mcp_demo.inspect_scene",
        "status": "success",
        "output": {
            "type": "scene_inspection",
            "roles": ["verification", "evidence"],
            "verification_strength": "standard",
        },
    }

    assert classify_tool_event_role(
        event,
        task_contract={"requires_verification": True},
        workspace_path="D:/workspace",
    ) == VERIFICATION
    assert verification_evidence_strength(event) == "standard"
    assert verification_evidence_modalities(event) == ("structural",)


def test_py_compile_is_structural_verification_not_behavioral() -> None:
    event = {
        "tool": "shell.run_command",
        "status": "success",
        "input": {"command": "python -m py_compile main.py"},
        "output": {"exit_code": 0},
    }

    assert verification_evidence_strength(event) == "standard"
    assert verification_evidence_modalities(event) == ("structural",)


def test_visual_requirement_needs_visual_verification_modality() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [{"kind": "external_state", "description": "Scene appearance"}],
    }
    events = [
        {
            "tool": "mcp_demo.execute",
            "status": "success",
            "output": {
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
            },
        },
        {
            "tool": "mcp_demo.scene_info",
            "status": "success",
            "output": {
                "roles": ["evidence", "verification"],
                "verification_strength": "weak",
                "structured_content": {"object_count": 11},
            },
        },
    ]

    assert verification_evidence_modalities(
        events[-1],
        task_contract=contract,
    ) == ("structural",)
    assert sufficient_deliverable_verification_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == []
    assert missing_required_verification_modalities(
        [events[-1]],
        contract,
    ) == ("visual",)


def test_visual_screenshot_satisfies_visual_verification_modality() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [{"kind": "external_state", "description": "Scene appearance"}],
    }
    events = [
        {
            "tool": "mcp_demo.execute",
            "status": "success",
            "output": {
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
            },
        },
        {
            "tool": "mcp_demo.get_viewport_screenshot",
            "status": "success",
            "output": {
                "roles": ["verification"],
                "verification_strength": "standard",
                "artifact_kind": "screenshot",
                "path": "D:/workspace/scene.png",
            },
        },
    ]

    assert verification_evidence_modalities(
        events[-1],
        task_contract=contract,
    ) == ("visual",)
    assert sufficient_deliverable_verification_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == [events[-1]]
    assert missing_required_verification_modalities(
        [events[-1]],
        contract,
    ) == ()


def test_visual_artifact_from_state_tool_satisfies_visual_verification_modality() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "deliverables": [{"kind": "external_state", "description": "Scene appearance"}],
    }
    events = [
        {
            "tool": "mcp_demo.execute",
            "status": "success",
            "output": {
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
                "path": "D:/workspace/scene_render.png",
                "artifact_kind": "image",
            },
        },
    ]

    assert verification_evidence_modalities(
        events[-1],
        task_contract=contract,
    ) == ("visual",)
    assert sufficient_deliverable_verification_events(
        events,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == [events[-1]]
    assert missing_required_verification_modalities(
        [events[-1]],
        contract,
    ) == ()


def test_failed_tool_uses_declared_task_role_without_claiming_successful_effect() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Scene"}],
    }
    event = {
        "tool": "mcp_demo.execute",
        "status": "failure",
        "declared_effects": ["external_state_change"],
        "declared_roles": ["deliverable"],
        "error": "remote command failed",
    }

    assert failed_tool_event_role(
        event,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == DELIVERABLE


def test_error_output_does_not_satisfy_external_state_deliverable() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Scene"}],
    }
    event = {
        "tool": "mcp_blender.execute_blender_code",
        "status": "success",
        "output": {
            "error": True,
            "message": "Error executing code: material failed",
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
        },
    }

    assert classify_tool_event_role(
        event,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) != DELIVERABLE
    assert successful_deliverable_events(
        [event],
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == []


def test_file_write_does_not_satisfy_external_state_deliverable() -> None:
    contract = {
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "deliverables": [{"kind": "external_state", "description": "Blender scene"}],
    }
    event = {
        "tool": "filesystem.write_file",
        "status": "success",
        "input": {"path": "D:/workspace/build_scene.py"},
        "output": {"path": "D:/workspace/build_scene.py"},
    }

    assert classify_tool_event_role(
        event,
        task_contract=contract,
        workspace_path="D:/workspace",
    ) != DELIVERABLE
    assert successful_deliverable_events(
        [event],
        task_contract=contract,
        workspace_path="D:/workspace",
    ) == []
