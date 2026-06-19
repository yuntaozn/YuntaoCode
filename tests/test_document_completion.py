from runtime.agent_strategy.document_completion import (
    contract_expects_text_output,
    min_text_output_check,
    text_output_char_count,
)


def test_contract_expects_text_output_for_document_deliverable() -> None:
    assert contract_expects_text_output({
        "expected_min_output_chars": 12000,
        "deliverables": [{"kind": "document", "path_hint": "story.docx"}],
    })


def test_contract_does_not_treat_code_as_long_document() -> None:
    assert not contract_expects_text_output({
        "expected_min_output_chars": 12000,
        "deliverables": [{"kind": "code", "path_hint": "src/app.js"}],
    })


def test_text_output_char_count_uses_text_stats_not_file_size() -> None:
    event = {
        "tool": "filesystem.finalize_text_file",
        "status": "success",
        "output": {
            "size": 60000,
            "draft_stats": {"text_chars": 5200},
            "validation": {"valid": True, "text_chars": 5200},
        },
    }

    assert text_output_char_count(event) == 5200


def test_min_text_output_check_rejects_short_finalized_text_file() -> None:
    contract = {
        "expected_min_output_chars": 12000,
        "deliverables": [{"kind": "document", "path_hint": "story.docx"}],
    }
    check = min_text_output_check(
        [
            {
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": "story.txt"},
                "output": {
                    "path": "story.txt",
                    "draft_stats": {"text_chars": 5200},
                    "validation": {"valid": True, "text_chars": 5200},
                },
            }
        ],
        expected_min_output_chars=12000,
        task_contract=contract,
        workspace_path="D:/workspace",
        mode="document",
    )

    assert check["required"] is True
    assert check["ok"] is False
    assert check["reason"] == "document_output_too_short"
    assert check["observed"] == 5200
