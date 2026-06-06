from runtime.agent_strategy.tool_event_roles import (
    DELIVERABLE,
    EVIDENCE,
    VERIFICATION,
    classify_tool_event_role,
    deliverable_verification_events,
    successful_deliverable_events,
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
