from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import runtime.conversation_runner as runner_module
import runtime.run_finalizer as finalizer_module
from runtime.agent_strategy import classifiers as strategy_classifiers
from runtime.agent_strategy import task_contract as task_contracts
from runtime.conversation_runner import ConversationRunExecutor
from runtime.run_result_presenter import (
    answer_only_final_answer_error,
    needs_synthesized_final_answer,
    run_status_from_result,
)
from runtime.tool_call_loop import ToolCallLoop as RealToolCallLoop


@dataclass
class ScenarioMessage:
    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = "message-1"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
        }


class ScenarioConversation:
    def __init__(self, user_content: str) -> None:
        self.id = "conversation-1"
        self.workspace_id = "workspace-1"
        self.metadata: dict[str, Any] = {}
        self.messages = [ScenarioMessage("user", user_content)]

    def to_public_dict(self, *, include_messages: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "workspace_id": self.workspace_id,
        }
        if include_messages:
            payload["messages"] = [message.to_public_dict() for message in self.messages]
        return payload


class ScenarioConversationStore:
    def __init__(self, conversation: ScenarioConversation) -> None:
        self.conversation = conversation

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any],
    ) -> ScenarioMessage:
        assert conversation_id == self.conversation.id
        message = ScenarioMessage(
            role,
            content,
            metadata,
            id=f"message-{len(self.conversation.messages) + 1}",
        )
        self.conversation.messages.append(message)
        return message

    def _save(self) -> None:
        return None


class ScenarioModelStream:
    def __init__(self, rounds: list[list[dict[str, Any]]]) -> None:
        self._rounds = [list(events) for events in rounds]
        self.calls: list[dict[str, Any]] = []

    async def stream(self, **kwargs: Any):
        self.calls.append(kwargs)
        if not self._rounds:
            raise AssertionError("scenario model stream received an unexpected extra round")
        for event in self._rounds.pop(0):
            yield event

    @property
    def remaining_rounds(self) -> int:
        return len(self._rounds)


class ScenarioEventStore:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, run_id: str, payload: dict[str, Any]) -> None:
        self.events.append({"run_id": run_id, **deepcopy(payload)})


class ScenarioSettings:
    data_dir = None

    def get_model_config(self, model: str) -> dict[str, Any]:
        return {"id": model, "context_limit": 32_000, "supports_vision": False}

    def is_memory_auto_extract_enabled(self) -> bool:
        return False


class ScenarioAttachments:
    def list_for_conversation(self, conversation_id: str) -> list[Any]:
        return []


class ScenarioRuns:
    def __init__(self, run: Any) -> None:
        self.run = run

    def get(self, run_id: str) -> Any:
        return self.run if run_id == self.run.id else None


@dataclass
class RunScenarioResult:
    conversation: ScenarioConversation
    events: list[dict[str, Any]]
    execution_model_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    synthesis_calls: list[dict[str, Any]]
    task_contract_calls: int

    @property
    def assistant(self) -> ScenarioMessage:
        return self.conversation.messages[-1]

    @property
    def run_result(self) -> dict[str, Any]:
        return dict(self.assistant.metadata.get("run_result") or {})


