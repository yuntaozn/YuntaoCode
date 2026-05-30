import pytest

from runtime.tool_registry import ToolRegistry, ToolSpec


async def _noop_handler(input_data, context):
    return {"ok": True}


def test_tool_registry_rejects_duplicate_tool_ids() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        id="demo.tool",
        name="Demo Tool",
        description="Demo",
        input_schema={"type": "object"},
    )

    registry.register(spec, _noop_handler)

    with pytest.raises(ValueError):
        registry.register(spec, _noop_handler)


def test_tool_spec_reports_missing_optional_dependencies() -> None:
    spec = ToolSpec(
        id="demo.optional",
        name="Optional Demo",
        description="Demo",
        input_schema={"type": "object"},
        optional_dependencies=["definitely_missing_yuntaocode_dependency"],
    )

    assert spec.check_dependencies() == {
        "definitely_missing_yuntaocode_dependency": False,
    }


def test_list_specs_includes_public_metadata() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            id="demo.read",
            name="Demo Read",
            description="Reads demo data",
            input_schema={"type": "object"},
            requires_confirmation=False,
            local_only=True,
        ),
        _noop_handler,
    )

    specs = registry.list_specs()

    assert specs == [
        {
            "id": "demo.read",
            "name": "Demo Read",
            "description": "Reads demo data",
            "input_schema": {"type": "object"},
            "requires_confirmation": False,
            "local_only": True,
            "dependencies": {},
        }
    ]
