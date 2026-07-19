from runtime.context_audit import build_context_audit


def test_context_audit_summarizes_historical_and_current_context() -> None:
    audit = build_context_audit({
        "run": {"task_id": "task-current"},
        "context_packs": [
            {
                "phase": "task_contract",
                "ledger": {
                    "records": [
                        {
                            "index": 0,
                            "kind": "user_intent",
                            "source_id": "current_user_message",
                            "source_type": "user_message",
                            "trust": "user_provided",
                            "freshness": "current",
                            "task_id": "task-current",
                            "token_estimate": 12,
                            "content_preview": "Create a lesson page",
                        },
                        {
                            "index": 1,
                            "kind": "task_lineage",
                            "source_id": "task_lineage_candidates",
                            "source_type": "conversation_history",
                            "trust": "runtime_fact",
                            "freshness": "recent",
                            "task_id": "task-old",
                            "token_estimate": 90,
                            "content_preview": "Historical task candidates",
                        },
                        {
                            "index": 2,
                            "kind": "memory",
                            "source_id": "memory_selection",
                            "source_type": "memory_store",
                            "trust": "memory",
                            "freshness": "stored",
                            "task_id": "task-current",
                            "token_estimate": 36,
                            "content_preview": "Selected user memory",
                        },
                    ],
                },
            },
            {
                "phase": "planning",
                "ledger": {
                    "records": [
                        {
                            "index": 0,
                            "kind": "task_contract",
                            "source_id": "current_task_contract",
                            "source_type": "runtime_event",
                            "trust": "runtime_fact",
                            "freshness": "current",
                            "task_id": "task-current",
                            "token_estimate": 25,
                            "content_preview": "Current task contract",
                        },
                        {
                            "index": 1,
                            "kind": "risk",
                            "source_id": "context_hygiene",
                            "source_type": "runtime_event",
                            "trust": "runtime_fact",
                            "freshness": "current",
                            "task_id": "task-current",
                            "token_estimate": 8,
                            "content_preview": "Historical model context was sanitized",
                        },
                        {
                            "index": 2,
                            "kind": "tool_result",
                            "source_id": "recent_tool_events",
                            "source_type": "run_event",
                            "trust": "runtime_fact",
                            "freshness": "current",
                            "task_id": "task-current",
                            "token_estimate": 14,
                            "content_preview": "Current run tool result",
                        },
                    ],
                },
            },
        ],
    })

    assert audit["schema_version"] == "context_audit.v1"
    assert audit["boundary"] == "audit_only"
    assert audit["counts"]["context_packs"] == 2
    assert audit["counts"]["records"] == 6
    assert audit["counts"]["token_estimate"] == 185
    assert audit["counts"]["historical_records"] == 2
    assert audit["counts"]["memory_records"] == 1
    assert audit["counts"]["task_lineage_records"] == 1
    assert audit["counts"]["hygiene_records"] == 1
    assert audit["counts"]["different_task_records"] == 1
    assert audit["flags"]["has_historical_context"] is True
    assert audit["flags"]["has_memory_context"] is True
    assert audit["flags"]["has_task_lineage"] is True
    assert audit["flags"]["has_context_hygiene"] is True
    assert audit["phase_summary"][0]["phase"] == "task_contract"
    assert audit["phase_summary"][0]["historical_records"] == 2
    assert audit["historical_records"][0]["kind"] == "task_lineage"
    assert audit["hygiene_records"][0]["source_id"] == "context_hygiene"


def test_context_audit_is_empty_for_missing_evidence() -> None:
    audit = build_context_audit(None)

    assert audit["schema_version"] == "context_audit.v1"
    assert audit["counts"]["records"] == 0
    assert audit["flags"]["has_context"] is False
