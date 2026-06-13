from runtime.agent_strategy.tool_event_roles import (
    DELIVERABLE,
    EVIDENCE,
    VERIFICATION,
    classify_tool_event_role,
    deliverable_verification_events,
    failed_tool_event_role,
    sufficient_deliverable_verification_events,
    successful_deliverable_events,
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
