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


def test_snapshot_groups_available_and_unavailable_capability_tools() -> None:
    snapshot = build_capability_snapshot([
        {
            "id": "mcp_blender.get_scene_info",
            "capability": "mcp.blender",
            "roles": ["verification"],
            "verification_strength": "weak",
            "available": True,
            "source_type": "mcp",
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
    assert capability["available_effects"] == []
    assert capability["available_verification_strengths"] == ["weak"]
    assert snapshot["verification_tool_strengths"] == {
        "mcp_blender.get_scene_info": "weak",
    }
    assert snapshot["external_state_capability_ids"] == []


def test_preflight_blocks_external_state_when_no_external_capability_available() -> None:
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

    assert result["ok"] is False
    assert result["blockers"][0]["code"] == "missing_external_state_capability"


def test_preflight_allows_normalized_local_file_delete_contract() -> None:
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

    assert contract["capability_ids"] == ["filesystem.local_state"]
    assert contract["deliverables"][0]["kind"] == "file"
    assert result["ok"] is True
    assert result["blockers"] == []


def test_preflight_restricts_fallback_for_external_state_capability() -> None:
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
    assert result["restrict_fallback"] is True
    assert "mcp_blender.execute_blender_code" in result["allowed_tool_ids"]
    assert "filesystem.scan_folder" in result["allowed_tool_ids"]
    assert "shell.run_command" not in result["allowed_tool_ids"]


def test_preflight_blocks_unavailable_target_capability() -> None:
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

    assert result["ok"] is False
    assert [item["code"] for item in result["blockers"]] == [
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
