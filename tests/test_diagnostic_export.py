from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.diagnostic_export import build_diagnostic_export


class FakeRegistry:
    def list_specs(self) -> list[dict]:
        return [
            {
                "id": "filesystem.read_file",
                "name": "Read File",
                "source_type": "builtin",
                "source_id": "filesystem",
                "requires_confirmation": False,
                "dependencies": {},
                "artifacts": ["text"],
                "effects": ["read"],
                "roles": ["inspection"],
                "available": False,
                "tool_health": "unavailable",
                "readiness": {
                    "code": "runtime_dependency_missing",
                    "message": "A runtime dependency is missing.",
                    "details": {"dependency": "demo"},
                },
            }
        ]


class FakeSettings:
    def public(self) -> dict:
        return {
            "default_model": "demo-model",
            "access_scope": "project_only",
            "planning_policy": "auto",
            "confirmation_policy": "auto",
            "backups": {"enabled": True},
            "memories": {"enabled": False},
            "providers": {
                "demo": {
                    "id": "demo",
                    "kind": "openai",
                    "base_url": "https://example.com/private/path",
                    "chat_path": "/chat/completions",
                    "api_key_required": True,
                    "has_api_key": True,
                    "api_key_hint": "sk-***secret",
                }
            },
            "models": [
                {
                    "id": "demo-model",
                    "name": "Demo Model",
                    "provider": "demo",
                    "context_limit": 1000,
                    "supports_tools": True,
                    "thinking_mode": "demo",
                    "request_options": {"secret_option": "hidden"},
                }
            ],
            "settings_path": r"C:\Users\demo\AppData\Local\YuntaoCode\settings.json",
        }

    def is_tool_enabled(self, tool_id: str) -> bool:
        return tool_id == "filesystem.read_file"


class FakeMcpServices:
    def list_public(self) -> list[dict]:
        return [
            {
                "id": "demo-mcp",
                "name": "Demo MCP",
                "enabled": True,
                "transport": {
                    "type": "stdio",
                    "command": "demo-mcp",
                    "cwd": r"C:\tools\demo",
                    "env_keys": ["SECRET_TOKEN"],
                    "header_keys": [],
                },
                "status": {
                    "state": "connected",
                    "message": "ok",
                    "protocol_connected": True,
                    "protocol_version": "2025-06-18",
                    "tool_ids": ["demo.tool"],
                    "logs": ["started", "connected"],
                },
            }
        ]


def test_diagnostic_export_is_sanitized_and_not_a_fixture(monkeypatch) -> None:
    monkeypatch.setattr(
        "runtime.diagnostic_export._command_version",
        lambda name: {"available": name == "git", "version": f"{name} version"},
    )
    run = SimpleNamespace(
        id="run-1",
        conversation_id="conversation-1",
        workspace_id="workspace-1",
        task_id="task-1",
        parent_run_id="",
        source_run_id="",
        attempt=1,
        resume_from_checkpoint_id="",
        mode="terminal",
        status="failure",
        stage="tool",
        message="tool failed",
        user_content="Diagnose the failed document task",
        created_at="2026-06-13T00:00:00Z",
        updated_at="2026-06-13T00:01:00Z",
        events=[
            {
                "event": "tool",
                "tool": "document.translate_docx",
                "status": "failure",
                "input": {"path": "source.docx"},
                "output": {"error": "timeout", "content": "full file content should not appear"},
                "error": "timeout",
            },
            {
                "event": "tool",
                "tool": "filesystem.finalize_text_file",
                "status": "success",
                "input": {"output_path": "story.txt"},
                "output": {
                    "path": "story.txt",
                    "draft_stats": {"text_chars": 5200, "chunk_count": 2},
                    "validation": {"valid": True, "text_chars": 5200},
                    "content": "generated story content should not appear",
                },
            },
            {
                "event": "error",
                "error": "HTTP 400: invalid provider request",
                "terminal": False,
                "recoverable": True,
            },
            {
                "event": "result",
                "result": {
                    "status": "failure",
                    "summary": "translation timed out",
                    "failure_details": [{"tool": "document.translate_docx", "error": "timeout"}],
                },
            },
        ],
        to_public_dict=lambda include_events=False: {
            "id": "run-1",
            "conversation_id": "conversation-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "mode": "terminal",
            "status": "failure",
            "stage": "tool",
            "message": "tool failed",
            "user_content": "Diagnose the failed document task",
            "attempt": 1,
            "event_count": 2,
        },
    )
    runtime = SimpleNamespace(
        config=SimpleNamespace(host="127.0.0.1", port=8765),
        runner=SimpleNamespace(path_guard=SimpleNamespace(workspace_roots=[r"D:\code\project"])),
        registry=FakeRegistry(),
        settings=FakeSettings(),
        mcp_services=FakeMcpServices(),
        is_tool_available=lambda spec: bool(spec.get("available", True)),
    )

    exported = build_diagnostic_export(runtime, run)
    text = json.dumps(exported, ensure_ascii=False)

    assert exported["schema_version"] == "diagnostic_export.v1"
    assert exported["kind"] == "run_diagnostic_export"
    assert exported["export_policy"]["contains_api_keys"] is False
    assert exported["export_policy"]["contains_full_runbook"] is False
    assert exported["export_policy"]["contains_full_event_log"] is False
    assert "fixture" not in exported
    assert "sk-***secret" not in text
    assert "secret_option" not in text
    assert "full file content should not appear" not in text
    assert "generated story content should not appear" not in text
    assert exported["settings"]["providers"]["demo"]["base_url_origin"] == "https://example.com"
    assert exported["tools"]["count"] == 1
    assert exported["tools"]["available_count"] == 0
    assert exported["tools"]["tools"][0]["tool_health"] == "unavailable"
    assert exported["tools"]["tools"][0]["readiness"]["code"] == "runtime_dependency_missing"
    assert exported["mcp_services"]["services"][0]["session"]["state"] == "connected"
    assert exported["model_errors"]["count"] == 1
    assert exported["model_errors"]["latest"]["recoverable"] is True
    assert exported["run_evidence_summary"]["schema_version"] == "run_evidence.v1"
    assert exported["run_evidence_summary"] == exported["runbook_summary"]
    assert exported["runbook_summary"]["trace"]["schema_version"] == "run_trace_summary.v1"
    assert exported["runbook_summary"]["trace"]["result_status"] == "failure"
    assert exported["runbook_summary"]["capability_evidence"]["schema_version"] == "capability_evidence_summary.v1"
    tool_outputs = exported["runbook_summary"]["tool_steps"]
    finalized = next(item for item in tool_outputs if item["tool"] == "filesystem.finalize_text_file")
    assert finalized["output"]["draft_stats"]["text_chars"] == 5200
    assert finalized["output"]["validation"]["text_chars"] == 5200
    assert exported["recent_events"][2]["terminal"] is False
