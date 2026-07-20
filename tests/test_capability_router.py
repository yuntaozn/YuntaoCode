from runtime.agent_strategy.capability_router import (
    build_capability_catalog,
    capability_from_tool_spec,
    format_capability_catalog_for_prompt,
    order_tool_specs_for_model_prompt,
    parse_task_route_proposal,
    validate_task_route_proposal,
)


def test_capability_from_explicit_pdf_tool_spec() -> None:
    capability = capability_from_tool_spec({
        "id": "document.extract_pdf_to_docx",
        "capability": "document.pdf_to_docx",
        "requires_confirmation": True,
        "artifacts": ["docx"],
        "verification_strength": "standard",
        "long_running": True,
        "retry_safe": True,
    })

    assert capability.id == "document.pdf_to_docx"
    assert capability.tool_ids == ("document.extract_pdf_to_docx",)
    assert capability.artifacts == ("docx",)
    assert capability.verification_strengths == ("standard",)
    assert capability.requires_confirmation is True
    assert capability.long_running is True
    assert capability.retry_safe is True


def test_capability_catalog_keeps_read_files_separate_from_text_writes() -> None:
    catalog = build_capability_catalog([
        {"id": "filesystem.scan_folder", "requires_confirmation": False},
        {"id": "filesystem.read_file", "requires_confirmation": False},
        {"id": "filesystem.write_file", "requires_confirmation": True, "artifacts": ["file"]},
    ])
    by_id = {item.id: item for item in catalog}

    assert by_id["filesystem.local_files"].tool_ids == (
        "filesystem.scan_folder",
        "filesystem.read_file",
    )
    assert by_id["filesystem.local_files"].requires_confirmation is False
    assert by_id["code.text_write"].tool_ids == ("filesystem.write_file",)
    assert by_id["code.text_write"].requires_confirmation is True
    assert by_id["code.text_write"].artifacts == ("file",)


def test_capability_catalog_groups_all_text_code_write_routes() -> None:
    catalog = build_capability_catalog([
        {"id": "code.apply_patch", "requires_confirmation": True, "artifacts": ["file"]},
        {"id": "code.edit_file", "requires_confirmation": True, "artifacts": ["file"]},
        {"id": "code.replace_text", "requires_confirmation": True, "artifacts": ["file"]},
        {"id": "filesystem.write_file", "requires_confirmation": True, "artifacts": ["file"]},
        {"id": "filesystem.create_text_draft", "artifacts": ["text_draft"]},
        {"id": "filesystem.append_text_chunk", "artifacts": ["text_draft"]},
        {"id": "filesystem.inspect_text_draft", "artifacts": ["text_draft"]},
        {"id": "filesystem.finalize_text_file", "requires_confirmation": True, "artifacts": ["file", "text_draft"]},
    ])

    [capability] = catalog

    assert capability.id == "code.text_write"
    assert capability.tool_ids == (
        "filesystem.create_text_draft",
        "filesystem.append_text_chunk",
        "filesystem.inspect_text_draft",
        "filesystem.finalize_text_file",
        "code.edit_file",
        "code.replace_text",
        "code.apply_patch",
        "filesystem.write_file",
    )
    assert capability.requires_confirmation is True
    assert capability.artifacts == ("file", "text_draft")


def test_text_write_tools_are_ordered_for_chunk_first_model_prompting() -> None:
    specs = [
        {"id": "filesystem.scan_folder"},
        {"id": "filesystem.write_file"},
        {"id": "filesystem.apply_changes"},
        {"id": "filesystem.create_text_draft"},
        {"id": "filesystem.append_text_chunk"},
        {"id": "filesystem.finalize_text_file"},
        {"id": "git.status"},
    ]

    ordered = [item["id"] for item in order_tool_specs_for_model_prompt(specs)]

    assert ordered == [
        "filesystem.scan_folder",
        "filesystem.create_text_draft",
        "filesystem.append_text_chunk",
        "filesystem.finalize_text_file",
        "filesystem.apply_changes",
        "filesystem.write_file",
        "git.status",
    ]


