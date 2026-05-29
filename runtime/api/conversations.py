from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import tornado.web
import tornado.iostream

from .base import ApiHandler
from runtime import i18n
from runtime.model_providers import generate_chat_completion
from runtime.model_providers.client import stream_chat_completion
from runtime.assistant_modes import get_mode_config, normalize_mode
from runtime.context_manager import (
    compress_context,
    count_messages_tokens,
    get_context_limit,
    get_usable_limit,
)
from runtime.conversation_runner import ConversationRunExecutor
from runtime.conversation_interactions import (
    confirm_responses as _confirm_responses,
    pending_confirms as _pending_confirms,
    runtime_guidance as _runtime_guidance,
)
from runtime.prompt_context import build_system_prompt
from runtime.task_runner import ToolContext


class ConversationsHandler(ApiHandler):
    def get(self) -> None:
        workspace_id = self.get_argument("workspace_id", None)
        conversations = self.runtime.conversations.list(workspace_id)
        self.finish_json({
            "success": True,
            "data": [item.to_public_dict() for item in conversations],
        })

    def post(self) -> None:
        payload = self.parse_json_body()
        workspace_id = payload.get("workspace_id")
        if not workspace_id:
            raise tornado.web.HTTPError(400, reason="workspace_id is required")
        if not self.runtime.workspaces.get(workspace_id):
            raise tornado.web.HTTPError(404, reason="workspace not found")
        mode = normalize_mode(payload.get("mode") or self.runtime.settings.get_assistant_mode())
        conversation = self.runtime.conversations.create(
            workspace_id, payload.get("title"), mode=mode,
        )
        self.finish_json({
            "success": True,
            "data": conversation.to_public_dict(include_messages=True),
        })


