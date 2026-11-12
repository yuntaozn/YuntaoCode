"""内联工具图片的有界解码与像素事实，不判断画面是否满足任务目标。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import warnings
from typing import Any


MAX_INLINE_IMAGE_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENT_IMAGE_BYTES = 10 * 1024 * 1024
MAX_INLINE_IMAGES = 2
MAX_IMAGE_PIXELS = 16 * 1024 * 1024
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def image_context_ref(data_url: str) -> str:
    """只在审计中记录内容指纹，不复制图片或来源 URL。"""
    return hashlib.sha256(data_url.encode("utf-8")).hexdigest()


def inline_image_records(
    output: Any, *, max_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """解析 MCP 标准 image 块；返回的 data_url 仅用于临时模型传输。"""
    if not isinstance(output, dict) or not isinstance(output.get("mcp_content"), list):
        return []
    if max_bytes is None:
        # 用户原图沿用上传大小边界；其他内联图片仍使用默认紧凑预算。
        max_bytes = MAX_ATTACHMENT_IMAGE_BYTES if output.get("type") == "attachment_image" else MAX_INLINE_IMAGE_BYTES
    records = []
    for index, block in enumerate(output["mcp_content"]):
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        mime = block.get("mimeType")
        encoded = block.get("data")
        record: dict[str, Any] = {
            "content_index": index, "mime_type": mime if isinstance(mime, str) else "",
            "delivery_status": "omitted", "inspection_status": "not_inspected",
        }
        records.append(record)
        if len(records) > MAX_INLINE_IMAGES:
            record["omission_reason"] = "image_count_limit"
            continue
        if not isinstance(mime, str) or mime not in IMAGE_MIMES:
            record["omission_reason"] = "unsupported_mime"
            continue
        if not isinstance(encoded, str) or not encoded:
            record["omission_reason"] = "missing_image_data"
            continue
        if len(encoded) > ((max_bytes + 2) // 3) * 4:
            record["omission_reason"] = "image_byte_limit"
            continue
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            record["omission_reason"] = "invalid_base64"
            continue
        if not data or len(data) > max_bytes:
            record["omission_reason"] = "image_byte_limit"
            continue
        record.update(inspect_image_bytes(data))
        record["size"] = len(data)
        if record["inspection_status"] in {"invalid_image", "image_pixel_limit"}:
            record["omission_reason"] = record["inspection_status"]
            continue
        data_url = f"data:{mime};base64,{encoded}"
        record.update({"data_url": data_url, "image_ref": image_context_ref(data_url), "delivery_status": "eligible"})
    return records


def inspect_image_bytes(data: bytes) -> dict[str, Any]:
    """Pillow 是可选能力；缺少时明确记录未检查，不宣称图片有效或视觉通过。"""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return {"inspection_status": "inspector_unavailable"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    return {"inspection_status": "image_pixel_limit", "width": width, "height": height}
                extrema = image.convert("RGBA").getextrema()
                return {
                    "inspection_status": "observed", "width": width, "height": height,
                    "pixel_ranges": [list(pair) for pair in extrema],
                    "pixel_channels": ["R", "G", "B", "A"],
                    "uniform_pixels": all(low == high for low, high in extrema),
                }
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return {"inspection_status": "invalid_image"}


def media_audit_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """审计投影不能含图片二进制；原始块保留在 ToolTask。"""
    return [{key: value for key, value in record.items() if key != "data_url"} for record in records]