def test_capability_catalog_keeps_local_file_state_separate_from_text_write() -> None:
    catalog = build_capability_catalog([
        {
            "id": "filesystem.delete_file",
            "requires_confirmation": True,
            "artifacts": ["file"],
            "effects": ["file_delete", "local_state_change"],
            "roles": ["deliverable", "verification"],
            "verification_strength": "standard",
        },
        {"id": "filesystem.write_file", "requires_confirmation": True, "artifacts": ["file"]},
    ])
    by_id = {item.id: item for item in catalog}

    assert by_id["filesystem.local_state"].tool_ids == ("filesystem.delete_file",)
    assert by_id["filesystem.local_state"].effects == ("file_delete", "local_state_change")
    assert by_id["filesystem.local_state"].roles == ("deliverable", "verification")
    assert by_id["filesystem.local_state"].verification_strengths == ("standard",)
    assert by_id["code.text_write"].tool_ids == ("filesystem.write_file",)


def test_capability_catalog_exposes_filesystem_change_set() -> None:
    catalog = build_capability_catalog([
        {
            "id": "filesystem.apply_changes",
            "capability": "filesystem.change_set",
            "requires_confirmation": True,
            "artifacts": ["file"],
            "effects": ["file_write", "file_delete", "local_state_change"],
            "roles": ["deliverable", "verification"],
            "verification_strength": "standard",
        },
    ])

    [capability] = catalog

    assert capability.id == "filesystem.change_set"
    assert capability.tool_ids == ("filesystem.apply_changes",)
    assert capability.requires_confirmation is True
    assert capability.effects == ("file_delete", "file_write", "local_state_change")
    assert capability.roles == ("deliverable", "verification")
    assert capability.verification_strengths == ("standard",)


def test_capability_prompt_tells_model_not_to_invent_tools() -> None:
    catalog = build_capability_catalog([
        {"id": "document.extract_pdf_to_docx", "capability": "document.pdf_to_docx", "artifacts": ["docx"]},
    ])

    prompt = format_capability_catalog_for_prompt(catalog)

    assert "Capability Router" in prompt
    assert "不要发明不存在的工具" in prompt
    assert "document.pdf_to_docx" in prompt
    assert "document.extract_pdf_to_docx" in prompt


def test_compact_capability_prompt_exposes_roles_and_verification_strengths() -> None:
    catalog = build_capability_catalog([
        {
            "id": "shell.run_command",
            "capability": "shell.local_command",
            "artifacts": ["command_output"],
            "roles": ["execution", "verification"],
            "verification_strength": "standard",
        },
    ])

    prompt = format_capability_catalog_for_prompt(catalog, compact=True)

    assert "roles=execution,verification" in prompt
    assert "verification=standard" in prompt


def test_validate_task_route_proposal_accepts_known_capability_tool_pair() -> None:
    catalog = build_capability_catalog([
        {"id": "document.extract_pdf_to_docx", "capability": "document.pdf_to_docx", "artifacts": ["docx"]},
    ])
    proposal = parse_task_route_proposal({
        "goal": "把 PDF 转成带图片和文字的 Word",
        "capability_id": "document.pdf_to_docx",
        "tool_id": "document.extract_pdf_to_docx",
        "expected_artifacts": ["docx"],
        "requires_write": True,
        "requires_verification": True,
        "confidence": 1.5,
    })

    result = validate_task_route_proposal(proposal, catalog)

    assert proposal.confidence == 1.0
    assert result["ok"] is True
    assert result["errors"] == []


def test_validate_task_route_proposal_rejects_unknown_tool_for_capability() -> None:
    catalog = build_capability_catalog([
        {"id": "document.extract_pdf_to_docx", "capability": "document.pdf_to_docx", "artifacts": ["docx"]},
    ])
    proposal = parse_task_route_proposal({
        "goal": "把 PDF 转成 Word",
        "capability_id": "document.pdf_to_docx",
        "tool_id": "filesystem.write_file",
    })

    result = validate_task_route_proposal(proposal, catalog)

    assert result["ok"] is False
    assert result["errors"] == ["tool_not_in_capability"]
