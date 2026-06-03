from runtime.agent_strategy.capability_router import (
    build_capability_catalog,
    capability_from_tool_spec,
    format_capability_catalog_for_prompt,
    parse_task_route_proposal,
    validate_task_route_proposal,
)


def test_capability_from_explicit_pdf_tool_spec() -> None:
    capability = capability_from_tool_spec({
        "id": "document.extract_pdf_to_docx",
        "capability": "document.pdf_to_docx",
        "requires_confirmation": True,
        "artifacts": ["docx"],
        "long_running": True,
        "retry_safe": True,
    })

    assert capability.id == "document.pdf_to_docx"
    assert capability.tool_ids == ("document.extract_pdf_to_docx",)
    assert capability.artifacts == ("docx",)
    assert capability.requires_confirmation is True
    assert capability.long_running is True
    assert capability.retry_safe is True


def test_capability_catalog_groups_tools_by_namespace() -> None:
    catalog = build_capability_catalog([
        {"id": "filesystem.scan_folder", "requires_confirmation": False},
        {"id": "filesystem.read_file", "requires_confirmation": False},
        {"id": "filesystem.write_file", "requires_confirmation": True, "artifacts": ["file"]},
    ])

    assert len(catalog) == 1
    assert catalog[0].id == "filesystem.local_files"
    assert catalog[0].tool_ids == (
        "filesystem.scan_folder",
        "filesystem.read_file",
        "filesystem.write_file",
    )
    assert catalog[0].requires_confirmation is True
    assert catalog[0].artifacts == ("file",)


def test_capability_prompt_tells_model_not_to_invent_tools() -> None:
    catalog = build_capability_catalog([
        {"id": "document.extract_pdf_to_docx", "capability": "document.pdf_to_docx", "artifacts": ["docx"]},
    ])

    prompt = format_capability_catalog_for_prompt(catalog)

    assert "Capability Router" in prompt
    assert "不要发明不存在的工具" in prompt
    assert "document.pdf_to_docx" in prompt
    assert "document.extract_pdf_to_docx" in prompt


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
