from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import runtime.run_finalizer as finalizer_module
from runtime.run_execution_state import RunExecutionState
from runtime.run_finalizer import (
    RunFinalizationRequest,
    RunFinalizer,
    initial_assistant_content,
)


def _initial_content(**overrides: Any) -> str:
    values = {
        "model_content": "模型结论",
        "model_provider_error": "",
        "convergence_stopped": False,
        "has_successful_write": False,
        "max_rounds_exceeded": False,
        "max_rounds_after_write_message": "写入后的轮次提示",
        "max_rounds_message": "普通轮次提示",
        "tool_contract_failed": False,
        "contract_failures": [],
    }
    values.update(overrides)
    return initial_assistant_content(**values)


def test_initial_content_preserves_model_text_before_provider_error_fact() -> None:
    content = _initial_content(model_provider_error="provider unavailable")

    assert content.startswith("模型结论\n\n")
    assert "模型服务在工具执行后返回错误" in content


def test_initial_content_distinguishes_convergence_after_a_write() -> None:
    content = _initial_content(
        convergence_stopped=True,
        has_successful_write=True,
    )

    assert "已有文件写入成功" in content
    assert "停止重复重试" in content


def test_initial_content_uses_write_specific_round_limit_message() -> None:
    content = _initial_content(
        max_rounds_exceeded=True,
        has_successful_write=True,
    )

    assert content == "写入后的轮次提示"


def test_initial_content_preserves_model_text_when_contract_gap_exists() -> None:
    content = _initial_content(
        tool_contract_failed=True,
        contract_failures=["document_output_too_short"],
    )

    assert content == "模型结论"


def test_initial_content_reports_neutral_contract_gap_without_model_text() -> None:
    content = _initial_content(
        model_content="",
        tool_contract_failed=True,
        contract_failures=["missing_target_verification"],
    )

    assert content.startswith("运行事实提示")
    assert "系统不会" not in content
    assert "未完整完成" not in content


def test_initial_content_keeps_ordinary_model_answer() -> None:
    assert _initial_content() == "模型结论"


class _Message:
    def __init__(self, role: str, content: str, metadata: dict[str, Any]) -> None:
        self.role = role
        self.content = content
        self.metadata = metadata

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
        }


class _Conversation:
    workspace_id = "workspace-1"

    def __init__(self) -> None:
        self.messages: list[_Message] = []

    def to_public_dict(self, *, include_messages: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": "conversation-1"}
        if include_messages:
            payload["messages"] = [message.to_public_dict() for message in self.messages]
        return payload


class _ConversationStore:
    def __init__(self, conversation: _Conversation) -> None:
        self.conversation = conversation

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any],
    ) -> _Message:
        assert conversation_id == "conversation-1"
        message = _Message(role, content, metadata)
        self.conversation.messages.append(message)
        return message


class _Settings:
    def get_model_config(self, model: str) -> dict[str, Any]:
        return {"context_limit": 4096}


class _FinalizationHost:
    def __init__(self, conversation: _Conversation) -> None:
        self.runtime = SimpleNamespace(
            conversations=_ConversationStore(conversation),
            settings=_Settings(),
        )
        self.events: list[dict[str, Any]] = []
        self.flush_count = 0

    def _task_contract_failures(self, *args: Any) -> list[str]:
        return []

    def _max_rounds_after_write_message(self, *args: Any) -> str:
        return "after-write"

    def _max_rounds_message(self, *args: Any) -> str:
        return "max-rounds"

    async def _build_change_summary(self, *args: Any) -> None:
        return None

    def _answer_only_final_answer_error(self, *args: Any) -> str:
        return ""

    def _needs_synthesized_final_answer(self, *args: Any, **kwargs: Any) -> bool:
        return False

    async def _generate_result_synthesis_answer(self, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        raise AssertionError("ordinary finalization must not request another model answer")

    def _synthesize_failure_answer(self, *args: Any) -> str:
        raise AssertionError("unexpected failure fallback")

    def _synthesize_partial_answer(self, *args: Any) -> str:
        raise AssertionError("unexpected partial fallback")

    def _synthesize_final_answer(self, *args: Any) -> str:
        raise AssertionError("unexpected final fallback")

    def _build_execution_notice(self, *args: Any, **kwargs: Any) -> str:
        return ""

    def _build_model_messages(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "hello"}]

    def _run_status_from_result(self, run_result: dict[str, Any]) -> str:
        return str(run_result["status"])

    def write_event(self, payload: dict[str, Any]) -> None:
        self.events.append(payload)

    async def flush(self, include_footers: bool = False) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
async def test_finalizer_publishes_result_persists_answer_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finalizer_module, "count_messages_tokens", lambda messages: 7)
    conversation = _Conversation()
    host = _FinalizationHost(conversation)
    metadata: dict[str, Any] = {"effective_context_limit": 4096}
    workspace = SimpleNamespace(
        path="D:/workspace",
        to_public_dict=lambda: {"id": "workspace-1", "path": "D:/workspace"},
    )
    execution_state = RunExecutionState.create(20)
    execution_state.record_guidance()
    execution_state.malformed_tool_call_retries = 1
    execution_state.progress_observer_count = 1
    execution_state.stagnant_rounds = 2
    execution_state.completion_review.begin(
        event_count=0,
        run_result={"status": "no_tool_activity"},
    )

    outcome = await RunFinalizer(host).finalize(
        RunFinalizationRequest(
            conversation_id="conversation-1",
            conversation=conversation,
            workspace=workspace,
            model="test-model",
            mode_config={},
            effective_mode="analysis",
            user_content="解释这个项目",
            metadata=metadata,
            content_parts=["这是模型的回答。"],
            reasoning_parts=["内部推理"],
            tool_events=[],
            task_contract={
                "requires_write": False,
                "requires_state_change": False,
                "requires_verification": False,
            },
            workspace_snapshot={},
            active_focus={},
            capability_snapshot={},
            capability_preflight={},
            context_hygiene_report={},
            run=SimpleNamespace(id="run-1", task_id=""),
            execution_plan=None,
            change_baseline=None,
            execution_state=execution_state,
            requires_code_write=False,
            recon_tool_count=0,
            write_repair_mode=False,
            context_tokens=3,
        )
    )

    assert outcome.assistant_content == "这是模型的回答。"
    assert outcome.run_result["status"] == "no_tool_activity"
    assert outcome.context_tokens == 7
    assert conversation.messages[-1].content == "这是模型的回答。"
    assert metadata["reasoning"] == "内部推理"
    assert metadata["runtime_intervention_count"] == 1
    assert metadata["malformed_tool_call_retries"] == 1
    assert metadata["progress_observer_count"] == 1
    assert metadata["stagnant_rounds"] == 2
    assert metadata["completion_review_count"] == 1
    assert [event["event"] for event in host.events] == [
        "context_pack",
        "result",
        "context_pack",
        "done",
    ]
    assert host.events[-1]["run_status"] == "no_tool_activity"
    assert host.events[-1]["context_tokens"] == 7
    assert host.flush_count == 2
