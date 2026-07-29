from runtime.agent_strategy.capability_preflight import (
    build_capability_snapshot,
    preflight_task_capabilities,
    task_contract_capability_ids,
)
from runtime.agent_strategy.task_contract import (
    default_task_contract,
    merge_model_task_contract,
    task_continuity_anchor,
)
from runtime.skills import register_builtin_tools
from runtime.tool_registry import ToolRegistry


def test_snapshot_groups_available_and_unavailable_capability_tools() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "mcp_blender.get_scene_info",
            "capability": "mcp.blender",
            "roles": ["verification"],
            "verification_strength": "weak",
            "available": True,
            "source_type": "mcp",
            "tool_health": "degraded",
            "tool_last_error": "MCP request timed out",
        },
        {
            "id": "mcp_blender.execute_blender_code",
            "capability": "mcp.blender",
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
            "available": False,
            "source_type": "mcp",
        },
    ])
    [capability] = snapshot["capabilities"]

    assert capability["id"] == "mcp.blender"
    assert capability["available"] is True
    assert capability["available_tool_ids"] == ["mcp_blender.get_scene_info"]
    assert capability["unavailable_tool_ids"] == ["mcp_blender.execute_blender_code"]
    assert capability["degraded_tool_ids"] == ["mcp_blender.get_scene_info"]
    assert snapshot["degraded_tool_ids"] == ["mcp_blender.get_scene_info"]
    assert snapshot["tool_last_errors"] == {
        "mcp_blender.get_scene_info": "MCP request timed out",
    }
    assert capability["available_effects"] == []
    assert capability["available_verification_strengths"] == ["weak"]
    assert snapshot["verification_tool_strengths"] == {
        "mcp_blender.get_scene_info": "weak",
    }
    assert snapshot["available_evidence_kinds"] == ["verification", "evidence"]
    assert snapshot["evidence_affordances"] == [
        {
            "kind": "verification",
            "tool_ids": ["mcp_blender.get_scene_info"],
            "provider_kinds": ["mcp"],
            "artifacts": [],
            "effects": [],
            "roles": ["verification"],
            "verification_strengths": ["weak"],
        },
        {
            "kind": "evidence",
            "tool_ids": ["mcp_blender.get_scene_info"],
            "provider_kinds": ["mcp"],
            "artifacts": [],
            "effects": [],
            "roles": ["verification"],
            "verification_strengths": ["weak"],
        },
    ]
    assert snapshot["external_state_capability_ids"] == []
    assert snapshot["provider_kinds"] == ["mcp"]
    assert snapshot["tools_by_provider_kind"] == {
        "mcp": [
            "mcp_blender.execute_blender_code",
            "mcp_blender.get_scene_info",
        ],
    }
    assert snapshot["providers"][0]["provider_kind"] == "mcp"
    assert snapshot["providers"][0]["available_tool_ids"] == ["mcp_blender.get_scene_info"]
    assert capability["provider_kinds"] == ["mcp"]
    assert capability["available_provider_kinds"] == ["mcp"]


def test_snapshot_exposes_available_conditional_affordances_and_effects() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "shell.run_command",
            "capability": "shell.local_command",
            "effects": ["shell_command"],
            "artifacts": ["command_output"],
            "roles": ["execution", "verification"],
            "available": True,
            "affordances": [
                {
                    "id": "process.start_background",
                    "description": "Start an external program in the background.",
                    "input_hints": ["set background=true"],
                    "effects": ["external_state_change"],
                    "artifacts": ["process"],
                    "roles": ["execution", "deliverable", "evidence"],
                    "evidence_limits": [
                        "process creation is not behavioral verification"
                    ],
                }
            ],
        }
    ])

    [capability] = snapshot["capabilities"]

    assert capability["available_effects"] == [
        "external_state_change",
        "shell_command",
    ]
    assert capability["conditional_effects"] == ["external_state_change"]
    assert capability["available_artifacts"] == ["command_output", "process"]
    assert capability["available_roles"] == [
        "deliverable",
        "evidence",
        "execution",
        "verification",
    ]
    assert capability["available_affordances"][0]["id"] == "process.start_background"
    assert snapshot["external_state_tool_ids"] == ["shell.run_command"]
    assert snapshot["external_state_capability_ids"] == ["shell.local_command"]
    assert snapshot["conditional_tool_effects"] == {
        "shell.run_command": ["external_state_change"],
    }
    assert snapshot["tool_affordances"]["shell.run_command"][0]["id"] == (
        "process.start_background"
    )

    preflight = preflight_task_capabilities(
        {
            "requires_state_change": True,
            "requires_write": False,
            "capability_ids": ["shell.local_command"],
            "deliverables": [{"kind": "external_state"}],
        },
        snapshot,
    )

    assert not any(
        item["code"] in {
            "missing_external_state_capability",
            "target_capability_lacks_external_state_effect",
        }
        for item in preflight["advisories"]
    )


