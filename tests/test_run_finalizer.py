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
        "max_rounds_exceeded": False,
        "round_limit": 20,
    }
    values.update(overrides)
    return initial_assistant_content(**values)


def test_initial_content_preserves_model_text_when_provider_errors() -> None:
    content = _initial_content(model_provider_error="provider unavailable")

    assert content == "模型结论"


def test_initial_content_reports_round_limit_only_when_model_answer_is_missing() -> None:
    content = _initial_content(
        max_rounds_exceeded=True,
        model_content="",
    )

    assert content == "执行轮次预算已用完（20 轮），模型未返回最终内容。"


def test_initial_content_without_model_text_is_only_a_missing_answer_placeholder() -> None:
    assert _initial_content(model_content="") == "模型未返回最终内容。"


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

    async def _wait_if_paused(self) -> None:
        pass

    def _task_contract_failures(self, *args: Any, **kwargs: Any) -> list[str]:
        raise AssertionError("finalization must use RunResult rather than a second contract judge")

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


class _SynthesizingHost(_FinalizationHost):
    def __init__(self, conversation: _Conversation) -> None:
        super().__init__(conversation)
        self.synthesis_kwargs: dict[str, Any] = {}

    def _needs_synthesized_final_answer(self, *args: Any, **kwargs: Any) -> bool:
        return True

    async def _generate_result_synthesis_answer(self, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        self.synthesis_kwargs = kwargs
        return "基于运行事实生成的最终总结。", {"model": "test-model"}


class _AnswerRepairHost(_SynthesizingHost):
    async def _generate_result_synthesis_answer(self, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        self.synthesis_kwargs = kwargs
        return "这是基于运行证据生成的完整分析结论。" * 10, {"model": "test-model"}


@pytest.mark.asyncio
async def test_finalizer_publishes_result_persists_answer_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finalizer_module, "count_messages_tokens", lambda messages: 7)
    result_calls = []
    build_result = finalizer_module.build_run_result

    def observe_result(**kwargs):
        result_calls.append(kwargs)
        return build_result(**kwargs)

    monkeypatch.setattr(finalizer_module, "build_run_result", observe_result)
    conversation = _Conversation()
    host = _FinalizationHost(conversation)
    metadata: dict[str, Any] = {"effective_context_limit": 4096}
    workspace = SimpleNamespace(
        path="D:/workspace",
        to_public_dict=lambda: {"id": "workspace-1", "path": "D:/workspace"},
    )
    execution_state = RunExecutionState.create(20)
    execution_state.record_guidance()

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
            capability_preflight={
                "advisories": [{
                    "code": "service_stopped",
                    "message": "Optional service is not ready.",
                }],
            },
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
    assert len(result_calls) == 1
    assert result_calls[0]["answer_text"] == outcome.assistant_content
    assert outcome.run_result["status"] == "no_tool_activity"
    assert outcome.run_result["capability_advisories"][0]["code"] == "service_stopped"
    assert "capability_preflight_advisory" in outcome.run_result["risks"]
    assert outcome.context_tokens == 7
    assert conversation.messages[-1].content == "这是模型的回答。"
    assert metadata["reasoning"] == "内部推理"
    assert metadata["guidance_count"] == 1
    assert metadata["runtime_intervention_count"] == 1
    assert [event["event"] for event in host.events] == [
        "context_pack",
        "result",
        "context_pack",
        "done",
    ]
    assert host.events[-1]["run_status"] == "no_tool_activity"
    assert host.events[-1]["context_tokens"] == 7
    assert host.flush_count == 2


@pytest.mark.asyncio
async def test_finalizer_keeps_main_model_answer_without_secondary_synthesis_or_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finalizer_module, "count_messages_tokens", lambda messages: 9)
    conversation = _Conversation()
    host = _SynthesizingHost(conversation)
    metadata: dict[str, Any] = {
        "effective_context_limit": 4096,
        "completion_decisions": [{
            "review_count": 1,
            "action": "final_answer_candidate",
            "self_assessment": {
                "schema_version": "completion_self_assessment.v1",
                "kind": "completion_self_assessment",
                "goal_closed": False,
                "remaining_work": ["run the browser verification"],
                "verification_limits": ["no rendered preview was observed"],
            },
        }],
        "task_route_evidence": {
            "schema_version": "task_route_evidence.v1",
            "kind": "task_route_evidence",
            "strategy_owner": "model",
            "proposal_count": 1,
        },
    }
    workspace = SimpleNamespace(
        path="D:/workspace",
        to_public_dict=lambda: {"id": "workspace-1", "path": "D:/workspace"},
    )
    tool_events = [
        {
            "event": "tool",
            "tool": "filesystem.write_file",
            "status": "success",
            "input": {"path": "viewer.html"},
            "output": {"path": "viewer.html"},
        }
    ]

    outcome = await RunFinalizer(host).finalize(
        RunFinalizationRequest(
            conversation_id="conversation-1",
            conversation=conversation,
            workspace=workspace,
            model="test-model",
            mode_config={},
            effective_mode="terminal",
            user_content="创建 viewer.html",
            metadata=metadata,
            content_parts=["Done."],
            reasoning_parts=[],
            tool_events=tool_events,
            task_contract={
                "goal": "创建 viewer.html",
                "requires_write": True,
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
            execution_state=RunExecutionState.create(20),
            requires_code_write=True,
            recon_tool_count=0,
            write_repair_mode=False,
            context_tokens=4,
        )
    )

    assert outcome.assistant_content == "Done."
    assert host.synthesis_kwargs == {}
    assert outcome.run_result["completion_assessment"]["goal_closed"] is False
    assert "synthesized_final_answer" not in metadata
    assert "changed_files_footer_appended" not in metadata



@pytest.mark.asyncio
async def test_missing_final_answer_is_not_replaced_by_a_second_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finalizer_module, "count_messages_tokens", lambda messages: 9)
    conversation = _Conversation()
    host = _AnswerRepairHost(conversation)
    metadata: dict[str, Any] = {}
    workspace = SimpleNamespace(
        path="D:/workspace",
        to_public_dict=lambda: {"id": "workspace-1", "path": "D:/workspace"},
    )

    outcome = await RunFinalizer(host).finalize(
        RunFinalizationRequest(
            conversation_id="conversation-1",
            conversation=conversation,
            workspace=workspace,
            model="test-model",
            mode_config={},
            effective_mode="analysis",
            user_content="分析项目并给出结论",
            metadata=metadata,
            content_parts=[],
            reasoning_parts=[],
            tool_events=[],
            task_contract={
                "intent": "read_only_analysis",
                "requires_write": False,
                "requires_state_change": False,
                "requires_verification": False,
                "expected_min_output_chars": 100,
                "deliverables": [{"kind": "answer"}],
            },
            workspace_snapshot={},
            active_focus={},
            capability_snapshot={},
            capability_preflight={},
            context_hygiene_report={},
            run=SimpleNamespace(id="run-1", task_id=""),
            execution_plan=None,
            change_baseline=None,
            execution_state=RunExecutionState.create(20),
            requires_code_write=False,
            recon_tool_count=0,
            write_repair_mode=False,
            context_tokens=4,
        )
    )

    assert outcome.assistant_content == "模型未返回最终内容。"
    assert outcome.run_result["counts"]["answer_deliverable_successes"] == 0
    assert host.synthesis_kwargs == {}
    assert metadata["final_answer_error"] == "model did not return a final answer"
    assert "synthesized_final_answer" not in metadata
    assert host.events[1]["event"] == "result"



