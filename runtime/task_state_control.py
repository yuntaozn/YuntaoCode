"""主执行模型可选的任务状态声明协议。

声明只更新 Run 的审计状态，不执行外部动作，也不授予权限或证明产物完成。
普通能力调用无需先通过此协议；任务语义始终由同一主执行模型负责。
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Awaitable, Callable

from runtime.agent_strategy.classifiers import finish_reason_indicates_truncation
from runtime.agent_strategy.task_contract import VALID_INTENTS, merge_model_task_contract


TASK_STATE_TOOL_ID = "runtime.update_task"
TASK_STATE_TOOL_NAME = "runtime__update_task"



def task_state_tool() -> dict[str, Any]:
    """返回只属于当前 Run 的模型协议工具，不注册为外部能力。"""
    return {
        "type": "function",
        "function": {
            "name": TASK_STATE_TOOL_NAME,
            "description": (
                "Optionally record or revise your understanding of the current task and plan. "
                "Use the user conversation and observed tool results to decide what remains. "
                "This is audit bookkeeping, not a prerequisite to other tools, a permission grant, "
                "or proof that a deliverable exists. Only include fields that changed. "
                "Completion records your goal_closed, remaining_work, and verification_limits "
                "independently of runtime evidence; it can be sent without restating the task. "
                "Use step_updates to report plan progress with optional observed tool_task_ids."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "minLength": 1, "maxLength": 240, "pattern": r"\S"},
                    "intent": {"type": "string", "enum": sorted(VALID_INTENTS)},
                    "requires_write": {"type": "boolean"},
                    "requires_state_change": {"type": "boolean"},
                    "requires_verification": {"type": "boolean"},
                    "required_verification_modalities": {
                        "type": "array", "maxItems": 6, "items": {"type": "string", "enum": ["structural", "visual", "behavioral", "content"]},
                    },
                    "capability_ids": {"type": "array", "maxItems": 6, "items": {"type": "string", "minLength": 1, "maxLength": 120, "pattern": r"\S"}},
                    "deliverables": {
                        "type": "array", "maxItems": 8, "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["file", "answer", "document", "code", "external_state"]},
                                "path_hint": {"type": "string", "maxLength": 180},
                                "capability_id": {"type": "string", "maxLength": 120},
                                "description": {"type": "string", "maxLength": 240},
                            },
                            "required": ["kind"], "additionalProperties": False,
                        },
                    },
                    "plan": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 260}},
                    "completion": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "goal_closed": {"type": "boolean"},
                            "remaining_work": {"type": "array", "items": {"type": "string", "maxLength": 500}, "maxItems": 12},
                            "verification_limits": {"type": "array", "items": {"type": "string", "maxLength": 500}, "maxItems": 12},
                        },
                        "required": ["goal_closed"],
                    },
                    "step_updates": {
                        "type": "array", "maxItems": 8,
                        "items": {
                            "type": "object", "additionalProperties": False,
                            "properties": {
                                "index": {"type": "integer", "minimum": 0},
                                "status": {"type": "string", "enum": ["pending", "running", "completed", "failed", "skipped"]},
                                "tool_task_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 24},
                                "note": {"type": "string", "maxLength": 500},
                            },
                            "required": ["index", "status"],
                        },
                    },
                },
                "minProperties": 1,
                "additionalProperties": False,
            },
        },
    }


def _validate_declaration_value(value: Any, schema: dict[str, Any], path: str = "task") -> None:
    """只校验声明 Schema 使用的结构约束；不判断任务语义或工具执行证据。"""
    kind = schema["type"]
    matches = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "integer": type(value) is int,
    }
    if not matches[kind]:
        raise ValueError(f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} has an unsupported value")
    if kind == "object":
        properties = schema["properties"]
        if len(value) < schema.get("minProperties", 0):
            raise ValueError(f"{path} must contain an update")
        if any(key not in value for key in schema.get("required", [])):
            raise ValueError(f"{path} is missing required fields")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(f"{path} has unknown fields; permissions cannot be changed")
        for key, item in value.items():
            _validate_declaration_value(item, properties[key], f"{path}.{key}")
    elif kind == "array":
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"{path} exceeds maxItems={schema['maxItems']}")
        for index, item in enumerate(value):
            _validate_declaration_value(item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        if len(value) < schema.get("minLength", 0) or ("maxLength" in schema and len(value) > schema["maxLength"]):
            raise ValueError(f"{path} has an invalid length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{path} must contain non-whitespace text")
    elif kind == "integer" and value < schema.get("minimum", value):
        raise ValueError(f"{path} is below minimum={schema['minimum']}")


class TaskStateControl:
    def __init__(
        self,
        contract: dict[str, Any],
        on_update: Callable[[dict[str, Any], list[str] | None, dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.contract = deepcopy(contract)
        self._on_update = on_update

    async def handle_call(
        self,
        tool_call: dict[str, Any],
        tool_id: str,
        arguments: dict[str, Any],
        finish_reason: str,
    ) -> dict[str, Any] | None:
        if tool_id != TASK_STATE_TOOL_ID:
            return None
        try:
            if finish_reason_indicates_truncation(finish_reason):
                raise ValueError("Task declaration was truncated; no task state was changed.")
            _validate_declaration_value(arguments, task_state_tool()["function"]["parameters"])
            completion = arguments.get("completion")
            updates = arguments.get("step_updates", [])
            semantic_fields = set(task_state_tool()["function"]["parameters"]["properties"]) - {"plan", "completion", "step_updates"}
            # 省略字段表示沿用已声明理解，避免只报告进度时清空交付物和验证要求。
            changed = {key: value for key, value in arguments.items() if key in semantic_fields}
            contract = deepcopy(self.contract)
            if changed:
                raw = {key: deepcopy(value) for key, value in self.contract.items() if key in semantic_fields}
                raw.update(changed)
                if raw.get("required_verification_modalities") and not raw.get("requires_verification"):
                    raise ValueError("required_verification_modalities requires requires_verification=true")
                contract = merge_model_task_contract(raw, self.contract)
                contract["source"] = "model_execution"
                contract["model_explicit_fields"] = sorted(changed)
            if contract.get("required_verification_modalities") and not contract.get("requires_verification"):
                raise ValueError("required_verification_modalities requires requires_verification=true")
            plan = arguments.get("plan")
            await self._on_update(contract, plan, {"completion": completion, "step_updates": updates})
            self.contract = deepcopy(contract)
            result = {
                "status": "recorded", "goal": contract["goal"],
                "requires_write": contract["requires_write"],
                "requires_state_change": contract["requires_state_change"],
                "requires_verification": contract["requires_verification"],
                "execution_performed": False,
            }
        except ValueError as exc:
            result = {"status": "rejected", "error": str(exc), "execution_performed": False}
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": tool_call["function"]["name"],
            "content": json.dumps(result, ensure_ascii=False),
        }