def test_snapshot_keeps_cli_and_mcp_as_provider_sources_not_capabilities() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "pdf_cli.convert",
            "capability": "document.pdf_to_docx",
            "artifacts": ["docx"],
            "available": True,
            "source_type": "cli",
            "source_id": "pdf-tools",
        },
        {
            "id": "mcp_blender.execute_blender_code",
            "capability": "mcp.blender",
            "effects": ["external_state_change"],
            "available": True,
            "source_type": "mcp",
            "source_id": "blender",
        },
    ])

    assert snapshot["provider_kinds"] == ["cli", "mcp"]
    assert snapshot["tools_by_provider_kind"] == {
        "cli": ["pdf_cli.convert"],
        "mcp": ["mcp_blender.execute_blender_code"],
    }
    capabilities = {item["id"]: item for item in snapshot["capabilities"]}
    assert capabilities["document.pdf_to_docx"]["provider_kinds"] == ["cli"]
    assert capabilities["mcp.blender"]["provider_kinds"] == ["mcp"]


def test_preflight_advises_external_state_when_no_external_capability_available() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "filesystem.write_file",
            "capability": "code.text_write",
            "artifacts": ["file"],
            "available": True,
        },
    ], state_changing_tool_ids={"filesystem.write_file", "shell.run_command"})
    contract = {
        "requires_state_change": True,
        "requires_write": False,
        "deliverables": [{"kind": "external_state", "description": "Scene in external app"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["ok"] is True
    assert result["schema_version"] == "capability_preflight.v2"
    assert result["advisories"][0]["code"] == "missing_external_state_capability"
    assert result["readiness_issues"][0]["code"] == "missing_external_state_capability"
    assert result["preferred_tool_ids"] is None
    assert result["route_hint"]["policy"] == "advisory"
    assert result["route_hint"]["strategy_owner"] == "model"


def test_preflight_reports_mcp_protocol_issue_for_external_state_target() -> None:
    snapshot = build_capability_snapshot(
        [
            {
                "id": "filesystem.scan_folder",
                "capability": "filesystem.local_files",
                "available": True,
            },
        ],
        capability_issues=[
            {
                "code": "protocol_disconnected",
                "source_type": "mcp",
                "source_id": "blender",
                "capability_id": "mcp.blender",
                "message": "MCP service Blender MCP is running, but the MCP protocol is not connected.",
                "recommended_action": "restart",
            }
        ],
    )
    contract = {
        "requires_state_change": True,
        "requires_write": False,
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state", "capability_id": "mcp.blender"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["ok"] is True
    assert [item["code"] for item in result["advisories"]] == ["protocol_disconnected"]
    assert [item["code"] for item in result["readiness_issues"]] == ["protocol_disconnected"]
    assert result["advisories"][0]["capability_id"] == "mcp.blender"
    assert result["advisories"][0]["recommended_action"] == "restart"


def test_preflight_reports_degraded_target_tool_as_advisory() -> None:
    snapshot = build_capability_snapshot(
        [
            {
                "id": "mcp_blender.execute_blender_code",
                "capability": "mcp.blender",
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
                "available": True,
                "source_type": "mcp",
                "tool_health": "degraded",
                "tool_last_error": "MCP request timed out after 120s: tools/call",
            },
        ],
        capability_issues=[
            {
                "code": "tool_degraded",
                "source_type": "mcp",
                "source_id": "blender",
                "capability_id": "mcp.blender",
                "tool_id": "mcp_blender.execute_blender_code",
                "remote_name": "execute_blender_code",
                "message": "MCP service Blender MCP is connected, but tool execute_blender_code is degraded.",
                "recommended_action": "restart",
            }
        ],
    )
    contract = {
        "requires_state_change": True,
        "requires_write": False,
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state", "capability_id": "mcp.blender"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["ok"] is True
    assert result["preferred_tool_ids"] is None
    assert result["advisories"][0]["code"] == "tool_degraded"
    assert result["advisories"][0]["tool_id"] == "mcp_blender.execute_blender_code"


def test_preflight_reports_mismatched_delete_contract_without_rewriting_it() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "filesystem.delete_file",
            "capability": "filesystem.local_state",
            "artifacts": ["file"],
            "effects": ["file_delete", "local_state_change"],
            "roles": ["deliverable", "verification"],
            "verification_strength": "standard",
            "available": True,
        },
    ], state_changing_tool_ids={"filesystem.delete_file"})
    fallback = default_task_contract(
        task_intent="answer_only",
        mode="coding",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code",
        access_scope="project_only",
    )
    contract = merge_model_task_contract({
        "goal": "\u5220\u6389\u8fd9\u4e2a\u65b0\u52a0\u7684\u6587\u6863",
        "intent": "write_required",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "capability_ids": ["filesystem.local_files"],
        "deliverables": [
            {"kind": "external_state", "description": "\u5220\u9664\u9879\u76ee\u4e2d\u7684\u6587\u6863\u6587\u4ef6"}
        ],
    }, fallback)

    result = preflight_task_capabilities(contract, snapshot)

    assert contract["capability_ids"] == ["filesystem.local_files"]
    assert contract["deliverables"][0]["kind"] == "external_state"
    assert result["ok"] is True
    assert {item["code"] for item in result["readiness_issues"]} == {
        "unknown_capability",
        "missing_external_state_capability",
    }


def test_preflight_exposes_external_state_capability_without_ranking_tools() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "filesystem.scan_folder",
            "capability": "filesystem.local_files",
            "available": True,
        },
        {
            "id": "shell.run_command",
            "capability": "shell.local_command",
            "available": True,
        },
        {
            "id": "mcp_blender.execute_blender_code",
            "capability": "mcp.blender",
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
            "available": True,
            "source_type": "mcp",
        },
    ], state_changing_tool_ids={"shell.run_command", "mcp_blender.execute_blender_code"})
    contract = {
        "requires_state_change": True,
        "requires_write": False,
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state", "description": "Blender scene"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["ok"] is True
    assert result["preferred_tool_ids"] is None
    assert result["target_capability_ids"] == ["mcp.blender"]
    assert result["route_hint"]["safety_owner"] == "tool_execution_guard"


def test_preflight_does_not_rank_role_relevant_mcp_tools() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "mcp_blender.execute_blender_code",
            "capability": "mcp.blender",
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
            "available": True,
            "source_type": "mcp",
        },
        {
            "id": "mcp_blender.get_scene_info",
            "capability": "mcp.blender",
            "roles": ["evidence", "verification"],
            "verification_strength": "weak",
            "available": True,
            "source_type": "mcp",
        },
        {
            "id": "mcp_blender.download_sketchfab_model",
            "capability": "mcp.blender",
            "effects": ["external_state_change"],
            "available": True,
            "source_type": "mcp",
        },
    ], state_changing_tool_ids={
        "mcp_blender.execute_blender_code",
        "mcp_blender.download_sketchfab_model",
    })
    contract = {
        "requires_state_change": True,
        "requires_write": False,
        "requires_verification": True,
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state", "description": "Blender scene"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["preferred_tool_ids"] is None
    assert result["target_capability_ids"] == ["mcp.blender"]


def test_preflight_adds_soft_visual_advisory_when_no_healthy_visual_tool() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "mcp_blender.execute_blender_code",
            "capability": "mcp.blender",
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
            "available": True,
            "source_type": "mcp",
        },
        {
            "id": "mcp_blender.get_viewport_screenshot",
            "capability": "mcp.blender",
            "roles": ["verification"],
            "artifacts": ["screenshot"],
            "verification_strength": "standard",
            "available": True,
            "source_type": "mcp",
            "tool_health": "degraded",
            "tool_last_error": "Unknown command type: get_viewport_screenshot",
        },
    ], state_changing_tool_ids={"mcp_blender.execute_blender_code"})
    contract = {
        "requires_state_change": True,
        "requires_write": False,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state", "description": "Blender scene"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["ok"] is True
    assert result["preferred_tool_ids"] is None
    assert any(
        item["code"] == "visual_verification_path_uncertain"
        for item in result["advisories"]
    )
    readiness = next(
        item for item in result["advisories"]
        if item["code"] == "visual_verification_provider_unavailable"
    )
    assert readiness["tools"] == [{
        "tool_id": "mcp_blender.get_viewport_screenshot",
        "health": "degraded",
        "message": "Unknown command type: get_viewport_screenshot",
    }]


def test_preflight_exposes_visual_verification_tools_for_code_task() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "code.edit_file",
            "capability": "code.text_write",
            "artifacts": ["diff"],
            "effects": ["file_write", "local_state_change"],
            "roles": ["deliverable"],
            "available": True,
        },
        {
            "id": "preview.capture_local_html",
            "capability": "preview.visual_debug",
            "artifacts": ["screenshot", "visual_evidence"],
            "roles": ["verification"],
            "verification_strength": "standard",
            "available": True,
        },
        {
            "id": "preview.capture_file",
            "capability": "preview.visual_debug",
            "artifacts": ["screenshot", "image", "visual_evidence", "pdf_page_render"],
            "roles": ["verification"],
            "verification_strength": "standard",
            "available": True,
        },
        {
            "id": "preview.interact_page",
            "capability": "preview.visual_debug",
            "artifacts": ["screenshot", "visual_evidence", "interaction_trace", "dom_text"],
            "roles": ["verification"],
            "verification_strength": "standard",
            "available": True,
        },
        {
            "id": "web.capture_page",
            "capability": "web.page_capture",
            "artifacts": ["screenshot"],
            "roles": ["verification"],
            "verification_strength": "standard",
            "available": True,
        },
    ])
    contract = {
        "requires_write": True,
        "requires_verification": True,
        "required_verification_modalities": ["visual"],
        "capability_ids": ["code.text_write"],
        "deliverables": [{"kind": "code", "path_hint": "index.html"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["preferred_tool_ids"] is None
    assert result["visual_verification_tool_ids"] == [
        "preview.capture_local_html",
        "preview.capture_file",
        "preview.interact_page",
        "web.capture_page",
    ]
    assert [item["kind"] for item in result["evidence_affordances"]] == [
        "content",
        "structural",
        "runtime",
        "visual",
        "network",
        "local_state",
        "verification",
        "evidence",
    ]


def test_snapshot_describes_core_evidence_affordances_without_routing() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "filesystem.read_file",
            "capability": "filesystem.local_files",
            "artifacts": ["text"],
            "roles": ["evidence", "verification"],
            "verification_strength": "weak",
        },
        {
            "id": "shell.run_command",
            "capability": "shell.local_command",
            "artifacts": ["command_output", "debug_session"],
            "effects": ["shell_command"],
            "roles": ["execution", "evidence", "verification"],
            "verification_strength": "standard",
        },
        {
            "id": "preview.capture_local_html",
            "capability": "preview.visual_debug",
            "artifacts": ["screenshot", "visual_evidence"],
            "roles": ["verification"],
            "verification_strength": "standard",
        },
    ])
    by_kind = {item["kind"]: item for item in snapshot["evidence_affordances"]}

    assert "content" in snapshot["available_evidence_kinds"]
    assert "runtime" in snapshot["available_evidence_kinds"]
    assert "visual" in snapshot["available_evidence_kinds"]
    assert by_kind["content"]["tool_ids"] == ["filesystem.read_file"]
    assert by_kind["runtime"]["tool_ids"] == ["shell.run_command"]
    assert by_kind["visual"]["tool_ids"] == ["preview.capture_local_html"]