@pytest.mark.asyncio
async def test_finalizer_preserves_valid_model_answer_when_result_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finalizer_module, "count_messages_tokens", lambda messages: 9)
    conversation = _Conversation()
    host = _FinalizationHost(conversation)
    metadata: dict[str, Any] = {
        "completion_decisions": [{
            "self_assessment": {
                "schema_version": "completion_self_assessment.v1",
                "kind": "completion_self_assessment",
                "goal_closed": False,
                "remaining_work": ["visual verification"],
                "verification_limits": ["no rendered preview was observed"],
            },
        }],
    }
    workspace = SimpleNamespace(
        path="D:/workspace",
        to_public_dict=lambda: {"id": "workspace-1", "path": "D:/workspace"},
    )
    tool_events = [{
        "tool": "filesystem.write_file",
        "status": "success",
        "input": {"path": "viewer.html"},
        "output": {"path": "viewer.html"},
    }]

    outcome = await RunFinalizer(host).finalize(
        RunFinalizationRequest(
            conversation_id="conversation-1",
            conversation=conversation,
            workspace=workspace,
            model="test-model",
            mode_config={},
            effective_mode="terminal",
            user_content="创建并验证 viewer.html",
            metadata=metadata,
            content_parts=["已创建 viewer.html，但还没有完成视觉验证。"],
            reasoning_parts=[],
            tool_events=tool_events,
            task_contract={
                "goal": "创建并验证 viewer.html",
                "requires_write": True,
                "requires_state_change": True,
                "requires_verification": True,
            },
            workspace_snapshot={},
            active_focus={},
            capability_snapshot={},
            capability_preflight={},
            context_hygiene_report={},
            run=SimpleNamespace(id="run-1", task_id=""),
            execution_plan=None,
            change_baseline=None,
            execution_state=RunExecutionState.create(20),
            requires_code_write=True,
            recon_tool_count=0,
            write_repair_mode=False,
            context_tokens=4,
        )
    )

    assert outcome.run_result["status"] == "partial"
    assert outcome.assistant_content.startswith("已创建 viewer.html，但还没有完成视觉验证。")
    assert "synthesized_final_answer" not in metadata