class RunScenario:
    """Scripted model/tool inputs around the real conversation Run pipeline."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        user_content: str,
        model_rounds: list[list[dict[str, Any]]],
        tool_results: list[dict[str, Any]],
        task_intent: str = "write_required",
        requires_write: bool = True,
        requires_verification: bool = True,
        planning_policy: str = "off",
        model_task_contract_error: str = "",
    ) -> None:
        self.workspace_path = workspace_path
        self.user_content = user_content
        self.model_stream = ScenarioModelStream(model_rounds)
        self.tool_results = [deepcopy(item) for item in tool_results]
        self.tool_calls: list[dict[str, Any]] = []
        self.synthesis_calls: list[dict[str, Any]] = []
        self.task_contract_calls = 0
        self.planning_policy = planning_policy
        self.model_task_contract_error = model_task_contract_error
        self.contract = task_contracts.default_task_contract(
            task_intent=task_intent,
            mode="terminal",
            planning_policy=planning_policy,
            confirmation_policy="aggressive",
            workspace_path=str(workspace_path),
            access_scope="workspace",
            source="scenario",
        )
        self.contract.update({
            "goal": user_content,
            "requires_write": requires_write,
            "requires_state_change": requires_write,
            "requires_verification": requires_write and requires_verification,
            "deliverables": (
                [{"kind": "code", "path_hint": "output.txt"}]
                if requires_write
                else []
            ),
            "first_action": "write" if requires_write else "answer",
        })
        self.contract["success_conditions"] = task_contracts.success_conditions_for_contract(
            self.contract
        )

    async def run(self, monkeypatch: Any) -> RunScenarioResult:
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        conversation = ScenarioConversation(self.user_content)
        run = SimpleNamespace(
            id="run-1",
            task_id="",
            status="running",
            source_run_id="",
            resume_from_checkpoint_id="",
        )
        event_store = ScenarioEventStore()
        runtime = SimpleNamespace(
            settings=ScenarioSettings(),
            conversations=ScenarioConversationStore(conversation),
            attachments=ScenarioAttachments(),
            runs=ScenarioRuns(run),
            run_events=event_store,
        )
        helper = ScenarioRunHost(runtime, self)

        async def identity_compression(
            messages: list[dict[str, Any]],
            *_args: Any,
            **_kwargs: Any,
        ) -> tuple[list[dict[str, Any]], None]:
            return messages, None

        def loop_factory(**kwargs: Any) -> RealToolCallLoop:
            return RealToolCallLoop(
                **kwargs,
                stream_factory=self.model_stream.stream,
            )

        monkeypatch.setattr(runner_module, "compress_context", identity_compression)
        monkeypatch.setattr(runner_module, "count_messages_tokens", lambda _messages: 12)
        monkeypatch.setattr(finalizer_module, "count_messages_tokens", lambda _messages: 18)
        monkeypatch.setattr(
            runner_module,
            "get_terminal_config",
            lambda _lang="": {"max_rounds": 8},
        )
        monkeypatch.setattr(runner_module, "ToolCallLoop", loop_factory)

        workspace = SimpleNamespace(
            id="workspace-1",
            path=str(self.workspace_path),
            to_public_dict=lambda: {
                "id": "workspace-1",
                "path": str(self.workspace_path),
            },
        )
        executor = ConversationRunExecutor(
            helper,
            run_id=run.id,
            conversation_id=conversation.id,
        )
        await executor.execute(
            conversation_id=conversation.id,
            conversation=conversation,
            workspace=workspace,
            payload={
                "planning_policy": self.planning_policy,
                "confirmation_policy": "aggressive",
                "enable_thinking": False,
            },
            content=self.user_content,
            image_data="",
            attachments=[],
            model="scenario-model",
            requested_mode=None,
            effective_mode="terminal",
            run=run,
        )
        if self.model_stream.remaining_rounds:
            raise AssertionError(
                f"scenario completed with {self.model_stream.remaining_rounds} unused model rounds"
            )
        if self.tool_results:
            raise AssertionError(
                f"scenario completed with {len(self.tool_results)} unused tool results"
            )
        return RunScenarioResult(
            conversation=conversation,
            events=event_store.events,
            execution_model_calls=self.model_stream.calls,
            tool_calls=self.tool_calls,
            synthesis_calls=self.synthesis_calls,
            task_contract_calls=self.task_contract_calls,
        )


class ScenarioRunHost:
    def __init__(self, runtime: Any, scenario: RunScenario) -> None:
        self.runtime = runtime
        self.scenario = scenario

    def _build_model_messages(self, conversation: Any, workspace: dict[str, Any], **_kwargs: Any):
        self._last_context_hygiene_report = {"changed": False}
        self._last_memory_context = {}
        return [
            {"role": "system", "content": f"Workspace: {workspace['path']}"},
            {"role": "user", "content": conversation.messages[-1].content},
        ]

    def _normalize_planning_policy(self, payload: dict[str, Any]) -> str:
        return self._helper.scenario.planning_policy

    def _normalize_confirmation_policy(self, payload: dict[str, Any]) -> str:
        return "aggressive"

    async def _capture_git_status(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def _build_task_contract(self, **_kwargs: Any) -> dict[str, Any]:
        return deepcopy(self._helper.scenario.contract)

    def _task_lineage_candidates(self, *_args: Any) -> list[dict[str, Any]]:
        return []

    def _task_lineage_availability(self, _candidates: list[dict[str, Any]]) -> dict[str, Any]:
        return {"available": False, "candidate_count": 0}

    def _referenced_task_candidate_contract(self, *_args: Any) -> None:
        return None

    def _should_use_model_task_contract(self, *_args: Any) -> bool:
        return bool(self._helper.scenario.model_task_contract_error)

    async def _decide_task_contract(
        self,
        *,
        fallback_contract: dict[str, Any],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        scenario = self._helper.scenario
        scenario.task_contract_calls += 1
        contract = deepcopy(fallback_contract)
        contract["source"] = "policy_fallback"
        contract["model_contract_error"] = scenario.model_task_contract_error
        return contract

    def _build_capability_snapshot(self, *_args: Any) -> dict[str, Any]:
        return {
            "schema_version": "capability_snapshot.v1",
            "capabilities": [],
            "capability_issues": [],
        }

    def _preflight_task_capabilities(self, *_args: Any) -> dict[str, Any]:
        return {"advisories": [], "target_capability_ids": []}

    async def _auto_start_mcp_services_for_preflight(self, *_args: Any) -> list[dict[str, Any]]:
        return []

    def _build_model_tools(self, *_args: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
        tool_ids = ["filesystem.write_file", "code.apply_patch", "shell.run_command"]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool_id.replace(".", "__"),
                    "description": tool_id,
                    "parameters": {"type": "object"},
                },
            }
            for tool_id in tool_ids
        ]
        name_map = {tool_id: tool_id for tool_id in tool_ids}
        name_map.update({tool_id.replace(".", "__"): tool_id for tool_id in tool_ids})
        return tools, name_map

    def _task_contract_prompt(self, _contract: dict[str, Any]) -> str:
        return "Follow the current task contract and use runtime evidence."

    def _capability_boundary_prompt(self, _preflight: dict[str, Any]) -> str:
        return ""

    def _pop_user_guidance(self, _conversation_id: str) -> tuple[str, str]:
        return "", ""

    def _messages_for_model_round(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return strategy_classifiers.messages_for_model_round(messages, tools)

    def _complete_tool_calls(
        self,
        calls: list[dict[str, Any]],
        round_index: int,
    ) -> list[dict[str, Any]]:
        return strategy_classifiers.complete_tool_calls(calls, round_index)

    def _extract_native_tool_calls(self, text: str, round_index: int) -> list[dict[str, Any]]:
        return strategy_classifiers.extract_native_tool_calls(text, round_index)

    def _has_unresolved_tool_call_markup(self, content: str) -> bool:
        return strategy_classifiers.has_unresolved_tool_call_markup(content)

    def _discard_parts(self, target: list[str], parts: list[str]) -> None:
        if parts:
            del target[-len(parts):]

    def _tool_call_details(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        function = tool_call["function"]
        model_name = str(function.get("name") or "")
        tool_id = tool_name_map.get(model_name, model_name.replace("__", "."))
        raw_arguments = function.get("arguments") or "{}"
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        return tool_id, dict(arguments)

    def _skipped_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_id: str,
        arguments: dict[str, Any],
        *,
        reason: str,
        message: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        event = {
            "tool": tool_id,
            "status": "failure",
            "input": arguments,
            "error": message,
            "output": {"reason": reason},
        }
        return self._scenario_tool_message(tool_call, event), event

    def _is_recoverable_write_failure(self, _tool_id: str, _event: dict[str, Any]) -> bool:
        return False

    def _write_repair_prompt(self, *_args: Any) -> str:
        return "Choose a materially different write route using the observed failure."

    def _mark_next_plan_step_running(self, *_args: Any) -> None:
        return None

    def _finish_plan_step(self, *_args: Any) -> None:
        return None

    def _is_recon_tool(self, tool_id: str) -> bool:
        return tool_id == "filesystem.read_file"

    def _tool_signature(self, tool_id: str, arguments: dict[str, Any]) -> str:
        return f"{tool_id}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
        _workspace_path: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        tool_id, arguments = self._tool_call_details(tool_call, tool_name_map)
        scenario = self._helper.scenario
        if not scenario.tool_results:
            raise AssertionError(f"unexpected tool call: {tool_id}")
        scripted = scenario.tool_results.pop(0)
        expected_tool = str(scripted.get("tool") or tool_id)
        assert tool_id == expected_tool
        event = deepcopy(scripted)
        event.setdefault("tool", tool_id)
        event.setdefault("input", arguments)
        event.setdefault("output", {})
        event.setdefault("error", "")
        scenario.tool_calls.append({"tool": tool_id, "arguments": arguments})
        return self._scenario_tool_message(tool_call, event), event

    def _scenario_tool_message(
        self,
        tool_call: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": tool_call["function"]["name"],
            "content": json.dumps(event, ensure_ascii=False),
        }

    def _is_write_tool(self, tool_id: str) -> bool:
        return tool_id in {"filesystem.write_file", "code.apply_patch"}

    def _read_file_range_record(self, *_args: Any) -> dict[str, Any]:
        return {}

    def _has_successful_target_deliverable(
        self,
        _task_contract: dict[str, Any],
        tool_events: list[dict[str, Any]],
        *_args: Any,
    ) -> bool:
        return any(
            self._is_write_tool(str(event.get("tool") or ""))
            and event.get("status") == "success"
            for event in tool_events
        )

    def _completion_review_prompt(self, *_args: Any, **_kwargs: Any) -> str:
        return "Review fresh runtime evidence and declare completion_self_assessment.v1."

    def _execution_convergence_prompt(self, *_args: Any) -> str:
        return "The same route has repeated without progress; choose the next strategy."

    def _malformed_tool_call_prompt(self, *_args: Any) -> str:
        return "Resend a complete structured tool call."

    def _read_range_summary_prompt(self, *_args: Any) -> str:
        return "Use the observed read ranges."

    def _task_contract_failures(self, *_args: Any, **_kwargs: Any) -> list[str]:
        return []

    def _max_rounds_after_write_message(self, *_args: Any) -> str:
        return "Round budget ended after a write."

    def _max_rounds_message(self, *_args: Any) -> str:
        return "Round budget ended."

    async def _build_change_summary(
        self,
        _workspace_path: str,
        _mode_config: dict[str, Any],
        _baseline: Any,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        paths = []
        for event in tool_events:
            if event.get("status") != "success" or not self._is_write_tool(str(event.get("tool") or "")):
                continue
            output = event.get("output") if isinstance(event.get("output"), dict) else {}
            input_data = event.get("input") if isinstance(event.get("input"), dict) else {}
            path = str(output.get("path") or input_data.get("path") or "")
            if path and path not in paths:
                paths.append(path)
        if not paths:
            return None
        return {
            "source": "scenario",
            "files": [{"status": "touched", "path": path} for path in paths],
            "file_count": len(paths),
        }

    def _answer_only_final_answer_error(
        self,
        content: str,
        tool_events: list[dict[str, Any]],
        task_contract: dict[str, Any] | None = None,
    ) -> str:
        return answer_only_final_answer_error(content, tool_events, task_contract)

    def _needs_synthesized_final_answer(
        self,
        content: str,
        tool_events: list[dict[str, Any]],
        *,
        task_contract: dict[str, Any] | None = None,
    ) -> bool:
        return needs_synthesized_final_answer(content, tool_events, task_contract)

    async def _generate_result_synthesis_answer(self, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        self._helper.scenario.synthesis_calls.append(kwargs)
        return "unexpected synthesized answer", {"model": "scenario-model"}

    def _synthesize_failure_answer(self, *_args: Any) -> str:
        return "runtime failure fallback"

    def _synthesize_partial_answer(self, *_args: Any) -> str:
        return "runtime partial fallback"

    def _synthesize_final_answer(self, *_args: Any) -> str:
        return "runtime protocol fallback"

    def _build_execution_notice(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def _run_status_from_result(self, run_result: dict[str, Any]) -> str:
        return run_status_from_result(run_result)