def test_write_tools_expose_local_state_without_becoming_verification() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "code.edit_file",
            "capability": "code.text_write",
            "artifacts": ["file", "diff"],
            "effects": ["file_write", "local_state_change"],
            "roles": ["deliverable"],
        },
    ])
    by_kind = {item["kind"]: item for item in snapshot["evidence_affordances"]}

    assert "local_state" in snapshot["available_evidence_kinds"]
    assert "verification" not in snapshot["available_evidence_kinds"]
    assert by_kind["local_state"]["tool_ids"] == ["code.edit_file"]
    assert by_kind["local_state"]["roles"] == ["deliverable"]


def test_builtin_tool_specs_feed_evidence_affordances() -> None:
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        groups=("filesystem", "code", "shell", "git", "spreadsheet"),
    )

    snapshot = build_capability_snapshot(registry.list_specs())
    by_kind = {item["kind"]: item for item in snapshot["evidence_affordances"]}

    assert "content" in snapshot["available_evidence_kinds"]
    assert "runtime" in snapshot["available_evidence_kinds"]
    assert "local_state" in snapshot["available_evidence_kinds"]
    assert "verification" in snapshot["available_evidence_kinds"]
    assert "evidence" in snapshot["available_evidence_kinds"]
    assert "filesystem.read_file" in by_kind["content"]["tool_ids"]
    assert "shell.run_command" in by_kind["runtime"]["tool_ids"]
    assert "code.edit_file" in by_kind["local_state"]["tool_ids"]
    assert "git.diff" in by_kind["verification"]["tool_ids"]
    assert "spreadsheet.inspect_workbook" in by_kind["content"]["tool_ids"]
    assert snapshot["tool_effects"]["code.edit_file"] == [
        "file_write",
        "local_state_change",
    ]
    assert snapshot["tool_roles"]["code.edit_file"] == ["deliverable"]


