import pytest

from runtime.tool_media import inline_image_records, media_audit_records
from tests.fakes.image_output import image_output


def test_black_pixels_are_observations_and_binary_stays_out_of_audit():
    pytest.importorskip("PIL.Image")
    raw = image_output()
    records = inline_image_records(raw)
    image = records[0]
    assert image["delivery_status"] == "eligible"
    assert image["pixel_ranges"] == [[0, 0]] * 3 + [[255, 255]]
    assert image["uniform_pixels"] is True
    assert (image["width"], image["height"]) == (4, 3)
    assert image["data_url"].startswith("data:image/png;base64,")
    audit = media_audit_records(records)
    assert "data_url" not in audit[0]
    assert "visual_passed" not in audit[0]
    assert raw["mcp_content"][0]["data"]


@pytest.mark.parametrize("block,reason", [
    ({"mimeType": "text/html", "data": "eA=="}, "unsupported_mime"),
    ({"mimeType": [], "data": "eA=="}, "unsupported_mime"),
    ({"mimeType": "image/png", "data": "!!!"}, "invalid_base64"),
    ({"mimeType": "image/png", "data": ""}, "missing_image_data"),
])
def test_invalid_inline_image_has_explicit_omission_reason(block, reason):
    result = inline_image_records({"mcp_content": [{"type": "image", **block}]})
    assert result[0]["omission_reason"] == reason
    assert "data_url" not in result[0]


def test_image_budget_is_checked_before_decoding_and_count_is_bounded():
    image = image_output()["mcp_content"][0]
    assert inline_image_records({"mcp_content": [image]}, max_bytes=1)[0]["omission_reason"] == "image_byte_limit"
    result = inline_image_records({"mcp_content": [image] * 3})
    assert len([item for item in result if item.get("data_url")]) == 2
    assert result[2]["omission_reason"] == "image_count_limit"


def test_optional_image_inspector_missing_is_explicit(monkeypatch):
    import builtins
    original = builtins.__import__

    def without_pillow(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("optional image inspector unavailable")
        return original(name, *args, **kwargs)

    raw = image_output()
    monkeypatch.setattr(builtins, "__import__", without_pillow)
    record = inline_image_records(raw)[0]
    assert record["inspection_status"] == "inspector_unavailable"
    assert "uniform_pixels" not in record
    assert record["data_url"]


def test_attachment_image_size_budget_does_not_change_generic_inline_limit(monkeypatch):
    import base64
    from runtime import tool_media

    monkeypatch.setattr(tool_media, "inspect_image_bytes", lambda _: {"inspection_status": "inspector_unavailable"})
    raw = {"mcp_content": [{"type": "image", "mimeType": "image/png", "data": base64.b64encode(b"x" * (3 * 1024 * 1024)).decode()}]}
    assert inline_image_records(raw)[0]["omission_reason"] == "image_byte_limit"
    attachment = {**raw, "type": "attachment_image"}
    assert inline_image_records(attachment)[0]["delivery_status"] == "eligible"
    assert inline_image_records(attachment, max_bytes=1)[0]["omission_reason"] == "image_byte_limit"