class ConversationDetailHandler(ApiHandler):
    def get(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        data = conversation.to_public_dict(include_messages=True)

        # Calculate current context token usage so the frontend can display it
        model = self.runtime.settings.get_default_model()
        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if workspace:
            mode_config = get_mode_config(getattr(conversation, "mode", None), self.get_lang())
            system_prompt = build_system_prompt(
                settings=self.runtime.settings,
                mode_config=mode_config,
                workspace_path=workspace.path,
            )
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt}
            ]
            for item in conversation.messages:
                metadata = getattr(item, "metadata", {}) or {}
                if metadata.get("guidance") and metadata.get("during_run"):
                    continue
                role = "assistant" if item.role == "assistant" else "user"
                messages.append({"role": role, "content": item.content})
            data["context_tokens"] = count_messages_tokens(messages)
            data["context_limit"] = get_context_limit(model, self.runtime.settings)
        else:
            data["context_tokens"] = 0
            data["context_limit"] = get_context_limit(model, self.runtime.settings)

        self.finish_json({"success": True, "data": data})

    def patch(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        mode = normalize_mode(payload.get("mode"))

        conversation = self.runtime.conversations.update_mode(conversation_id, mode)
        self.runtime.settings.update({"assistant_mode": mode})
        self.finish_json({
            "success": True,
            "data": conversation.to_public_dict(include_messages=True),
        })

    def delete(self, conversation_id: str) -> None:
        deleted = self.runtime.conversations.delete(conversation_id)
        if not deleted:
            raise tornado.web.HTTPError(404, reason="conversation not found")
        self.finish_json({"success": True})


class ConversationGuidanceHandler(ApiHandler):
    def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        content = str(payload.get("content") or "").strip()
        if not content:
            raise tornado.web.HTTPError(400, reason="content is required")

        items = _runtime_guidance.setdefault(conversation_id, [])
        items.append(content)
        if len(items) > 10:
            del items[:-10]
        message = self.runtime.conversations.add_message(
            conversation_id,
            "user",
            content,
            {"guidance": True, "during_run": True},
        )
        self.finish_json({
            "success": True,
            "data": {
                "count": len(items),
                "message": message.to_public_dict(),
            },
        })


class ConversationMessagesHandler(ApiHandler):
    def _payload_mode(self, payload: dict[str, Any]) -> str | None:
        mode = str(payload.get("mode") or "").strip()
        return normalize_mode(mode) if mode else None

    async def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        content = (payload.get("content") or "").strip()
        if not content:
            raise tornado.web.HTTPError(400, reason="content is required")

        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")

        payload_mode = self._payload_mode(payload)
        if payload_mode:
            self.runtime.settings.update({"assistant_mode": payload_mode})
            if payload_mode != conversation.mode:
                conversation = self.runtime.conversations.update_mode(conversation_id, payload_mode)

        user_message = self.runtime.conversations.add_message(conversation_id, "user", content)
        assistant_content, metadata = await self._build_reply(conversation, workspace.to_public_dict(), content, payload)
        assistant_message = self.runtime.conversations.add_message(
            conversation_id,
            "assistant",
            assistant_content,
            metadata,
        )

        self.finish_json({
            "success": True,
            "data": {
                "conversation": conversation.to_public_dict(include_messages=True),
                "messages": [
                    user_message.to_public_dict(),
                    assistant_message.to_public_dict(),
                ],
            },
        })

    async def _build_reply(
        self,
        conversation: Any,
        workspace: dict[str, Any],
        content: str,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        model = payload.get("model") or self.runtime.settings.get_default_model()
        messages = self._build_model_messages(conversation, workspace)
        try:
            return await generate_chat_completion(
                settings=self.runtime.settings,
                model=model,
                messages=messages,
                enable_thinking=bool(payload.get("enable_thinking", True)),
                reasoning_effort=str(payload.get("reasoning_effort") or "medium"),
            )
        except tornado.web.HTTPError as exc:
            if exc.status_code != 400:
                raise
            text = i18n.t("conv.workspace_hint", self.get_lang(), path=workspace["path"], reason=str(exc.reason))
            return text, {"mode": "local-placeholder", "reason": exc.reason}

    def _build_model_messages(
        self,
        conversation: Any,
        workspace: dict[str, Any],
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        mode_config = get_mode_config(mode if mode is not None else getattr(conversation, "mode", None), self.get_lang())
        # Extract the latest user message for memory relevance scoring
        latest_user_message = ""
        for msg in reversed(getattr(conversation, "messages", [])):
            if getattr(msg, "role", "") == "user":
                latest_user_message = msg.content or ""
                break
        system_prompt = build_system_prompt(
            settings=self.runtime.settings,
            mode_config=mode_config,
            workspace_path=workspace["path"],
            user_message=latest_user_message,
        )
        messages = [{"role": "system", "content": system_prompt}]
        for item in conversation.messages:
            metadata = getattr(item, "metadata", {}) or {}
            if metadata.get("guidance") and metadata.get("during_run"):
                continue
            role = "assistant" if item.role == "assistant" else "user"
            messages.append({"role": role, "content": item.content})
        return messages

class ConversationMessagesStreamHandler(ConversationMessagesHandler):
    def flush(self, include_footers: bool = False) -> asyncio.Task[None]:
        return asyncio.create_task(self._safe_flush(include_footers=include_footers))

    async def _safe_flush(self, include_footers: bool = False) -> None:
        if getattr(self, "_client_stream_closed", False):
            return
        try:
            await super().flush(include_footers=include_footers)
        except tornado.iostream.StreamClosedError:
            self._client_stream_closed = True

    async def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        payload = self.parse_json_body()
        content = (payload.get("content") or "").strip()
        image_data = payload.get("image_data") or ""
        if not content and not image_data:
            raise tornado.web.HTTPError(400, reason="content is required")

        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")

        payload_mode = self._payload_mode(payload)
        if payload_mode:
            self.runtime.settings.update({"assistant_mode": payload_mode})
            if payload_mode != conversation.mode:
                conversation = self.runtime.conversations.update_mode(conversation_id, payload_mode)

        self.set_header("Content-Type", "application/x-ndjson; charset=utf-8")
        msg_metadata: dict[str, Any] = {}
        if image_data:
            msg_metadata["has_image"] = True
        user_message = self.runtime.conversations.add_message(
            conversation_id, "user", content or self.t("conv.image_placeholder"), msg_metadata,
        )
        self.write_event({"event": "user", "message": user_message.to_public_dict()})
        await self.flush()

        model = payload.get("model") or self.runtime.settings.get_default_model()
        requested_mode = getattr(conversation, "mode", None)
        effective_mode = self._effective_mode(requested_mode, content, conversation)
        run = self.runtime.runs.create(
            conversation_id=conversation_id,
            workspace_id=conversation.workspace_id,
            mode=effective_mode,
            user_content=content or "[image]",
        )
        self._active_run_id = run.id
        self._active_conversation_id = conversation_id
        self.write_event({"event": "run", "run": run.to_public_dict(include_events=True)})
        await self.flush()
        executor = ConversationRunExecutor(
            self,
            run_id=run.id,
            conversation_id=conversation_id,
        )
        event_queue = self.runtime.run_events.subscribe(run.id)

        async def execute_run() -> None:
            try:
                await executor.execute(
                    conversation_id=conversation_id,
                    conversation=conversation,
                    workspace=workspace,
                    payload=payload,
                    content=content,
                    image_data=image_data,
                    model=model,
                    requested_mode=requested_mode,
                    effective_mode=effective_mode,
                    run=run,
                )
            except Exception as exc:
                self.runtime.run_events.emit(run.id, {
                    "event": "error",
                    "error": str(exc) or exc.__class__.__name__,
                })

        task = asyncio.create_task(execute_run())
        try:
            while True:
                if getattr(self, "_client_stream_closed", False):
                    return
                if task.done() and event_queue.empty():
                    break
                try:
                    event_data = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    self.write_json_line({
                        "event": "heartbeat",
                        "run_id": run.id,
                        "message": self.t("conv.model_processing"),
                    })
                    await self.flush()
                    continue
                payload_for_client = dict(event_data)
                payload_for_client.pop("time", None)
                self.write_json_line(payload_for_client)
                await self.flush()
                if payload_for_client.get("event") in {"done", "error"}:
                    break
        finally:
            self.runtime.run_events.unsubscribe(run.id, event_queue)

    def _normalize_execution_mode(self, payload: dict[str, Any]) -> str:
        mode = str(payload.get("execution_mode") or "").strip().lower()
        if mode in {"conservative", "auto", "aggressive"}:
            return mode
        if not any(key in payload for key in ("plan_mode", "plan_execution")):
            return self.runtime.settings.get_execution_mode()
        legacy = self._normalize_plan_mode(payload)
        return {
            "off": "conservative",
            "auto": "auto",
            "always": "aggressive",
        }.get(legacy, self.runtime.settings.get_execution_mode())

    def _plan_mode_for_execution_mode(self, execution_mode: str, payload: dict[str, Any]) -> str:
        if execution_mode == "conservative":
            return "off"
        if execution_mode == "aggressive":
            return "always"
        return self._normalize_plan_mode(payload)

    def _normalize_plan_mode(self, payload: dict[str, Any]) -> str:
        mode = str(payload.get("plan_mode") or "").strip().lower()
        if mode in {"auto", "always", "off"}:
            return mode
        if payload.get("plan_execution") is True:
            return "always"
        if payload.get("plan_execution") is False and "plan_execution" in payload:
            return "off"
        return "auto"

    def _build_task_contract(
        self,
        *,
        task_intent: str,
        mode: str | None,
        execution_mode: str,
        plan_mode: str,
        workspace_path: str,
    ) -> dict[str, Any]:
        requires_write = task_intent in {"write_required", "document_export"}
        requires_verification = requires_write
        requires_plan = plan_mode == "always"
        if execution_mode == "conservative":
            requires_plan = False
        return {
            "intent": task_intent,
            "assistant_mode": mode or "terminal",
            "execution_mode": execution_mode,
            "plan_mode": plan_mode,
            "access_scope": self.runtime.settings.get_access_scope(),
            "workspace_path": workspace_path,
            "requires_write": requires_write,
            "requires_verification": requires_verification,
            "requires_plan": requires_plan,
            "success_conditions": [
                condition for condition in [
                    "write_tool_success" if requires_write else "",
                    "verification_tool_success" if requires_verification else "",
                    "final_answer_with_evidence",
                ] if condition
            ],
        }

    def _task_contract_prompt(self, contract: dict[str, Any]) -> str:
        conditions = ", ".join(contract.get("success_conditions") or [])
        lang = self.get_lang()
        return (
            i18n.t("contract.title", lang)
            + i18n.t("contract.workspace", lang, workspace_path=str(contract.get("workspace_path")))
            + i18n.t("contract.access", lang, access_scope=str(contract.get("access_scope")))
            + i18n.t("contract.exec_mode", lang, execution_mode=str(contract.get("execution_mode")))
            + i18n.t("contract.intent", lang, intent=str(contract.get("intent")))
            + i18n.t("contract.must_write", lang, requires_write=str(bool(contract.get("requires_write"))))
            + i18n.t("contract.must_verify", lang, requires_verification=str(bool(contract.get("requires_verification"))))
            + i18n.t("contract.success", lang, conditions=conditions)
            + i18n.t("contract.write_rule", lang)
            + i18n.t("contract.verify_rule", lang)
            + i18n.t("contract.summary_rule", lang)
        )

    def _task_contract_failures(
        self,
        contract: dict[str, Any],
        tool_events: list[dict[str, Any]],
        mode: str | None,
    ) -> list[str]:
        failures: list[str] = []
        if contract.get("requires_write") and not self._has_successful_write(tool_events):
            failures.append("missing_write_tool_success")
        if (
            contract.get("requires_verification")
            and self._has_successful_write(tool_events)
            and not self._has_successful_verification(tool_events, mode)
        ):
            failures.append("missing_verification_tool_success")
        return failures

    async def _decide_plan_execution(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        workspace_path: str,
        mode: str | None,
        user_content: str,
    ) -> dict[str, Any]:
        lang = self.get_lang()
        prompt = i18n.t("plan_judge.prompt", lang, mode=mode or "document", workspace_path=workspace_path)
        try:
            decision_messages: list[dict[str, Any]] = []
            if messages and messages[0].get("role") == "system":
                decision_messages.append(messages[0])
            decision_messages.append({"role": "user", "content": user_content})
            decision_messages.append({"role": "system", "content": prompt})
            answer, _metadata = await generate_chat_completion(
                settings=self.runtime.settings,
                model=model,
                messages=decision_messages,
                enable_thinking=False,
                reasoning_effort="low",
                tools=None,
            )
            parsed = self._extract_plan_json(answer)
            if parsed and "use_plan" in parsed:
                return {
                    "mode": "auto",
                    "enabled": bool(parsed.get("use_plan")),
                    "reason": str(parsed.get("reason") or "")[:160],
                    "confidence": parsed.get("confidence"),
                    "source": "model",
                }
        except Exception:
            pass

        enabled = self._heuristic_plan_execution(user_content, mode)
        return {
            "mode": "auto",
            "enabled": enabled,
            "reason": self.t("plan_judge.reason_auto") if enabled else self.t("plan_judge.reason_direct"),
            "source": "heuristic",
        }

    def _heuristic_plan_execution(self, content: str, mode: str | None) -> bool:
        text = content.lower()
        simple_terms = ("你好", "介绍下你自己", "你是谁", "是什么", "为什么", "解释一下")
        if len(text) < 24 and any(term in text for term in simple_terms):
            return False
        if mode == "paper":
            paper_plan_terms = (
                "文献综述",
                "系统综述",
                "研究设计",
                "研究问题",
                "论文大纲",
                "论文初稿",
                "审稿意见",
                "审稿回复",
                "投稿",
                "摘要",
                "引言",
                "相关工作",
                "方法论",
                "质量检查",
                "引用",
                "参考文献",
            )
            return len(text) > 80 or any(term in text for term in paper_plan_terms)
        if self._looks_like_simple_code_change(content):
            return False
        if mode == "coding" and self._user_requests_code_change(content, mode):
            return not self._looks_like_simple_code_change(content)
        complex_terms = (
            "分析当前项目",
            "审查",
            "审核",
            "汇总",
            "对比",
            "整理",
            "生成报告",
            "风险清单",
            "整改清单",
            "多份",
            "全部",
            "完整",
            "实现",
            "重构",
            "修复",
            "测试",
            "验证",
            "方案",
            "计划",
        )
        if any(term in text for term in complex_terms):
            return True
        return len(text) > 120

    async def _generate_execution_plan(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        workspace_path: str,
        mode: str | None,
        enable_thinking: bool,
        reasoning_effort: str,
    ) -> dict[str, Any]:
        plan_messages = [*messages, {
            "role": "system",
            "content": self._planning_prompt(workspace_path, mode),
        }]
        plan_parts: list[str] = []
        async for event in stream_chat_completion(
            settings=self.runtime.settings,
            model=model,
            messages=plan_messages,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
            tools=None,
        ):
            if event.get("error"):
                raise tornado.web.HTTPError(502, reason=event["error"])
            if event.get("message"):
                plan_parts.append(event["message"])
            if event.get("reasoning"):
                self.write_event({"event": "reasoning", "reasoning": event["reasoning"]})
                await self.flush()
            if event.get("heartbeat"):
                self.write_event({
                    "event": "heartbeat",
                    "message": event.get("message") or "模型仍在处理，请稍候",
                    "idle_seconds": event.get("idle_seconds"),
                })
                await self.flush()
        raw_plan = "".join(plan_parts).strip()
        return self._normalize_execution_plan(raw_plan, mode)

    def _planning_prompt(self, workspace_path: str, mode: str | None) -> str:
        lang = self.get_lang()
        if mode == "coding":
            focus = i18n.t("planner.focus_coding", lang)
        elif mode == "paper":
            focus = i18n.t("planner.focus_paper", lang)
        else:
            focus = i18n.t("planner.focus_general", lang)
        return (
            i18n.t("planner.intro", lang, workspace_path=workspace_path)
            + focus + "\n"
            + i18n.t("planner.json_format", lang)
        )

    def _normalize_execution_plan(self, raw_plan: str, mode: str | None) -> dict[str, Any]:
        parsed = self._extract_plan_json(raw_plan)
        if not parsed:
            parsed = self._fallback_execution_plan(mode)

        raw_steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
        steps: list[dict[str, Any]] = []
        for index, item in enumerate(raw_steps[:8], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or f"步骤 {index}").strip()
            description = str(item.get("description") or item.get("detail") or "").strip()
            tool_hint = str(item.get("tool_hint") or item.get("tool") or "").strip()
            steps.append({
                "title": title[:80],
                "description": description[:260],
                "tool_hint": tool_hint[:120],
                "status": "pending",
            })

        if not steps:
            return self._fallback_execution_plan(mode)

        return {
            "title": str(parsed.get("title") or "计划执行").strip()[:80],
            "steps": steps,
            "raw": raw_plan[:4000],
        }

    def _extract_plan_json(self, raw_plan: str) -> dict[str, Any] | None:
        text = raw_plan.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def _fallback_execution_plan(self, mode: str | None) -> dict[str, Any]:
        if mode == "coding":
            steps = [
                ("定位相关代码", "扫描目录并读取与需求相关的文件。", "code.list_project_files / filesystem.read_file"),
                ("分析修改点", "确认需要修改的函数、配置或页面，并控制影响范围。", "code.search_text"),
                ("执行代码变更", "使用批量替换、精确编辑或写入工具完成修改。", "code.replace_text / code.edit_file / filesystem.write_file"),
                ("验证结果", "运行可行的语法检查、测试或搜索验证。", "shell.run_command / git.status"),
                ("汇总变更", "列出修改文件、验证结果和剩余风险。", "git.diff / git.status"),
            ]
        elif mode == "paper":
            steps = [
                ("建立材料护照", "扫描论文项目目录，识别草稿、文献、笔记、数据说明和参考资料。", "filesystem.scan_folder / code.list_project_files"),
                ("提取已确认事实", "读取核心文档，区分 raw、redacted、verified 信息，并列出未覆盖材料。", "filesystem.read_file / document.extract_docx_outline / document.extract_pdf_text_preview"),
                ("形成论文产出", "根据用户目标生成大纲、综述、摘要、段落草稿、审稿回复或修改建议。", "本地模型 / filesystem.write_file"),
                ("学术质量门", "检查幻觉引用、方法论捏造、实验结果捏造、过早锁定框架和贡献夸大风险。", "本地模型"),
                ("汇总结论", "列出依据、可用文本、待确认项和建议的下一步用户决策。", "本地模型"),
            ]
        else:
            steps = [
                ("识别资料范围", "扫描当前项目目录，确定需要读取的文档和附件。", "filesystem.scan_folder"),
                ("读取核心内容", "提取 Word、PDF 或文本中的标题、大纲和关键段落。", "document.extract_docx_outline / document.extract_pdf_text_preview"),
                ("分析和归纳", "按用户目标整理事实、问题、风险或结论。", "filesystem.read_file"),
                ("形成产出", "生成摘要、审查意见、清单或汇报内容。", "本地模型"),
                ("说明依据", "列出已读取资料、跳过项和不确定项。", "本地模型"),
            ]
        return {
            "title": "计划执行",
            "steps": [
                {"title": title, "description": desc, "tool_hint": tool, "status": "pending"}
                for title, desc, tool in steps
            ],
            "raw": "",
        }

    def _format_execution_plan_for_context(self, plan: dict[str, Any]) -> str:
        lines = [f"计划执行：{plan.get('title') or '计划执行'}"]
        for index, step in enumerate(plan.get("steps") or [], start=1):
            lines.append(
                f"{index}. {step.get('title')}: {step.get('description')}"
                + (f"（工具建议：{step.get('tool_hint')}）" if step.get("tool_hint") else "")
            )
        return "\n".join(lines)

    def _execute_plan_prompt(self, plan: dict[str, Any], mode: str | None) -> str:
        code_rule = ""
        if mode == "coding":
            code_rule = (
                "如果任务涉及代码变更，必须成功调用 code.edit_file、code.replace_text 或 filesystem.write_file 后，"
                "才能声称已经修改完成。"
            )
        return (
            "计划执行模式已开启。上面的计划是参考路线，不是固定轨道；"
            "如工具结果、插话或文件结构显示原计划不合适，可以跳过、合并、拆分或追加步骤。"
            "需要读取本地资料或代码时必须调用本地工具；每次工具返回后继续推进下一步。"
            f"{code_rule}"
            "最终回答要说明：完成了哪些步骤、使用了哪些文件或工具、结果和未完成/不确定项。"
        )

    def _execution_stage_sequence(
        self,
        mode: str | None,
        code_change_intent: bool,
        task_intent: str = "",
    ) -> list[str]:
        if mode in {"coding", "terminal"} and code_change_intent:
            return ["explorer", "editor", "verifier", "reviewer"]
        if mode == "paper":
            if task_intent == "read_only_analysis":
                return ["explorer", "reviewer"]
            return ["explorer", "writer", "integrity_gate", "reviewer"]
        if mode == "document":
            if task_intent == "document_export":
                return ["explorer", "creator", "verifier", "reviewer"]
            return ["explorer", "reviewer"]
        return ["explorer", "reviewer"]

    def _stage_round_limit(self, stage: str, mode: str | None, code_change_intent: bool) -> int:
        if stage == "explorer":
            if mode in {"coding", "terminal"} and code_change_intent:
                return 5
            if mode == "paper":
                return 5
            if mode == "document":
                return 4
            return 5
        if stage == "editor":
            return 5
        if stage == "creator":
            return 5
        if stage == "writer":
            return 3
        if stage == "integrity_gate":
            return 1
        if stage == "verifier":
            return 2
        return 1

    def _stage_tools(
        self,
        stage: str,
        tools: list[dict[str, Any]],
        tool_name_map: dict[str, str],
        mode: str | None,
        code_change_intent: bool,
    ) -> list[dict[str, Any]] | None:
        # 阶段不再收窄工具集。Planner / Explorer / Editor / Verifier
        # 只是角色提示和 UI 状态，真实安全边界由执行层决定。
        return tools

    def _explorer_tool_ids(self, mode: str | None) -> set[str]:
        base = {
            "filesystem.scan_folder",
            "filesystem.read_file",
            "filesystem.read_text_preview",
            "document.extract_docx_outline",
            "document.extract_pdf_text_preview",
            "code.search_text",
            "code.list_project_files",
        }
        if mode in {"coding", "terminal"}:
            base |= {"git.status", "git.log"}
        return base

    def _stage_status_message(self, stage: str) -> str:
        return {
            "writer": "写作者正在形成论文产出",
            "integrity_gate": "学术质量门正在检查事实与引用风险",
            "explorer": "侦察者正在收集必要证据",
            "editor": "执行者正在基于证据执行修改",
            "verifier": "验证者正在检查变更结果",
            "creator": "创作者正在生成或导出文档",
            "reviewer": "审查者正在收束任务并形成结论",
        }.get(stage, "正在执行阶段任务")

    def _stage_prompt(
        self,
        stage: str,
        workspace_path: str,
        mode: str | None,
        code_change_intent: bool,
    ) -> str:
        if stage == "explorer":
            if mode == "paper":
                return (
                    "你现在是 Explorer（论文侦察者）。职责重点是收集论文任务所需的最小可靠证据。\n"
                    f"当前项目目录：{workspace_path}\n"
                    "阶段只是参考，不会限制工具；如发现必须写入、验证或换工具，可以基于证据调整计划。\n"
                    "优先避免：编造文献、补造实验结果、把推测说成事实、反复读取同一材料。\n"
                    "请形成 Material Passport：已读材料、材料类型、Data Access 层级（raw/redacted/verified）、已确认事实、缺失证据、需要用户确认的关键决策。\n"
                    "推进条件：已确认足够支撑本轮回答的材料后，进入写作、验证或总结。"
                )
            return (
                "你现在是 Explorer（侦察者）。职责重点是收集完成任务所需的最小证据。\n"
                f"当前项目目录：{workspace_path}\n"
                "阶段只是参考，不会限制工具；如证据已足够，应主动进入写入、验证或总结，而不是机械继续搜索。\n"
                "优先避免：运行无关命令、反复搜索同一关键词、重复读取同一范围。"
            )
        if stage == "editor":
            return (
                "你现在是 Editor（执行者）。职责：基于已收集的证据执行真实修改。\n"
                f"当前项目目录：{workspace_path}\n"
                "所有工具仍然可用；请选择完成修改所需的最合适工具。\n"
                "规则：\n"
                "1. 【强制】每次编辑文件前，必须先调用 filesystem.read_file 读取目标文件的相关片段，确认实际内容和缩进。绝对不要凭记忆构造 old_text。\n"
                "2. 构造 old_text 时，直接复制从 read_file 结果中看到的原文，不要调整空格或缩进。\n"
                "3. 如果写入失败（如 old_text not found），必须重新读取文件对应位置，基于真实内容重试，不要凭记忆猜测。\n"
                "4. 不要伪造修改结果，不要声称已完成但未实际调用写入工具。"
            )
        if stage == "writer":
            return (
                "你现在是 Writer（论文写作者）。职责：只基于 Planner 和 Explorer 已确认的材料形成论文产出。\n"
                f"当前项目目录：{workspace_path}\n"
                "默认在对话中输出，不要私自写文件。只有用户明确要求保存、生成草稿文件或导出时，才调用写入/导出工具。\n"
                "所有工具仍然可用；如发现材料不足，可以补读；如用户要求保存或导出，可以写入或导出。\n"
                "输出必须区分：事实提取、推断、建议、可直接使用的草稿文本。不要编造引用、作者、DOI、实验结果、统计显著性或方法细节。\n"
                "遇到选题方向、研究假设、章节大纲、投稿目标、审稿回复策略等关键决策时，给出可选方案并标注需要用户确认。"
            )
        if stage == "integrity_gate":
            return (
                "你现在是 Integrity Gate（学术质量门）。职责重点是检查本轮论文输出是否存在学术可靠性风险。\n"
                f"当前项目目录：{workspace_path}\n"
                "阶段只是参考，不会限制工具；如证据不足，可以补充读取必要材料。\n"
                "请按以下失败模式逐项判断 CLEAR / SUSPECTED / INSUFFICIENT EVIDENCE：\n"
                "1. 实现或事实错误被 AI 自审放过；2. 幻觉引用；3. 幻觉实验结果；4. 依赖捷径或证据不足；"
                "5. 把缺陷包装成创新；6. 方法论捏造；7. 早期框架过度锁定。\n"
                "如果出现 SUSPECTED，必须明确风险和需要补充的证据；如果证据不足，不要强行通过。"
            )
        if stage == "creator":
            return (
                "你现在是 Creator（文档创作者）。职责：基于 Explorer 阶段收集的材料，调用文档生成/导出工具完成产出。\n"
                f"当前项目目录：{workspace_path}\n"
                "所有工具仍然可用；优先使用最贴近目标的文档生成、导出或写入工具。\n"
                "规则：\n"
                "1. 如果材料足够，直接调用导出工具；如果材料不足，只补充读取最小必要内容。\n"
                "2. generate_ppt 需要 slides 数组（每项含 title 和 content），path 可省略（会自动生成）。\n"
                "3. export_docx / export_markdown 需要 content（Markdown 格式文本）。\n"
                "4. 如果工具调用成功，简短确认产出路径和文件大小即可。\n"
                "5. 如果工具调用失败，说明失败原因，不要伪造成功结果。"
            )
        if stage == "verifier":
            return (
                "你现在是 Verifier（验证者）。职责：写入成功后只做一次必要验证。\n"
                f"当前项目目录：{workspace_path}\n"
                "所有工具仍然可用；优先运行测试/语法检查、查看 git.status 或 git.diff。"
                "如果验证失败，可以读取必要上下文并继续修复；如果验证通过，进入总结。"
            )
        if stage == "reviewer":
            if mode == "paper":
                return (
                    "你现在是 Reviewer（论文审查者）。职责重点是检查是否满足用户目标并形成最终答复。\n"
                    f"当前项目目录：{workspace_path}\n"
                    "阶段只是参考，不会限制工具；如果发现关键证据缺失，可以补充最小必要工具调用。\n"
                    "最终答复请包含：Material Passport 简表、主要产出或结论、质量门结果、仍需用户确认的决策、建议下一步。\n"
                    "必须保留证据边界：哪些来自已读材料，哪些只是推断或建议。不要声称已经核验未读取的文献或结果。"
                )
            write_rule = (
                "如果代码写入没有成功，必须明确说明本轮没有完成真实修改。"
                if mode == "coding" and code_change_intent
                else ""
            )
            return (
                "你现在是 Reviewer（审查者）。职责重点是检查任务是否满足用户目标并形成最终答复。\n"
                f"当前项目目录：{workspace_path}\n"
                "阶段只是参考，不会限制工具；如果发现关键验证或证据缺失，可以补充最小必要工具调用。"
                "最终答复请包含：已完成内容、依据/变更文件、验证情况、遗漏或剩余风险。"
                f"{write_rule}"
            )
        return ""

    def _mark_next_plan_step_running(
        self,
        execution_plan: dict[str, Any] | None,
        tool_call: dict[str, Any],
    ) -> int | None:
        if not execution_plan:
            return None
        steps = execution_plan.get("steps")
        if not isinstance(steps, list):
            return None
        function = tool_call.get("function") or {}
        active_tool = str(function.get("name") or "")
        tool_id = self._normalize_tool_id(active_tool)
        pending_indexes = [
            index for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("status") in {None, "pending"}
        ]
        if not pending_indexes:
            return None

        matched_index = next(
            (
                index for index in pending_indexes
                if self._tool_matches_plan_step(tool_id, steps[index])
            ),
            None,
        )
        if matched_index is None:
            # Avoid marking a write/create step complete just because the model
            # performed another read/search. Unmatched tool calls remain visible
            # in the tool log, while the plan stays honest.
            return None

        step = steps[matched_index]
        step["status"] = "running"
        step["active_tool"] = active_tool
        return matched_index

    def _normalize_tool_id(self, value: Any) -> str:
        return str(value or "").strip().replace("__", ".")

    def _tool_matches_plan_step(self, tool_id: str, step: dict[str, Any]) -> bool:
        hint = self._normalize_tool_id(step.get("tool_hint")).lower()
        title = str(step.get("title") or "").lower()
        description = str(step.get("description") or "").lower()
        text = f"{hint} {title} {description}"
        tool_id = self._normalize_tool_id(tool_id).lower()
        if not tool_id:
            return False
        # 精确匹配：tool_hint 中包含真实工具 ID
        if tool_id in hint:
            return True

        # 模糊匹配：如果 hint 中提到了工具前缀（如 filesystem.list_dir），
        # 可能是模型生成了不精确的工具名。此时仍尝试通过步骤标题/描述的
        # 语义关键词匹配，而不是直接拒绝。
        hint_has_tool_prefix = any(
            prefix in hint for prefix in ("filesystem.", "code.", "document.", "shell.", "git.")
        )

        write_terms = (
            "写", "写入", "修改", "编辑", "替换", "创建", "新增", "生成", "导出",
            "优化", "补充", "更新", "write", "edit", "replace", "create",
            "generate", "export", "update", "modify", "optimize",
        )
        read_terms = (
            "读", "读取", "扫描", "搜索", "查看", "枚举", "列出", "定位",
            "read", "scan", "search", "list", "inspect", "enumerate",
        )
        verify_terms = (
            "验证", "测试", "检查", "运行", "diff", "status", "verify", "test", "lint",
        )
        if self._is_write_tool(tool_id):
            if not hint_has_tool_prefix:
                return any(term in text for term in write_terms)
            # hint 已明确指向某类工具前缀，但不是写入类工具 → 不匹配
            return False
        if self._is_verification_tool(tool_id, None):
            if not hint_has_tool_prefix:
                return any(term in text for term in verify_terms)
            return False
        if tool_id in self._explorer_tool_ids("coding") or tool_id in self._read_only_tool_ids("coding"):
            return any(term in text for term in read_terms)
        return False

    def _finish_plan_step(
        self,
        execution_plan: dict[str, Any],
        step_index: int,
        tool_event: dict[str, Any],
    ) -> None:
        steps = execution_plan.get("steps") or []
        if step_index < 0 or step_index >= len(steps) or not isinstance(steps[step_index], dict):
            return
        step = steps[step_index]
        step["status"] = "completed" if tool_event.get("status") == "success" else "failed"
        step["tool"] = tool_event.get("name") or tool_event.get("tool") or ""
        step["task_id"] = tool_event.get("task_id") or ""
        if tool_event.get("error"):
            step["error"] = tool_event["error"]

    def _complete_remaining_plan_steps(
        self,
        execution_plan: dict[str, Any],
        *,
        failed: bool,
        had_tool_events: bool = True,
    ) -> None:
        for step in execution_plan.get("steps") or []:
            if not isinstance(step, dict) or step.get("status") not in {None, "pending", "running"}:
                continue
            if failed:
                step["status"] = "skipped"
            elif had_tool_events:
                step["status"] = "skipped"
                step.setdefault("note", "未观察到对应工具事件")
            else:
                step["status"] = "skipped"

    def _build_model_tools(self, mode_config: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
        allowed_tools: set[str] | None = None
        if mode_config and "tools" in mode_config:
            allowed_tools = set(mode_config["tools"])
        tools: list[dict[str, Any]] = []
        name_map: dict[str, str] = {}
        for spec in self.runtime.registry.list_specs():
            if allowed_tools is not None and spec["id"] not in allowed_tools:
                continue
            if not self.runtime.settings.is_tool_enabled(spec["id"]):
                continue
            model_name = self._model_tool_name(spec["id"])
            name_map[model_name] = spec["id"]
            name_map[spec["id"]] = spec["id"]
            tools.append({
                "type": "function",
                "function": {
                    "name": model_name,
                    "description": spec["description"],
                    "parameters": spec["input_schema"],
                },
            })
        return tools, name_map

    def _model_tool_name(self, tool_id: str) -> str:
        return tool_id.replace(".", "__")

    def _messages_for_model_round(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if tools:
            return messages
        sanitized: list[dict[str, Any]] = []
        for item in messages:
            role = str(item.get("role") or "")
            if role == "tool":
                name = str(item.get("name") or "tool")
                content = str(item.get("content") or "")
                sanitized.append({
                    "role": "assistant",
                    "content": f"工具结果摘要（{name}）：{content[:3000]}",
                })
                continue
            if role == "assistant" and item.get("tool_calls"):
                calls: list[str] = []
                for call in item.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") if isinstance(call.get("function"), dict) else {}
                    tool_name = str(function.get("name") or "tool")
                    args = str(function.get("arguments") or "{}")
                    calls.append(f"{tool_name}({args[:500]})")
                content = str(item.get("content") or "").strip()
                summary = "已调用工具：" + "；".join(calls[:8])
                sanitized.append({
                    "role": "assistant",
                    "content": (content + "\n" if content else "") + summary,
                })
                continue
            if role in {"system", "user", "assistant"}:
                sanitized.append({
                    "role": role,
                    "content": str(item.get("content") or ""),
                })
        return sanitized

    def _merge_tool_call_chunks(self, calls: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
        for chunk in chunks:
            try:
                index = int(chunk.get("index", 0) or 0)
            except (TypeError, ValueError):
                index = 0
            while len(calls) <= index:
                calls.append({
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                })
            target = calls[index]
            if chunk.get("id"):
                target["id"] = chunk["id"]
            if chunk.get("type"):
                target["type"] = chunk["type"]
            function = chunk.get("function") or {}
            if function.get("name"):
                target["function"]["name"] = function["name"]
            if function.get("arguments"):
                target["function"]["arguments"] += function["arguments"]

    def _complete_tool_calls(self, calls: list[dict[str, Any]], round_index: int) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        for index, call in enumerate(calls):
            function = call.get("function") or {}
            if not function.get("name"):
                continue
            completed.append({
                "id": call.get("id") or f"call_{round_index}_{index}",
                "type": call.get("type") or "function",
                "function": {
                    "name": function["name"],
                    "arguments": function.get("arguments") or "{}",
                },
            })
        return completed

    def _tool_call_details(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        function = tool_call.get("function") or {}
        model_tool_name = function.get("name") or ""
        tool_id = tool_name_map.get(model_tool_name) or model_tool_name.replace("__", ".")
        arguments_text = function.get("arguments") or "{}"
        try:
            arguments = json.loads(arguments_text)
            if not isinstance(arguments, dict):
                arguments = {}
        except json.JSONDecodeError:
            arguments = {}
        return tool_id, arguments

    def _tool_signature(self, tool_id: str, arguments: dict[str, Any]) -> str:
        normalized: dict[str, Any]
        if tool_id == "code.search_text":
            normalized = {
                "path": arguments.get("path"),
                "query": arguments.get("query"),
                "include_extensions": arguments.get("include_extensions") or [],
            }
        elif tool_id in {"filesystem.read_file", "filesystem.read_text_preview"}:
            normalized = {
                "path": arguments.get("path"),
                "start_line": arguments.get("start_line"),
                "end_line": arguments.get("end_line"),
            }
        elif tool_id in {"filesystem.scan_folder", "code.list_project_files"}:
            normalized = {
                "path": arguments.get("path"),
                "include_extensions": arguments.get("include_extensions") or [],
            }
        else:
            normalized = arguments
        return json.dumps(
            {"tool": tool_id, "input": normalized},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    def _document_write_tool_ids(self) -> set[str]:
        return {
            "document.export_markdown",
            "document.export_docx",
            "document.generate_docx_from_outline",
            "document.export_pdf",
            "document.generate_ppt",
            "document.merge_pdfs",
            "document.split_pdf",
            "document.create_bookmark_outline",
        }

    def _write_tool_ids(self) -> set[str]:
        return {
            "code.edit_file",
            "code.replace_text",
            "filesystem.write_file",
            *self._document_write_tool_ids(),
        }

    def _read_only_tool_ids(self, mode: str | None) -> set[str]:
        ids = self._explorer_tool_ids(mode)
        ids |= {"git.status", "git.diff", "git.log"}
        return ids

    def _post_write_verify_tool_ids(self) -> set[str]:
        return {"shell.run_command", "git.status", "git.diff", "code.search_text", "code.list_project_files", "git.log"}

    def _verification_tool_ids(self, mode: str | None) -> set[str]:
        ids = set(self._post_write_verify_tool_ids())
        if mode in {"document", "paper"}:
            ids |= {
                "filesystem.scan_folder",
                "filesystem.read_file",
                "filesystem.read_text_preview",
                "document.extract_docx_outline",
                "document.extract_pdf_text_preview",
            }
        return ids

    def _post_write_tool_ids(self) -> set[str]:
        return self._write_tool_ids() | self._post_write_verify_tool_ids() | self._post_write_read_tool_ids()

    def _execution_pressure_tool_ids(self, mode: str | None) -> set[str]:
        return (
            self._write_tool_ids()
            | self._explorer_tool_ids(mode)
            | {"git.status", "git.diff"}
        )

    def _editor_repair_tool_ids(self, mode: str | None, *, force_full_file_rewrite: bool = False) -> set[str]:
        if force_full_file_rewrite:
            return {
                "filesystem.read_file",
                "filesystem.read_text_preview",
                "filesystem.write_file",
            }
        return self._write_tool_ids() | self._explorer_tool_ids(mode)

    def _post_write_read_tool_ids(self) -> set[str]:
        """允许在 post_write 阶段读取文件——多文件任务中创建后续文件前需要读取参考。"""
        return {"filesystem.read_file", "filesystem.read_text_preview", "filesystem.scan_folder"}

    def _is_write_tool(self, tool_id: str) -> bool:
        return tool_id in self._write_tool_ids()

    def _is_state_changing_tool(self, tool_id: str) -> bool:
        return self._is_write_tool(tool_id) or tool_id in {
            "shell.run_command",
            "git.commit",
        }

    def _is_post_write_verify_tool(self, tool_id: str) -> bool:
        return tool_id in self._post_write_verify_tool_ids()

    def _is_verification_tool(self, tool_id: str, mode: str | None) -> bool:
        return tool_id in self._verification_tool_ids(mode)

    def _is_post_write_tool(self, tool_id: str) -> bool:
        return tool_id in self._post_write_tool_ids()

    def _filter_tools_by_ids(
        self,
        tools: list[dict[str, Any]],
        tool_name_map: dict[str, str],
        allowed_ids: set[str],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            model_name = str(function.get("name") or "")
            tool_id = tool_name_map.get(model_name) or model_name.replace("__", ".")
            if tool_id in allowed_ids:
                result.append(tool)
        return result

    def _is_recon_tool(self, tool_id: str) -> bool:
        return tool_id in {
            "filesystem.scan_folder",
            "filesystem.read_file",
            "filesystem.read_text_preview",
            "document.extract_docx_outline",
            "document.extract_pdf_text_preview",
            "code.search_text",
            "code.list_project_files",
            "git.status",
            "git.diff",
            "git.log",
        }

    def _skipped_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_id: str,
        arguments: dict[str, Any],
        *,
        reason: str,
        message: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        model_tool_name = ((tool_call.get("function") or {}).get("name") or self._model_tool_name(tool_id))
        event = {
            "status": "failure",
            "tool": tool_id,
            "name": self._tool_display_name(tool_id),
            "input": arguments,
            "task_id": "",
            "error": message,
            "output": {"type": "guard", "reason": reason, "message": message},
        }
        tool_payload = {
            "tool": tool_id,
            "input": arguments,
            "status": "failure",
            "output": {"reason": reason, "message": message},
            "error": message,
        }
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": model_tool_name,
            "content": self._compact_tool_payload(tool_payload),
        }, event

    def _progress_key(self, tool_events: list[dict[str, Any]], mode: str | None) -> str:
        significant: list[dict[str, Any]] = []
        for event in tool_events[-16:]:
            tool_id = str(event.get("tool") or "")
            status = str(event.get("status") or "")
            event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
            if status != "success":
                continue
            if (
                self._is_write_tool(tool_id)
                or self._is_verification_tool(tool_id, mode)
                or self._is_recon_tool(tool_id)
            ):
                significant.append({
                    "tool": tool_id,
                    "path": event_input.get("path") or event_input.get("output_path") or event_input.get("cwd") or "",
                    "query": event_input.get("query") or event_input.get("old_text") or event_input.get("old_string") or "",
                    "task_id": event.get("task_id") or "",
                })
        return json.dumps(significant, ensure_ascii=False, sort_keys=True)

    def _round_has_only_non_progress(self, round_events: list[dict[str, Any]]) -> bool:
        if not round_events:
            return False
        for event in round_events:
            if event.get("status") == "success":
                return False
        return True

    def _looks_like_dangling_action(self, content: str) -> bool:
        text = content.strip()
        if not text:
            return False
        tail = text[-260:].lower()
        action_terms = (
            "让我先", "我先", "接下来", "现在我", "我将", "我会", "准备",
            "开始", "需要先", "继续", "let me", "i will", "next",
        )
        toolish_terms = (
            "验证", "检查", "读取", "搜索", "查找", "扫描", "修改", "写入",
            "替换", "运行", "调用", "测试", "确认", "verify", "check",
            "read", "search", "scan", "edit", "write", "run", "test",
        )
        dangling_endings = ("：", ":", "。", ".", "先验证一下", "先检查一下", "先读取", "开始执行修改")
        has_action = any(term in tail for term in action_terms)
        has_toolish = any(term in tail for term in toolish_terms)
        if has_action and has_toolish:
            if text.endswith(("：", ":")):
                return True
            if any(tail.endswith(ending.lower()) for ending in dangling_endings):
                return True
            return True
        return False

    def _dangling_action_prompt(
        self,
        workspace_path: str,
        unfinished_text: str,
        tool_events: list[dict[str, Any]],
        mode: str | None,
    ) -> str:
        snippet = unfinished_text[-200:]
        return (
            f"悬空动作：项目={workspace_path}。未完成：{snippet}\n"
            "请调用本地工具执行动作，或直接输出最终总结（变更文件+验证结果+风险）。"
            "不要只说'我先验证/我将检查/接下来处理'。"
        )

    def _needs_synthesized_final_answer(self, content: str, tool_events: list[dict[str, Any]]) -> bool:
        if not tool_events:
            return False
        text = (content or "").strip()
        if not text or text == "模型没有返回内容。":
            return True
        return self._looks_like_dangling_action(text)

    def _synthesize_final_answer(
        self,
        workspace_path: str,
        tool_events: list[dict[str, Any]],
        change_summary: dict[str, Any] | None,
        mode: str | None,
    ) -> str:
        write_paths: list[str] = []
        verify_lines: list[str] = []
        failure_lines: list[str] = []
        for event in tool_events:
            tool_id = str(event.get("tool") or "")
            status = str(event.get("status") or "")
            event_input = event.get("input") if isinstance(event.get("input"), dict) else {}
            output = event.get("output") if isinstance(event.get("output"), dict) else {}
            path = (
                event_input.get("path")
                or event_input.get("output_path")
                or output.get("path")
                or ""
            )
            rel_path = self._relative_workspace_path(workspace_path, path) if path else ""
            display_path = rel_path or str(path or "")
            if self._is_write_tool(tool_id) and status == "success" and display_path:
                write_paths.append(display_path)
            if self._is_verification_tool(tool_id, mode) and status == "success":
                detail = tool_id
                query = event_input.get("query")
                if query:
                    detail += f"（搜索：{query}）"
                elif display_path:
                    detail += f"（{display_path}）"
                verify_lines.append(detail)
            if status == "failure":
                error = str(event.get("error") or "").strip()
                failure_lines.append(f"{tool_id}: {error[:160] if error else '失败'}")

        changed_paths: list[str] = []
        if isinstance(change_summary, dict):
            for item in change_summary.get("files") or []:
                if isinstance(item, dict) and item.get("path"):
                    changed_paths.append(str(item["path"]))
        if not changed_paths:
            changed_paths = list(dict.fromkeys(write_paths))
        write_paths = list(dict.fromkeys(write_paths))
        verify_lines = list(dict.fromkeys(verify_lines))

        lines = ["系统检测到模型最终回复停在待执行语句，已按真实工具记录收束本轮结果。"]
        if changed_paths:
            lines.append("")
            lines.append("新增/变更文件：")
            lines.extend(f"- {path}" for path in changed_paths[:12])
        elif write_paths:
            lines.append("")
            lines.append("成功写入文件：")
            lines.extend(f"- {path}" for path in write_paths[:12])
        else:
            lines.append("")
            lines.append("本轮没有观察到成功写入文件。")

        lines.append("")
        if verify_lines:
            lines.append("已执行验证：")
            lines.extend(f"- {item}" for item in verify_lines[:8])
        else:
            lines.append("未观察到成功验证工具调用。")

        if failure_lines:
            lines.append("")
            lines.append("失败或风险：")
            lines.extend(f"- {item}" for item in failure_lines[:6])
        return "\n".join(lines)

    def _progress_observer_prompt(
        self,
        workspace_path: str,
        current_stage: str,
        tool_events: list[dict[str, Any]],
        code_change_intent: bool,
        reason: str,
    ) -> str:
        action_rule = ""
        if code_change_intent and not self._has_successful_write(tool_events):
            action_rule = (
                "需要真实修改文件但尚未写入。请直接调用 code.edit_file / code.replace_text / filesystem.write_file，"
                "或只读取一个最小必要文件后写入。"
            )
        return (
            f"进度纠偏（{reason}）：项目={workspace_path}，阶段={current_stage or '无'}。"
            f"{action_rule}"
            "所有工具仍可用，请根据最新上下文推进。"
        )

    def _recon_budget_prompt(self, budget: int, workspace_path: str) -> str:
        return (
            f"侦察预算已用完（{budget} 次读取/搜索）。项目={workspace_path}。"
            "下一轮必须推进：读取最小必要片段后调用 code.edit_file / code.replace_text / filesystem.write_file，"
            "或明确说明缺少什么信息导致无法修改。不要用文字声称已修改。"
        )

    def _write_only_stage_prompt(self, workspace_path: str) -> str:
        return (
            f"执行压力阶段：项目={workspace_path}。"
            "每次读取必须服务于写入（说明要确认哪个文件/位置/old_text）。"
            "上下文足够时立即调用写入工具；不够时只读取最小必要片段。"
        )

    def _requires_runtime_confirmation(self, tool_id: str) -> bool:
        if tool_id not in self._document_write_tool_ids() and tool_id != "filesystem.write_file":
            return False
        try:
            tool = self.runtime.registry.get(tool_id)
        except KeyError:
            return False
        return bool(tool.spec.requires_confirmation)

    async def _confirm_runtime_tool_call(self, tool_id: str, arguments: dict[str, Any]) -> bool:
        conversation_id = str(getattr(self, "_active_conversation_id", "") or "")
        if not conversation_id:
            return True

        confirm_event = asyncio.Event()
        _pending_confirms[conversation_id] = confirm_event
        _confirm_responses.pop(conversation_id, None)
        target = (
            arguments.get("path")
            or arguments.get("output_path")
            or arguments.get("output_dir")
            or ""
        )
        self.write_event({
            "event": "confirm",
            "message": f"即将执行文件写入工具 {self._tool_display_name(tool_id)}"
            + (f"：{target}" if target else "")
            + "，是否继续？（5 分钟内未响应将自动取消）",
            "tool": tool_id,
            "input": arguments,
        })
        await self.flush()
        try:
            await asyncio.wait_for(confirm_event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            pass
        finally:
            _pending_confirms.pop(conversation_id, None)
        return _confirm_responses.pop(conversation_id, "cancel") == "continue"

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        tool_name_map: dict[str, str],
        workspace_path: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        function = tool_call.get("function") or {}
        model_tool_name = function.get("name") or ""
        tool_id = tool_name_map.get(model_tool_name) or model_tool_name.replace("__", ".")
        arguments_text = function.get("arguments") or "{}"
        try:
            arguments = json.loads(arguments_text)
            if not isinstance(arguments, dict):
                arguments = {}
        except json.JSONDecodeError:
            # Try to fix common JSON issues from streaming (unclosed braces/brackets)
            arguments = self._try_fix_json(arguments_text)

        if not self.runtime.settings.is_tool_enabled(tool_id):
            return self._skipped_tool_call(
                tool_call,
                tool_id,
                arguments,
                reason="plugin_disabled",
                message=f"插件已禁用，不能调用工具：{tool_id}",
            )

        if self._requires_runtime_confirmation(tool_id):
            confirmed = await self._confirm_runtime_tool_call(tool_id, arguments)
            if not confirmed:
                return self._skipped_tool_call(
                    tool_call,
                    tool_id,
                    arguments,
                    reason="user_cancelled_tool",
                    message=f"用户取消了写入工具调用：{tool_id}",
                )

        event: dict[str, Any] = {
            "status": "running",
            "tool": tool_id,
            "name": self._tool_display_name(tool_id),
            "input": arguments,
        }
        self.write_event({"event": "tool", **event})
        await self.flush()

        task_future = asyncio.create_task(self.runtime.runner.submit(
            tool_id,
            arguments,
            wait=True,
            confirmed=True,
            workspace_path=workspace_path,
        ))
        started_at = asyncio.get_running_loop().time()
        while not task_future.done():
            await asyncio.sleep(10)
            if task_future.done():
                break
            elapsed = int(asyncio.get_running_loop().time() - started_at)
            self.write_event({
                "event": "heartbeat",
                "message": f"工具仍在运行：{self._tool_display_name(tool_id)}，已等待 {elapsed}s",
                "idle_seconds": elapsed,
            })
            await self.flush()
        task = await task_future
        output_preview = self._tool_output_preview(tool_id, task.output)
        event = {
            "status": task.status,
            "tool": tool_id,
            "name": self._tool_display_name(tool_id),
            "input": arguments,
            "task_id": task.id,
            "error": task.error,
            "output": output_preview,
        }
        tool_payload = {
            "tool": tool_id,
            "input": arguments,
            "status": task.status,
            "output": task.output,
            "error": task.error,
        }
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": model_tool_name,
            "content": self._compact_tool_payload(tool_payload),
        }, event

    def _try_fix_json(self, text: str) -> dict[str, Any]:
        """Attempt to repair truncated or malformed JSON from model tool calls."""
        text = text.strip()
        if not text:
            return {}
        # Try closing unclosed braces/brackets
        opens = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")
        fixed = text
        if open_brackets > 0:
            fixed += "]" * open_brackets
        if opens > 0:
            fixed += "}" * opens
        try:
            result = json.loads(fixed)
            return result if isinstance(result, dict) else {}
        except (json.JSONDecodeError, ValueError):
            pass
        # Try adding a closing quote if string is unclosed
        if fixed.count('"') % 2 != 0:
            fixed += '"'
            if open_brackets > 0:
                fixed += "]" * open_brackets
            if opens > 0:
                fixed += "}" * opens
            try:
                result = json.loads(fixed)
                return result if isinstance(result, dict) else {}
            except (json.JSONDecodeError, ValueError):
                pass
        return {}

    def _tool_display_name(self, tool_id: str) -> str:
        try:
            return self.runtime.registry.get(tool_id).spec.name
        except KeyError:
            return tool_id

    def _tool_output_preview(self, tool_id: str, output: Any) -> dict[str, Any] | None:
        """Extract a small preview of tool output for frontend rich rendering."""
        if not output or not isinstance(output, dict):
            return None
        preview: dict[str, Any] = {}
        if tool_id == "shell.run_command":
            stdout = str(output.get("stdout") or "")[:4000]
            stderr = str(output.get("stderr") or "")[:2000]
            preview = {"type": "shell", "exit_code": output.get("exit_code"), "stdout": stdout, "stderr": stderr}
        elif tool_id == "code.edit_file":
            preview = {
                "type": "diff",
                "path": output.get("path"),
                "diff_preview": str(output.get("diff_preview") or "")[:4000],
                "backup": output.get("_backup"),
            }
        elif tool_id == "code.replace_text":
            preview = {
                "type": "bulk_replace",
                "root": output.get("root"),
                "old_text": output.get("old_text"),
                "new_text": output.get("new_text"),
                "dry_run": bool(output.get("dry_run")),
                "changed_files": (output.get("changed_files") or [])[:80],
                "changed_file_count": output.get("changed_file_count"),
                "matched_file_count": output.get("matched_file_count"),
                "replacement_count": output.get("replacement_count"),
                "truncated": bool(output.get("truncated")),
                "backup": output.get("_backup"),
            }
        elif tool_id == "filesystem.write_file":
            preview = {
                "type": "file_write",
                "path": output.get("path"),
                "created": bool(output.get("created")),
                "size": output.get("size"),
                "backup": output.get("_backup"),
            }
        elif tool_id == "filesystem.read_file":
            preview = {
                "type": "file_read",
                "path": output.get("path"),
                "total_lines": output.get("total_lines"),
                "start_line": output.get("start_line"),
                "end_line": output.get("end_line"),
                "truncated": bool(output.get("truncated")),
                "remaining_lines": output.get("remaining_lines"),
                "next_start_line": output.get("next_start_line"),
                "next_end_line": output.get("next_end_line"),
            }
        elif tool_id == "filesystem.read_text_preview":
            preview = {
                "type": "file_preview",
                "path": output.get("path"),
                "size": output.get("size"),
                "truncated": bool(output.get("truncated")),
            }
        elif tool_id == "git.diff":
            preview = {"type": "diff", "diff_preview": str(output.get("diff") or "")[:4000]}
        elif tool_id == "git.status":
            preview = {"type": "git_status", "files": (output.get("files") or [])[:40]}
        elif tool_id == "git.log":
            preview = {"type": "git_log", "commits": (output.get("commits") or [])[:10]}
        elif tool_id.startswith("web."):
            preview = {
                "type": "web",
                "url": output.get("url") or output.get("final_url"),
                "final_url": output.get("final_url") or output.get("url"),
                "status_code": output.get("status_code"),
                "title": output.get("title") or "",
                "text": str(output.get("text") or "")[:4000],
                "links": (output.get("links") or [])[:20],
                "truncated": bool(output.get("truncated")),
            }
        else:
            return None
        return preview

    async def _capture_git_status(
        self,
        workspace_path: str,
        mode_config: dict[str, Any],
    ) -> dict[str, Any] | None:
        if mode_config.get("tools") and "git.status" not in set(mode_config.get("tools") or []):
            return None
        try:
            tool = self.runtime.registry.get("git.status")
            context = ToolContext(
                path_guard=self.runtime.runner.path_guard,
                task_id="internal.git.status",
                log=lambda *_args, **_kwargs: None,
            )
            output = await tool.handler({"path": workspace_path}, context)
        except Exception:
            return None
        return output if isinstance(output, dict) else None

    async def _build_change_summary(
        self,
        workspace_path: str,
        mode_config: dict[str, Any],
        baseline: dict[str, Any] | None,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        final_status = await self._capture_git_status(workspace_path, mode_config)
        touched_paths = self._collect_touched_paths(workspace_path, tool_events)
        if not final_status:
            if not touched_paths:
                return None
            return {
                "source": "tool-events",
                "clean": None,
                "files": [{"status": "touched", "path": path} for path in touched_paths[:80]],
                "file_count": len(touched_paths),
                "total_dirty_count": None,
                "truncated": len(touched_paths) > 80,
            }

        final_files = final_status.get("files") or []
        baseline_files = baseline.get("files") if baseline else []
        baseline_map = {
            self._normalize_display_path(item.get("path")): str(item.get("status") or "")
            for item in baseline_files or []
            if isinstance(item, dict) and item.get("path")
        }
        touched_set = set(touched_paths)
        changed_files: list[dict[str, str]] = []
        for item in final_files:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            path = self._normalize_display_path(item.get("path"))
            status = str(item.get("status") or "")
            if baseline is None or baseline_map.get(path) != status or path in touched_set:
                changed_files.append({"status": status, "path": path})

        known_paths = {item["path"] for item in changed_files}
        for path in touched_paths:
            if path not in known_paths:
                changed_files.append({"status": "clean", "path": path})
                known_paths.add(path)

        if not changed_files:
            return None

        return {
            "source": "git-status",
            "branch": final_status.get("branch") or "",
            "clean": bool(final_status.get("clean")),
            "files": changed_files[:80],
            "file_count": len(changed_files),
            "total_dirty_count": int(final_status.get("file_count") or 0),
            "truncated": len(changed_files) > 80,
        }

    def _collect_touched_paths(self, workspace_path: str, tool_events: list[dict[str, Any]]) -> list[str]:
        paths: list[str] = []
        for event in tool_events:
            if event.get("status") != "success":
                continue
            tool_id = event.get("tool")
            if tool_id not in {"code.edit_file", "code.replace_text", "filesystem.write_file"}:
                continue
            output = event.get("output") if isinstance(event.get("output"), dict) else {}
            input_data = event.get("input") if isinstance(event.get("input"), dict) else {}
            candidates: list[Any] = []
            if tool_id == "code.replace_text":
                root = output.get("root") or input_data.get("path") or workspace_path
                for item in output.get("changed_files") or []:
                    if isinstance(item, dict) and item.get("path"):
                        candidates.append(str(Path(str(root)) / str(item["path"])))
                if not candidates:
                    candidates.append(root)
            else:
                candidates.append(output.get("path") or input_data.get("path"))
            for candidate in candidates:
                rel = self._relative_workspace_path(workspace_path, candidate)
                if rel and rel not in paths:
                    paths.append(rel)
        return paths

    def _relative_workspace_path(self, workspace_path: str, path_value: Any) -> str:
        if not path_value:
            return ""
        text = str(path_value)
        try:
            path = Path(text)
            if path.is_absolute():
                return self._normalize_display_path(path.relative_to(Path(workspace_path)))
        except ValueError:
            return self._normalize_display_path(text)
        except OSError:
            return self._normalize_display_path(text)
        return self._normalize_display_path(text)

    def _normalize_display_path(self, path_value: Any) -> str:
        return str(path_value or "").replace("\\", "/")

    def _is_runtime_guidance_message(self, message: Any) -> bool:
        metadata = getattr(message, "metadata", {}) or {}
        return bool(metadata.get("guidance") and metadata.get("during_run"))

    def _discard_parts(self, target: list[str], parts: list[str]) -> None:
        if not parts:
            return
        del target[-len(parts):]

    def _read_file_range_record(
        self,
        arguments: dict[str, Any],
        tool_event: dict[str, Any],
    ) -> dict[str, Any]:
        output = tool_event.get("output") if isinstance(tool_event.get("output"), dict) else {}
        path = str(output.get("path") or arguments.get("path") or "")
        start_line = output.get("start_line") or arguments.get("start_line") or 1
        end_line = output.get("end_line") or arguments.get("end_line")
        total_lines = output.get("total_lines")
        next_start_line = output.get("next_start_line")
        next_end_line = output.get("next_end_line")
        return {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": total_lines,
            "truncated": bool(output.get("truncated")),
            "next_start_line": next_start_line,
            "next_end_line": next_end_line,
        }

    def _read_range_summary_prompt(
        self,
        workspace_path: str,
        ranges: list[dict[str, Any]],
    ) -> str:
        lines = ["已读取文件片段（按行号范围记录）："]
        next_calls: list[str] = []
        for item in ranges:
            rel = self._relative_workspace_path(workspace_path, item.get("path")) or str(item.get("path") or "")
            start_line = item.get("start_line") or 1
            end_line = item.get("end_line") or "?"
            total = item.get("total_lines") or "?"
            lines.append(f"- {rel}: {start_line}-{end_line} / {total}")
            if item.get("truncated") and item.get("next_start_line"):
                next_calls.append(
                    f"- 如确实需要继续阅读 {rel}，请调用 filesystem.read_file "
                    f"并传入 start_line={item.get('next_start_line')}, end_line={item.get('next_end_line')}"
                )
        lines.append("不要重复读取完全相同的文件行号范围。")
        if next_calls:
            lines.append("长文件尚有后续内容；只有当当前任务确实依赖后续代码时，才继续读取下一段：")
            lines.extend(next_calls[:4])
        lines.append("如果现有片段已足以定位修改点，请直接调用写入工具；不要因为文件很长就停止执行。")
        return "\n".join(lines)

    def _previous_write_context(self, conversation: Any | None, current_content: str) -> bool:
        if conversation is None:
            return False
        current = current_content.strip()
        for message in reversed(getattr(conversation, "messages", [])[-16:]):
            if self._is_runtime_guidance_message(message):
                continue
            role = str(getattr(message, "role", "") or "")
            previous_content = str(getattr(message, "content", "") or "")
            if previous_content.strip() == current:
                continue
            metadata = getattr(message, "metadata", {}) or {}
            if role == "user":
                if self._has_no_write_instruction(previous_content):
                    return False
                if self._looks_like_code_change_request(previous_content):
                    return True
                continue
            if role != "assistant" or not isinstance(metadata, dict):
                continue
            contract = metadata.get("task_contract")
            if isinstance(contract, dict) and contract.get("requires_write"):
                return True
            if metadata.get("task_intent") in {"write_required", "document_export"}:
                return True
            if metadata.get("code_change_intent") is True:
                return True
            change_summary = metadata.get("change_summary")
            if isinstance(change_summary, dict) and int(change_summary.get("file_count") or 0) > 0:
                return True
            execution_notice = metadata.get("execution_notice")
            if isinstance(execution_notice, dict) and execution_notice.get("reason") in {
                "tool_contract_failed",
                "write_tool_failed",
                "no_successful_write_tool",
                "max_tool_rounds",
            }:
                return True
            execution_plan = metadata.get("execution_plan")
            if self._plan_has_pending_write_step(execution_plan):
                return True
            content_hint = previous_content.lower()
            if "继续" in content_hint and any(
                term in content_hint
                for term in ("优化", "修改", "写入", "创建", "未完成", "剩余", "页面", "seo")
            ):
                return True
        return False

    def _plan_has_pending_write_step(self, execution_plan: Any) -> bool:
        if not isinstance(execution_plan, dict):
            return False
        steps = execution_plan.get("steps")
        if not isinstance(steps, list):
            return False
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = step.get("status")
            if status not in {None, "pending", "running", "skipped"}:
                continue
            text = " ".join(
                str(step.get(key) or "").lower()
                for key in ("title", "description", "tool_hint")
            )
            if any(term in text for term in ("write", "edit", "replace", "create", "generate", "export")):
                return True
            if any(term in text for term in ("写", "修改", "编辑", "替换", "创建", "新增", "生成", "导出", "优化")):
                return True
        return False

    def _classify_task_intent(
        self,
        content: str,
        mode: str | None,
        conversation: Any | None = None,
    ) -> str:
        if self._has_no_write_instruction(content):
            return "read_only_analysis"
        if self._looks_like_follow_up_execution(content) and self._previous_write_context(conversation, content):
            return "write_required"
        if self._user_requests_code_change(content, "coding"):
            return "write_required"
        if self._looks_like_document_export_request(content):
            return "document_export"
        if self._looks_like_paper_task(content):
            return "paper_workflow"
        if mode == "coding":
            if self._user_requests_code_change(content, mode):
                return "write_required"
            if self._looks_like_read_only_request(content):
                return "read_only_analysis"
            if self._looks_like_follow_up_execution(content) and conversation is not None:
                for message in reversed(getattr(conversation, "messages", [])[-8:]):
                    if self._is_runtime_guidance_message(message):
                        continue
                    if getattr(message, "role", "") != "user":
                        continue
                    previous_content = str(getattr(message, "content", "") or "")
                    if previous_content.strip() == content.strip():
                        continue
                    if self._has_no_write_instruction(previous_content):
                        return "read_only_analysis"
                    if self._user_requests_code_change(previous_content, "coding"):
                        return "write_required"
            return "answer_only"
        if self._looks_like_read_only_request(content):
            return "read_only_analysis"
        return "answer_only"

    def _has_no_write_instruction(self, content: str) -> bool:
        text = content.lower()
        if not text:
            return False
        no_write_terms = (
            "不要改代码",
            "不用改代码",
            "先不要改代码",
            "先别改代码",
            "别改代码",
            "不改代码",
            "不要修改代码",
            "不要改文件",
            "不要修改文件",
            "不要动文件",
            "不要动代码",
            "不要写入",
            "不要执行修改",
            "不要改动",
            "不需要改动",
            "不需要修改",
            "无需修改",
            "先不改",
            "只分析",
            "仅分析",
            "只看",
            "只检查",
            "只给建议",
            "给出建议",
            "调整建议",
            "改进建议",
            "不要改",
            "no code changes",
            "do not modify",
            "don't modify",
            "read only",
            "analysis only",
        )
        return any(term in text for term in no_write_terms)

    def _looks_like_read_only_request(self, content: str) -> bool:
        text = content.lower()
        if not text:
            return False
        if self._has_no_write_instruction(content):
            return True
        if self._has_explicit_write_instruction(content):
            return False
        read_only_terms = (
            "分析",
            "检查",
            "查看",
            "看下",
            "看看",
            "梳理",
            "评估",
            "审查",
            "建议",
            "方案",
            "思路",
            "解释",
            "说明",
            "为什么",
            "如何",
            "是否",
            "可行性",
            "状态",
            "现状",
            "风险",
            "问题",
            "原因",
            "定位",
            "排查",
            "review",
            "analyze",
            "analyse",
            "explain",
            "suggest",
            "recommend",
        )
        return any(term in text for term in read_only_terms)

    def _looks_like_document_export_request(self, content: str) -> bool:
        text = content.lower()
        export_terms = (
            "导出",
            "生成word",
            "生成 word",
            "生成docx",
            "生成 docx",
            "生成pdf",
            "生成 pdf",
            "生成ppt",
            "生成 ppt",
            "保存为",
            "写成文件",
            "输出文件",
            ".docx",
            ".pdf",
            ".pptx",
            ".md",
        )
        return any(term in text for term in export_terms)

    def _has_explicit_write_instruction(self, content: str) -> bool:
        text = content.lower()
        if not text:
            return False
        explicit_write_terms = (
            "帮我改",
            "帮我修",
            "帮我加",
            "帮我删",
            "开始改",
            "直接改",
            "继续改",
            "继续做",
            "继续优化",
            "优化网站",
            "优化页面",
            "优化其他页",
            "创建robots",
            "生成robots",
            "创建sitemap",
            "生成sitemap",
            "按你说的继续改进",
            "按你说的改",
            "修复",
            "改成",
            "改造",
            "改造成",
            "改为",
            "替换",
            "新增",
            "添加",
            "添加路由",
            "删除",
            "移除",
            "去掉",
            "实现",
            "创建页面",
            "创建逻辑",
            "独立页面",
            "修改导航",
            "接入",
            "更新",
            "重构",
            "补上",
            "写入",
            "生成文件",
            "变更",
            "恢复",
            "回退",
            "apply",
            "implement",
            "fix",
            "update",
            "modify",
            "change",
            "refactor",
            "remove",
            "delete",
            "add",
        )
        return any(term in text for term in explicit_write_terms)

    def _effective_mode(
        self,
        requested_mode: str | None,
        content: str,
        conversation: Any | None = None,
    ) -> str:
        if requested_mode == "coding":
            return "coding"
        if requested_mode == "paper":
            return "paper"
        if self._looks_like_follow_up_execution(content) and self._previous_write_context(conversation, content):
            return "coding"
        if self._user_requests_code_change(content, "coding"):
            return "coding"
        if self._looks_like_paper_task(content):
            return "paper"
        if self._looks_like_follow_up_execution(content) and conversation is not None:
            for message in reversed(getattr(conversation, "messages", [])[-8:]):
                if self._is_runtime_guidance_message(message):
                    continue
                if getattr(message, "role", "") != "user":
                    continue
                previous_content = str(getattr(message, "content", "") or "")
                if previous_content.strip() == content.strip():
                    continue
                if self._user_requests_code_change(previous_content, "coding"):
                    return "coding"
                if self._looks_like_paper_task(previous_content):
                    return "paper"
        if self._looks_like_document_export_request(content):
            return "document"
        return requested_mode or "terminal"

    def _looks_like_paper_task(self, content: str) -> bool:
        text = content.lower()
        if not text:
            return False
        paper_terms = (
            "论文", "文献综述", "系统综述", "研究设计", "研究问题", "研究假设", "研究方法",
            "摘要", "引言", "相关工作", "方法论", "讨论", "结论", "参考文献", "引用",
            "审稿", "审稿意见", "审稿回复", "投稿", "期刊", "学术", "开题", "课题",
            "paper", "literature review", "systematic review", "abstract", "citation",
            "reviewer", "journal", "doi",
        )
        return any(term in text for term in paper_terms)

    def _looks_like_follow_up_execution(self, content: str) -> bool:
        text = content.strip().lower()
        if len(text) > 40:
            return False
        terms = (
            "继续",
            "再执行",
            "再次执行",
            "重新执行",
            "重试",
            "再试",
            "试试",
            "继续优化",
            "继续执行",
            "继续处理",
            "接着做",
            "往下做",
            "接着改",
            "按这个改",
            "就这样改",
            "继续改",
            "继续做",
        )
        return any(term in text for term in terms)

    def _looks_like_code_change_request(self, content: str) -> bool:
        text = content.lower()
        if not text:
            return False

        # Analysis-only requests should NOT be treated as code change
        analysis_only_terms = (
            "分析代码", "检查代码", "看下代码", "代码逻辑", "解读代码",
            "帮我看看", "帮我分析", "帮我理解", "什么意思", "怎么工作",
            "调用工具", "能否找到原因", "排查", "定位问题",
        )
        if any(term in text for term in analysis_only_terms):
            # Only if there's also a clear write signal, allow it
            explicit_write = ("并修复", "然后改", "然后修", "并改", "顺便改", "帮我修")
            if not any(term in text for term in explicit_write):
                return False

        code_context_terms = (
            ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".css", ".json",
            "代码", "文件", "函数", "组件", "页面", "前端", "后端", "接口", "路由",
            "端口", "配置", "样式", "布局", "按钮", "输入框", "目录", "登录",
            "报错", "bug", "ui", "css", "js", "html", "vue", "react",
            "seo", "网站", "网页", "meta", "robots.txt", "sitemap.xml",
            "canonical", "open graph", "twitter card",
        )
        direct_write_terms = (
            "帮我改", "帮我修", "帮我加", "帮我删", "开始做", "直接改", "修复",
            "改成", "改造", "改造成", "改为", "替换", "新增", "添加", "添加路由", "删除", "移除", "去掉",
            "实现", "创建页面", "创建逻辑", "独立页面", "修改导航", "接入", "更新", "调整", "重构", "补上", "写入", "生成",
            "变更", "恢复", "回退", "太大", "太小", "没反应", "加载不出来",
            "优化网站", "优化页面", "优化其他页", "继续优化",
            "创建robots", "生成robots", "创建sitemap", "生成sitemap",
            "添加meta", "补充meta",
        )
        broad_write_terms = ("修改", "改", "修", "加", "删")

        if any(term in text for term in direct_write_terms):
            return True
        return any(term in text for term in broad_write_terms) and any(
            term in text for term in code_context_terms
        )

    def _looks_like_simple_code_change(self, content: str) -> bool:
        text = content.lower().strip()
        if len(text) > 100:
            return False
        broad_terms = (
            "全部", "完整", "全局", "很多文件", "多文件", "重构", "实现", "接入",
            "测试", "验证", "生成报告", "计划执行",
        )
        if any(term in text for term in broad_terms):
            return False
        simple_terms = (
            "字太大", "字太小", "太大", "太小", "改小", "改大", "按钮",
            "颜色", "间距", "文案", "样式", "布局", "显示", "隐藏", "没反应",
        )
        return any(term in text for term in simple_terms)

    def _code_change_intent(
        self,
        content: str,
        mode: str | None,
        conversation: Any | None = None,
    ) -> bool:
        if self._has_no_write_instruction(content):
            return False
        if self._user_requests_code_change(content, mode):
            return True
        if self._looks_like_follow_up_execution(content) and self._previous_write_context(conversation, content):
            return True
        if mode != "coding" or not self._looks_like_follow_up_execution(content):
            return False
        if conversation is None:
            return False
        for message in reversed(getattr(conversation, "messages", [])[-8:]):
            if self._is_runtime_guidance_message(message):
                continue
            if getattr(message, "role", "") != "user":
                continue
            previous_content = str(getattr(message, "content", "") or "")
            if previous_content.strip() == content.strip():
                continue
            if self._has_no_write_instruction(previous_content):
                return False
            if self._looks_like_code_change_request(previous_content) or self._user_requests_code_change(previous_content, "coding"):
                return True
        return False

    def _has_successful_write(self, tool_events: list[dict[str, Any]]) -> bool:
        return any(
            self._is_write_tool(str(event.get("tool") or "")) and event.get("status") == "success"
            for event in tool_events
        )

    def _has_successful_verification(self, tool_events: list[dict[str, Any]], mode: str | None) -> bool:
        return any(
            self._is_verification_tool(str(event.get("tool") or ""), mode) and event.get("status") == "success"
            for event in tool_events
        )

    def _is_recoverable_write_failure(self, tool_id: str, event: dict[str, Any]) -> bool:
        if tool_id not in {"code.edit_file", "code.replace_text", "filesystem.write_file"}:
            return False
        if event.get("status") == "success":
            return False
        error = str(event.get("error") or "").lower()
        return any(
            marker in error
            for marker in (
                "old_text not found",
                "old_text matches",
                "path is required",
                "content is required",
                "missing required",
                "path not found",
                "no such file",
                "not found in file",
                "multiple matches",
            )
        )

    def _write_repair_prompt(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        event: dict[str, Any],
        workspace_path: str,
        force_full_file_rewrite: bool = False,
    ) -> str:
        target = arguments.get("path") or arguments.get("output_path") or workspace_path
        error = str(event.get("error") or "")
        missing_path_rule = ""
        if "path is required" in error.lower():
            missing_path_rule = (
                "\n本次失败是因为写入工具缺少 path 参数。下一轮必须先确定要写入的文件路径，"
                "然后调用 filesystem.write_file 时同时提供 path 和 content。"
                "如果是修改已有文件，优先读取目标文件后用 code.edit_file 或 code.replace_text；"
                "如果是创建新文件，path 必须是当前项目内的明确相对路径或绝对路径。"
            )
        full_rewrite_rule = ""
        if force_full_file_rewrite:
            full_rewrite_rule = (
                "\n系统已检测到精确编辑连续失败。下一轮不要再调用 code.edit_file。"
                "请先用 filesystem.read_file 读取目标文件当前内容，然后调用 filesystem.write_file 写回完整文件内容。"
                "写回内容必须基于刚读取到的真实文件，只修改用户要求的部分。"
            )
        return (
            "写入修复模式：刚才的写入工具调用失败，不能用文字声称已经修改完成。\n"
            f"当前项目目录：{workspace_path}\n"
            f"失败工具：{tool_id}\n"
            f"目标路径：{target}\n"
            f"失败原因：{error}\n"
            "下一步请只做必要的修复：\n"
            "1. 如果是 old_text 未匹配或不唯一，先用 filesystem.read_file 读取目标文件相关片段；\n"
            "2. 基于实际文件内容重新调用 code.edit_file 或 code.replace_text；\n"
            "3. 如果目标文件结构变化太大，允许使用 filesystem.write_file 写回完整文件，但必须基于刚读取到的真实内容；\n"
            "4. 写入成功后再进入验证，不要继续泛泛搜索。"
            f"{missing_path_rule}"
            f"{full_rewrite_rule}"
        )

    async def _auto_read_failed_target(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        workspace_path: str,
    ) -> str:
        """edit_file 失败后，自动读取目标文件的相关片段，返回文件内容片段供模型使用。"""
        from pathlib import Path
        target = arguments.get("path") or arguments.get("output_path") or ""
        if not target:
            return ""
        try:
            access_scope = self.runtime.settings.get_access_scope()
            guard = self.runtime.runner.path_guard.scoped(
                workspace_path,
                allow_all=access_scope == "full_local",
            )
            target_path = guard.resolve(target)
            if not target_path.exists() or not target_path.is_file():
                return ""
            text = target_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        
        # 尝试定位失败的 old_text 周边内容
        old_text = ""
        edits = arguments.get("edits")
        if isinstance(edits, list) and edits:
            old_text = (edits[0].get("old_text") or edits[0].get("old_string") or "")
        elif isinstance(arguments.get("old_text"), str):
            old_text = arguments["old_text"]
        elif isinstance(arguments.get("old_string"), str):
            old_text = arguments["old_string"]
        
        lines = text.splitlines()
        total_lines = len(lines)
        
        if old_text:
            # 模糊定位：找 old_text 首行在文件中的大致位置
            first_line = old_text.strip().splitlines()[0].strip() if old_text.strip() else ""
            center_line = 0
            if first_line:
                for i, line in enumerate(lines):
                    if first_line in line:
                        center_line = i
                        break
            # 取前后 30 行上下文，返回纯文本（不带行号），避免模型把行号写进 old_text
            start = max(0, center_line - 30)
            end = min(total_lines, center_line + 30)
            snippet = "\n".join(lines[start:end])
            return f"文件：{target_path.name}（第 {start+1}-{end} 行，共 {total_lines} 行，以下为不含行号的原始文本）\n{snippet}"
        
        # 没有 old_text，返回文件前 60 行纯文本
        end = min(total_lines, 60)
        snippet = "\n".join(lines[:end])
        suffix = f"\n... (剩余 {total_lines - end} 行省略)" if total_lines > end else ""
        return f"文件：{target_path.name}（共 {total_lines} 行，以下为不含行号的原始文本）\n{snippet}{suffix}"

    def _interrupt_execution_plan(self, execution_plan: dict[str, Any]) -> None:
        steps = execution_plan.get("steps")
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("status") == "running":
                step["status"] = "pending"
                note = str(step.get("note") or "").strip()
                step["note"] = f"{note}；收到插话后待重新审视".strip("；")
                break

    def _runtime_intervention_prompt(
        self,
        workspace_path: str,
        current_stage: str,
        tool_events: list[dict[str, Any]],
        execution_plan: dict[str, Any] | None,
    ) -> str:
        recent_tools = []
        for event in tool_events[-8:]:
            tool = str(event.get("tool") or "")
            status = str(event.get("status") or "")
            if tool:
                recent_tools.append(f"{tool}:{status}")
        plan_hint = ""
        if execution_plan:
            plan_hint = (
                "当前计划已被标记为需要重新审视。不要机械继续旧计划；"
                "如果插话改变目标、约束、文件范围或发现原路线错误，请调整下一步。"
            )
        return (
            "运行中干预：用户在任务执行过程中追加了新信息或纠偏要求。\n"
            f"当前项目目录：{workspace_path}\n"
            f"当前阶段：{current_stage or '未锁定阶段'}\n"
            f"最近工具事件：{', '.join(recent_tools) if recent_tools else '暂无'}\n"
            f"{plan_hint}\n"
            "处理规则：\n"
            "1. 最新插话优先于此前计划、此前推理和此前未完成输出；\n"
            "2. 先重新判断用户真实意图：这是补充信息、纠正方向、要求停止某动作，还是新增约束；\n"
            "3. 如果插话与旧方案冲突，放弃旧方案中冲突部分，不要继续沿旧思路执行；\n"
            "4. 如果已有工具结果仍有用，可以复用；如果不足，请只读取最小必要上下文；\n"
            "5. 下一步必须基于插话重新选择：继续、调整计划、补读证据、写入、验证或停止说明原因。\n"
            "不要把插话当作普通聊天补丁，也不要忽略它继续执行旧路径。"
        )

    def _pop_runtime_guidance(self, conversation_id: str) -> tuple[str, str]:
        guidance_items = _runtime_guidance.pop(conversation_id, [])
        if not guidance_items:
            return "", ""
        guidance_text = "\n".join(f"- {item}" for item in guidance_items[-5:])
        return (
            "【运行中插话 / 干预】用户追加了新的信息或纠偏要求。"
            "请暂停沿用旧思路，重新审视当前任务后再继续：\n"
            f"{guidance_text}",
            guidance_text,
        )

    def _verifier_retry_prompt(self, mode: str | None, workspace_path: str) -> str:
        if mode in {"document", "paper"}:
            return (
                "验证阶段必须执行一次真实验证工具调用，不能只用文字说明已经验证。\n"
                f"当前项目目录：{workspace_path}\n"
                "请优先验证刚生成/修改的文件：可使用 filesystem.scan_folder 确认文件存在，"
                "对 .md/.txt 使用 filesystem.read_file，对 .docx 使用 document.extract_docx_outline，"
                "对 .pdf 使用 document.extract_pdf_text_preview。验证后再进入总结。"
            )
        return (
            "验证阶段必须执行一次真实验证工具调用，不能只用文字说明已经验证。\n"
            f"当前项目目录：{workspace_path}\n"
            "请调用 shell.run_command、git.status 或 git.diff 中的一个工具，确认本轮变更结果后再总结。"
        )

    def _tool_contract_correction_prompt(self, workspace_path: str, write_only: bool = False) -> str:
        if write_only:
            return (
                f"执行契约（压力模式）：项目={workspace_path}。"
                "读取最小上下文后立即调用 code.edit_file / code.replace_text / filesystem.write_file，"
                "或说明缺少什么导致无法修改。不要用文字声称已修改。"
            )
        return (
            f"执行契约：项目={workspace_path}。你未成功调用写入工具。"
            "请先用 filesystem.read_file 定位代码，再调用 code.edit_file / code.replace_text / filesystem.write_file。"
            "无法修改时必须说明原因。"
        )

    def _read_only_task_prompt(self, workspace_path: str) -> str:
        return (
            f"只读模式。项目={workspace_path}。"
            "严禁修改/创建/删除文件或运行改变状态的命令。可用扫描/搜索/读取/git status/diff 收集证据。"
            "回答给出事实、问题判断和建议；不要声称已修改。"
        )

    def _analysis_first_task_prompt(self, workspace_path: str) -> str:
        return (
            f"分析优先任务。项目={workspace_path}。"
            "先用工具定位事实；若确需修改可直接调用写入工具。"
            "高风险操作（大范围覆盖/提交/删除）请先说明风险；普通编辑可按需推进并验证。"
        )

    def _post_write_prompt(self, workspace_path: str) -> str:
        return (
            f"已有写入成功。项目={workspace_path}。"
            "继续写入剩余文件，或调用验证工具（shell.run_command/git.diff/git.status）后总结。"
            "最终回复须列出变更文件、验证情况和剩余风险。"
        )

    def _final_answer_prompt(self, workspace_path: str) -> str:
        return (
            f"收束阶段：不再调用工具。项目={workspace_path}。"
            "简洁总结：1.变更文件 2.验证结果 3.剩余风险。"
        )

    def _user_requests_code_change(self, content: str, mode: str | None) -> bool:
        if mode != "coding":
            return False
        if self._has_no_write_instruction(content):
            return False
        text = content.lower()
        inquiry_terms = ("建议", "分析", "解释", "为什么", "是否", "方案", "思路", "怎么", "如何", "检查", "查看")
        direct_write_terms = (
            "帮我改",
            "帮我修",
            "帮我加",
            "帮我删",
            "开始做",
            "直接改",
            "修复",
            "改成",
            "改造",
            "改造成",
            "改为",
            "替换",
            "新增",
            "添加",
            "添加路由",
            "删除",
            "移除",
            "去掉",
            "实现",
            "创建页面",
            "创建逻辑",
            "独立页面",
            "修改导航",
            "接入",
            "更新",
            "调整",
            "重构",
            "补上",
            "写入",
            "生成",
            "变更",
            "恢复",
            "回退",
            "太大",
            "太小",
            "没反应",
            "加载不出来",
            "优化网站",
            "优化页面",
            "优化其他页",
            "继续优化",
            "创建robots",
            "生成robots",
            "创建sitemap",
            "生成sitemap",
            "添加meta",
            "补充meta",
        )
        broad_write_terms = ("修改", "改", "修", "加", "删")
        if self._has_explicit_write_instruction(content) or any(term in text for term in direct_write_terms):
            return True
        if any(term in text for term in inquiry_terms):
            return False
        code_context_terms = (
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".vue",
            ".html",
            ".css",
            ".json",
            "代码",
            "文件",
            "函数",
            "组件",
            "页面",
            "前端",
            "后端",
            "样式",
            "布局",
            "按钮",
            "ui",
            "端口",
            "配置",
            "接口",
            "路由",
            "seo",
            "网站",
            "网页",
            "meta",
            "robots.txt",
            "sitemap.xml",
            "canonical",
            "open graph",
            "twitter card",
        )
        return any(term in text for term in broad_write_terms) and any(
            term in text for term in code_context_terms
        )

    def _max_rounds_message(self, max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
        lines = [
            f"本轮已达到工具调用上限（{max_rounds} 轮），系统已停止继续执行，避免陷入重复调用。",
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
            "建议：如果这是代码或界面修改任务，请直接说明要修改的文件、关键词或期望结果；系统会继续自动识别任务类型并调用合适工具。",
        ])
        return "\n".join(lines)

    def _max_rounds_after_write_message(self, max_rounds: int, tool_events: list[dict[str, Any]]) -> str:
        paths: list[str] = []
        for event in tool_events:
            if not self._is_write_tool(str(event.get("tool") or "")) or event.get("status") != "success":
                continue
            event_input = event.get("input")
            if isinstance(event_input, dict):
                path = event_input.get("path")
                if path:
                    paths.append(str(path))
        unique_paths = list(dict.fromkeys(paths))
        lines = [
            f"本轮已有写入工具成功执行，但后续工具调用达到上限（{max_rounds} 轮），系统已停止继续执行。",
            "本轮变更是否完整请以上方工具记录和变更清单为准。",
        ]
        if unique_paths:
            lines.append("")
            lines.append("已成功写入的文件：")
            lines.extend(f"- {path}" for path in unique_paths[-8:])
        lines.append("")
        lines.append("建议：如结果不完整，请基于这些已写入文件继续下一轮，系统会避免重复搜索并优先收束。")
        return "\n".join(lines)

    def _build_execution_notice(
        self,
        mode: str | None,
        assistant_content: str,
        tool_events: list[dict[str, Any]],
        *,
        requires_code_write: bool = False,
        contract_failed: bool = False,
        max_rounds_exceeded: bool = False,
    ) -> dict[str, Any] | None:
        if mode not in {"coding", "terminal"}:
            return None

        write_tools = {"code.edit_file", "code.replace_text", "filesystem.write_file"}
        write_successes = [
            event for event in tool_events
            if event.get("tool") in write_tools and event.get("status") == "success"
        ]
        write_failures = [
            event for event in tool_events
            if event.get("tool") in write_tools and event.get("status") == "failure"
        ]
        if write_successes:
            return None

        claims_change = self._assistant_claims_code_changed(assistant_content)
        if not claims_change and not write_failures and not requires_code_write:
            return None

        failed_tools = [
            {
                "tool": event.get("tool") or "",
                "name": event.get("name") or event.get("tool") or "",
                "path": ((event.get("input") or {}).get("path") if isinstance(event.get("input"), dict) else "") or "",
                "error": event.get("error") or "",
                "task_id": event.get("task_id") or "",
            }
            for event in write_failures
        ]
        if max_rounds_exceeded:
            message = "注意：本轮工具调用达到上限，系统已停止继续执行并保存了诊断信息。实际文件是否变更请以工具调用和变更清单为准。"
            reason = "max_tool_rounds"
        elif contract_failed:
            message = "注意：本轮模型没有成功调用本地写入工具，系统已判定代码变更未执行。"
            reason = "tool_contract_failed"
        elif write_failures:
            message = "注意：本轮代码写入工具执行失败，实际文件可能没有变更。请展开上方工具调用查看失败原因。"
            reason = "write_tool_failed"
        elif tool_events:
            message = "注意：本轮没有成功执行任何代码写入工具，因此不能确认实际文件已经变更。"
            reason = "no_successful_write_tool"
        else:
            message = "注意：本轮没有任何本地工具调用记录，因此实际代码没有被修改。"
            reason = "no_tool_calls"

        return {
            "reason": reason,
            "message": message,
            "failed_tools": failed_tools[:8],
            "tool_event_count": len(tool_events),
        }

    def _assistant_claims_code_changed(self, content: str) -> bool:
        text = content.lower()
        claim_terms = (
            "已修改",
            "已经修改",
            "修改完成",
            "已修复",
            "修复完成",
            "已经修复",
            "已成功",
            "成功修改",
            "成功修复",
            "已新增",
            "已写入",
            "已经添加",
            "已经改",
            "改为",
            "改成",
        )
        code_terms = (
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".vue",
            ".html",
            ".css",
            ".json",
            "代码",
            "文件",
            "端口",
            "配置",
            "函数",
            "组件",
        )
        return any(term in text for term in claim_terms) and any(term in text for term in code_terms)

    def _compact_tool_payload(self, payload: dict[str, Any], limit: int = 40000) -> str:
        text = json.dumps(self._summarize_tool_payload(payload), ensure_ascii=False)
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... 工具结果过长，已截断 ..."

    def _summarize_tool_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool_id = str(payload.get("tool") or "")
        output = payload.get("output")
        if not isinstance(output, dict):
            return payload

        compacted = dict(payload)
        if tool_id == "filesystem.scan_folder":
            compacted["output"] = {
                "root": output.get("root"),
                "folder_count": output.get("folder_count"),
                "file_count": output.get("file_count"),
                "folders": (output.get("folders") or [])[:120],
                "files": (output.get("files") or [])[:260],
                "truncated_for_context": True,
            }
        elif tool_id == "code.list_project_files":
            compacted["output"] = {
                "root": output.get("root"),
                "file_count": output.get("file_count"),
                "truncated": output.get("truncated"),
                "files": (output.get("files") or [])[:500],
                "truncated_for_context": True,
            }
        elif tool_id == "code.search_text":
            compacted["output"] = {
                "root": output.get("root"),
                "query": output.get("query"),
                "match_count": output.get("match_count"),
                "truncated": output.get("truncated"),
                "matches": (output.get("matches") or [])[:80],
                "truncated_for_context": True,
            }
        elif tool_id in {"filesystem.read_file", "filesystem.read_text_preview"}:
            key = "content" if "content" in output else "text"
            text = str(output.get(key) or "")
            max_chars = 50000
            compact_output = {
                key: text[:max_chars],
                "path": output.get("path"),
                "size": output.get("size"),
                "total_lines": output.get("total_lines"),
                "start_line": output.get("start_line"),
                "end_line": output.get("end_line"),
                "encoding": output.get("encoding"),
                "truncated": output.get("truncated") or len(text) > max_chars,
                "remaining_lines": output.get("remaining_lines"),
                "next_start_line": output.get("next_start_line"),
                "next_end_line": output.get("next_end_line"),
                "suggested_next_call": output.get("suggested_next_call"),
                "truncated_for_context": len(text) > max_chars,
                "raw_content": str(output.get("raw_content") or "")[:max_chars],
                "usage_hint": output.get("usage_hint"),
            }
            if len(text) > max_chars:
                compact_output[key] += "\n... 文件内容过长，已压缩；如需更多内容，请按行号范围读取 ..."
                raw_text = str(output.get("raw_content") or "")
                if len(raw_text) > max_chars:
                    compact_output["raw_content"] = raw_text[:max_chars] + "\n... raw_content 同样已截断 ..."
            compacted["output"] = compact_output
        elif tool_id == "shell.run_command":
            compacted["output"] = {
                **output,
                "stdout": str(output.get("stdout") or "")[:20000],
                "stderr": str(output.get("stderr") or "")[:12000],
                "truncated_for_context": True,
            }
        elif tool_id.startswith("web."):
            compacted["output"] = {
                **output,
                "text": str(output.get("text") or "")[:50000],
                "html_preview": str(output.get("html_preview") or "")[:15000],
                "links": (output.get("links") or [])[:80],
                "truncated_for_context": True,
            }
        return compacted

    def write_event(self, payload: dict[str, Any]) -> None:
        self._record_run_event(payload)
        self.write_json_line(payload)

    def _record_run_event(self, payload: dict[str, Any]) -> None:
        run_id = getattr(self, "_active_run_id", "")
        if not run_id or not hasattr(self.runtime, "run_events"):
            return
        self.runtime.run_events.emit(run_id, payload)

    def write_json_line(self, payload: dict[str, Any]) -> None:
        if getattr(self, "_client_stream_closed", False):
            return
        try:
            self.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except (tornado.iostream.StreamClosedError, RuntimeError):
            self._client_stream_closed = True


class ConversationCompressHandler(ApiHandler):
    """POST /conversations/{id}/compress — manually trigger context compression."""

    async def post(self, conversation_id: str) -> None:
        conversation = self.runtime.conversations.get(conversation_id)
        if not conversation:
            raise tornado.web.HTTPError(404, reason="conversation not found")

        workspace = self.runtime.workspaces.get(conversation.workspace_id)
        if not workspace:
            raise tornado.web.HTTPError(404, reason="workspace not found")

        model = self.runtime.settings.get_default_model()
        mode_config = get_mode_config(getattr(conversation, "mode", None), self.get_lang())
        system_prompt = build_system_prompt(
            settings=self.runtime.settings,
            mode_config=mode_config,
            workspace_path=workspace.path,
        )

        # Build the full message list
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        for item in conversation.messages:
            role = "assistant" if item.role == "assistant" else "user"
            messages.append({"role": role, "content": item.content})

        before_tokens = count_messages_tokens(messages)

        # Force compression by temporarily lowering the usable limit
        from runtime.context_manager import (
            compress_context as _compress,
            RECENT_MESSAGES_KEEP,
        )
        compressed, summary_meta = await _compress(
            messages, model, self.runtime.settings, conversation=conversation,
        )

        # If no automatic compression happened (below limit), force it anyway
        if not summary_meta:
            # Force: treat current total as over-limit
            from runtime.context_manager import _generate_summary
            non_system = messages[1:]
            keep = min(RECENT_MESSAGES_KEEP, len(non_system))
            older = non_system[:-keep] if keep < len(non_system) else []
            recent = non_system[-keep:] if keep else non_system
            if older:
                cached = (conversation.metadata or {}).get("context_summary", "")
                summary_text = await _generate_summary(older, model, self.runtime.settings, cached)
                summary_meta = {
                    "context_summary": summary_text,
                    "summary_up_to_index": len(older),
                    "summary_token_count": count_messages_tokens(
                        [{"role": "system", "content": summary_text}]
                    ),
                }

        if summary_meta:
            conv_meta = conversation.metadata or {}
            conv_meta.update(summary_meta)
            conversation.metadata = conv_meta
            self.runtime.conversations._save()

        after_tokens = count_messages_tokens(compressed) if summary_meta else before_tokens

        self.finish_json({
            "success": True,
            "data": {
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "compressed": bool(summary_meta),
                "context_limit": get_context_limit(model, self.runtime.settings),
                "summary_token_count": (summary_meta or {}).get("summary_token_count", 0),
            },
        })


class ConversationConfirmHandler(ApiHandler):
    """POST /conversations/{id}/confirm — 用户确认继续或取消任务"""

    def post(self, conversation_id: str) -> None:
        payload = self.parse_json_body()
        action = payload.get("action", "continue")  # "continue" or "cancel"
        _confirm_responses[conversation_id] = action
        event = _pending_confirms.get(conversation_id)
        if event:
            event.set()
            self.finish_json({"success": True, "action": action})
        else:
            self.finish_json({"success": False, "error": "无待确认任务"})
