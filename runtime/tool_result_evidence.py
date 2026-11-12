"""工具结果的审计投影；保留结构化事实，不使用前端展示预算。"""

from __future__ import annotations

import json
from typing import Any

from runtime.tool_media import inline_image_records, media_audit_records


def tool_output_evidence(output: Any) -> dict[str, Any] | None:
    """完整保留路径、诊断及状态；内联媒体通过原始 ToolTask 输出追溯。"""
    if not isinstance(output, dict):
        return None if output is None else {"value": _without_inline_media(output)}
    evidence = _without_inline_media(output)
    content = output.get("mcp_content")
    if isinstance(content, list) and output.get("content") == json.dumps(content, ensure_ascii=False):
        # MCP 无文本输出时会把媒体块序列化为 content，避免再次复制其中的二进制。
        evidence["content"] = json.dumps(evidence["mcp_content"], ensure_ascii=False)
    images = inline_image_records(output)
    if images:
        evidence["inline_images"] = media_audit_records(images)
    return evidence


def _without_inline_media(value: Any) -> Any:
    if isinstance(value, dict):
        media_block = isinstance(value.get("type"), str) and value.get("type") in {"image", "audio"}
        result = {}
        for key, item in value.items():
            if media_block and key == "data" and isinstance(item, str):
                result["data_omitted"] = True
                result["data_chars"] = len(item)
            else:
                result[key] = _without_inline_media(item)
        return result
    if isinstance(value, list):
        return [_without_inline_media(item) for item in value]
    if isinstance(value, str) and value.startswith(("data:image/", "data:audio/", "data:video/")):
        return {"inline_media_omitted": True, "chars": len(value)}
    return value
