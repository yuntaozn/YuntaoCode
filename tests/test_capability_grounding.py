from runtime.agent_strategy.capability_grounding import ground_task_contract_with_capabilities
from runtime.agent_strategy.capability_preflight import (
    build_capability_snapshot,
    preflight_task_capabilities,
)
from runtime.agent_strategy.task_contract import success_conditions_for_contract


def _snapshot() -> dict:
    return build_capability_snapshot(
        [
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
                "id": "mcp_blender.get_scene_info",
                "capability": "mcp.blender",
                "roles": ["evidence", "verification"],
                "verification_strength": "weak",
                "available": True,
                "source_type": "mcp",
            },
            {
                "id": "mcp_blender.execute_blender_code",
                "capability": "mcp.blender",
                "effects": ["external_state_change"],
                "roles": ["deliverable"],
                "available": True,
                "source_type": "mcp",
            },
        ],
        state_changing_tool_ids={"shell.run_command", "mcp_blender.execute_blender_code"},
    )


def test_grounding_converts_external_app_file_guess_to_external_state() -> None:
    contract = {
        "intent": "write_required",
        "goal": "使用Blender创建一个二层小楼的3D模型",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "requires_plan": True,
        "capability_ids": [],
        "deliverables": [
            {
                "kind": "file",
                "path_hint": r"D:\code\blender\two-story-house.blend",
                "path_policy": "exact",
                "description": "二层小楼的Blender工程文件",
            }
        ],
        "first_action": "plan",
        "blockers": ["缺少Blender相关的操作能力，无法直接在Blender中创建3D模型"],
        "system_overrides": [],
    }

    changed = ground_task_contract_with_capabilities(
        contract,
        _snapshot(),
        user_content="帮我用blender建个二层小楼",
    )
    contract["success_conditions"] = success_conditions_for_contract(contract)
    preflight = preflight_task_capabilities(contract, _snapshot())

    assert changed is True
    assert contract["capability_ids"] == ["mcp.blender"]
    assert contract["requires_write"] is False
    assert contract["requires_state_change"] is True
    assert contract["deliverables"] == [
        {
            "kind": "external_state",
            "path_hint": "",
            "path_policy": "hint",
            "capability_id": "mcp.blender",
            "description": "使用Blender创建一个二层小楼的3D模型",
        }
    ]
    assert contract["blockers"] == []
    assert "capability_grounded" in contract["system_overrides"]
    assert "target_deliverable_success" in contract["success_conditions"]
    assert preflight["ok"] is True
    assert preflight["schema_version"] == "capability_preflight.v2"
    assert preflight["readiness_issues"] == []
    assert preflight["route_hint"]["policy"] == "advisory"
    assert "mcp_blender.execute_blender_code" in preflight["preferred_tool_ids"]
    assert "mcp_blender.get_scene_info" in preflight["preferred_tool_ids"]


def test_grounding_preserves_explicit_file_artifact_request() -> None:
    contract = {
        "intent": "write_required",
        "goal": "Create and export a Blender model",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "capability_ids": [],
        "deliverables": [
            {
                "kind": "file",
                "path_hint": "house.blend",
                "path_policy": "hint",
                "description": "Saved Blender file",
            }
        ],
        "first_action": "plan",
        "blockers": [],
        "system_overrides": [],
    }

    changed = ground_task_contract_with_capabilities(
        contract,
        _snapshot(),
        user_content="Use Blender to create a small house and save as house.blend",
    )

    assert changed is True
    assert contract["capability_ids"] == ["mcp.blender"]
    assert contract["requires_write"] is True
    assert contract["deliverables"][0]["kind"] == "file"
    assert contract["deliverables"][0]["capability_id"] == "mcp.blender"


def test_grounding_does_not_promote_answer_only_question() -> None:
    contract = {
        "intent": "answer_only",
        "goal": "How to build a house in Blender?",
        "requires_write": False,
        "requires_state_change": False,
        "requires_verification": False,
        "capability_ids": [],
        "deliverables": [{"kind": "answer", "description": "Explanation"}],
        "system_overrides": [],
    }

    changed = ground_task_contract_with_capabilities(
        contract,
        _snapshot(),
        user_content="How to build a house in Blender?",
    )

    assert changed is False
    assert contract["capability_ids"] == []
    assert contract["deliverables"][0]["kind"] == "answer"


def test_grounding_uses_mcp_issue_when_dynamic_tools_are_unavailable() -> None:
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
                "code": "service_stopped",
                "source_type": "mcp",
                "source_id": "blender",
                "capability_id": "mcp.blender",
                "name": "Blender MCP",
                "message": "MCP service Blender MCP is stopped; start it before retrying.",
                "recommended_action": "start",
            }
        ],
    )
    contract = {
        "intent": "write_required",
        "goal": "Use Blender to create a two-story house",
        "requires_write": True,
        "requires_state_change": True,
        "requires_verification": True,
        "capability_ids": [],
        "deliverables": [
            {
                "kind": "file",
                "path_hint": "two_story_house.blend",
                "path_policy": "hint",
                "description": "A guessed Blender file",
            }
        ],
        "first_action": "plan",
        "blockers": ["Missing Blender capability"],
        "system_overrides": [],
    }

    changed = ground_task_contract_with_capabilities(
        contract,
        snapshot,
        user_content="Use Blender to create a two-story house",
    )
    preflight = preflight_task_capabilities(contract, snapshot)

    assert changed is True
    assert contract["capability_ids"] == ["mcp.blender"]
    assert contract["requires_write"] is False
    assert contract["deliverables"] == [
        {
            "kind": "external_state",
            "path_hint": "",
            "path_policy": "hint",
            "capability_id": "mcp.blender",
            "description": "Use Blender to create a two-story house",
        }
    ]
    assert contract["blockers"] == []
    assert preflight["target_capability_ids"] == ["mcp.blender"]
    assert preflight["advisories"][0]["code"] == "service_stopped"
    assert preflight["advisories"][0]["recommended_action"] == "start"
    assert preflight["preferred_tool_ids"] is None