def test_preflight_advises_unavailable_target_capability() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "mcp_blender.execute_blender_code",
            "capability": "mcp.blender",
            "effects": ["external_state_change"],
            "roles": ["deliverable"],
            "available": False,
            "source_type": "mcp",
        },
    ], state_changing_tool_ids={"mcp_blender.execute_blender_code"})
    contract = {
        "requires_state_change": True,
        "requires_write": False,
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state"}],
    }

    result = preflight_task_capabilities(contract, snapshot)

    assert result["ok"] is True
    assert [item["code"] for item in result["advisories"]] == [
        "capability_unavailable",
        "missing_external_state_capability",
    ]
    assert [item["code"] for item in result["readiness_issues"]] == [
        "capability_unavailable",
        "missing_external_state_capability",
    ]


def test_task_contract_capability_ids_reads_contract_and_deliverables() -> None:
    contract = {
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state", "capability_id": "browser.control"}],
    }

    assert task_contract_capability_ids(contract) == ["mcp.blender", "browser.control"]


def test_task_contract_preserves_model_declared_capabilities() -> None:
    fallback = default_task_contract(
        task_intent="write_required",
        mode="terminal",
        planning_policy="auto",
        confirmation_policy="auto",
        workspace_path=r"D:\code",
        access_scope="project_only",
    )

    contract = merge_model_task_contract({
        "goal": "Create a small house in Blender",
        "intent": "write_required",
        "requires_write": False,
        "requires_state_change": True,
        "requires_verification": True,
        "capability_ids": ["mcp.blender"],
        "deliverables": [{"kind": "external_state", "capability_id": "mcp.blender"}],
    }, fallback)

    assert contract["capability_ids"] == ["mcp.blender"]
    assert contract["deliverables"][0]["capability_id"] == "mcp.blender"
    assert task_continuity_anchor(contract)["capability_ids"] == ["mcp.blender"]
