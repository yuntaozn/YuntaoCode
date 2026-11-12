"""从 ConversationMessagesStreamHandler 提取的提示构建函数。

所有函数都是纯函数：只依赖参数并产生确定性字符串输出；
不使用 ``self``，不执行 I/O，也不产生 i18n 副作用。"""

from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Runtime 证据提示
# ---------------------------------------------------------------------------

def missing_tool_call_payload_prompt(protocol_error: str = "missing_tool_call_payload") -> str:
    """返回协议校验事实，不要求重试、改路或结束。"""
    return json.dumps({
        "kind": "model_protocol_error", "code": protocol_error,
        "executed_tool_calls": 0,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Task 级提示
# ---------------------------------------------------------------------------


def max_rounds_message(max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
    lines = [
        f"本轮已用完当前工具执行预算（{max_rounds} 轮）。运行记录已保存，可基于已有事实继续、恢复或换策略。",
        "",
    ]
    if tool_events:
        lines.append("最近的工具调用：")
        for event in tool_events[-6:]:
            tool = event.get("tool") or event.get("name") or "unknown"
            status = event.get("status") or "unknown"
            path = ""
            event_input = event.get("input")
            if isinstance(event_input, dict):
                path = str(event_input.get("path") or "")
            error = event.get("error") or ""
            detail = f"- {tool}: {status}"
            if path:
                detail += f"（{path}）"
            if error:
                detail += f"；错误：{error}"
            lines.append(detail)
    else:
        lines.append("本轮没有成功产生可记录的工具调用。")
    lines.extend([
        "",
        "后续可继续依据：以上工具事实、用户后续补充、关键文件、关键词或期望结果。",
    ])
    return "\n".join(lines)
