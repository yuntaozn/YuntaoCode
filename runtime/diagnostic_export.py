"""Portable diagnostic exports for a selected Run.

Diagnostic exports help compare behavior across machines. They are generated on
demand, avoid secrets and file contents, and do not participate in Skill
Evolution replay verification.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from runtime.run_evidence import build_run_evidence
from runtime.version import __version__


DIAGNOSTIC_EXPORT_SCHEMA_VERSION = "diagnostic_export.v1"


def build_diagnostic_export(runtime: Any, run: Any) -> dict[str, Any]:
    evidence = build_run_evidence(run)
    run_info = evidence.get("run") if isinstance(evidence.get("run"), dict) else {}
    run_id = str(run_info.get("id") or getattr(run, "id", "") or "")
    return {
        "schema_version": DIAGNOSTIC_EXPORT_SCHEMA_VERSION,
        "kind": "run_diagnostic_export",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filename": _diagnostic_filename(run_id or run_info.get("goal") or "run"),
        "product": {
            "name": "YuntaoCode",
            "version": __version__,
        },
        "runtime": _runtime_summary(runtime),
        "environment": _environment_summary(),
        "settings": _settings_summary(runtime),
        "tools": _tool_summary(runtime),
        "mcp_services": _mcp_summary(runtime),
        "run": _run_summary(run),
        "run_evidence_summary": _run_evidence_summary(evidence),
        "runbook_summary": _run_evidence_summary(evidence),
        "model_errors": _model_error_summary(getattr(run, "events", []) or []),
        "recent_events": _recent_events(getattr(run, "events", []) or []),
        "export_policy": {
            "manual_export": True,
            "stored_by_runtime": False,
            "remote_submission": False,
            "contains_full_runbook": False,
            "contains_full_event_log": False,
            "contains_file_contents": False,
            "contains_api_keys": False,
        },
        "privacy_note": (
            "Review this diagnostic before sharing. It excludes API keys and "
            "file contents, but goals, paths, hostnames, model IDs, tool errors, "
            "and local environment details may still be private."
        ),
    }


def _runtime_summary(runtime: Any) -> dict[str, Any]:
    config = getattr(runtime, "config", None)
    runner = getattr(runtime, "runner", None)
    path_guard = getattr(runner, "path_guard", None)
    roots = getattr(path_guard, "workspace_roots", []) or []
    return {
        "host": str(getattr(config, "host", "") or ""),
        "port": int(getattr(config, "port", 0) or 0),
        "workspace_root_count": len(roots),
        "workspace_roots": [str(root) for root in roots],
    }


def _environment_summary() -> dict[str, Any]:
    return {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "executables": {
            "git": _command_version("git"),
            "node": _command_version("node"),
            "npm": _command_version("npm"),
        },
    }


def _settings_summary(runtime: Any) -> dict[str, Any]:
    settings = getattr(runtime, "settings", None)
    if not settings:
        return {}
    public = settings.public() if hasattr(settings, "public") else {}
    providers = {}
    for provider_id, provider in (public.get("providers") or {}).items():
        if not isinstance(provider, dict):
            continue
        providers[str(provider_id)] = {
            "id": str(provider.get("id") or provider_id),
            "kind": str(provider.get("kind") or ""),
            "base_url_origin": _url_origin(provider.get("base_url")),
            "chat_path": str(provider.get("chat_path") or ""),
            "api_key_required": bool(provider.get("api_key_required", True)),
            "has_api_key": bool(provider.get("has_api_key", False)),
        }
    return {
        "default_model": str(public.get("default_model") or ""),
        "access_scope": str(public.get("access_scope") or ""),
        "planning_policy": str(public.get("planning_policy") or ""),
        "confirmation_policy": str(public.get("confirmation_policy") or ""),
        "backups": public.get("backups") if isinstance(public.get("backups"), dict) else {},
        "memories": public.get("memories") if isinstance(public.get("memories"), dict) else {},
        "providers": providers,
        "models": [_model_summary(model) for model in public.get("models") or [] if isinstance(model, dict)],
    }


def _tool_summary(runtime: Any) -> dict[str, Any]:
    registry = getattr(runtime, "registry", None)
    settings = getattr(runtime, "settings", None)
    if not registry:
        return {"count": 0, "tools": []}
    tools = []
    for spec in registry.list_specs():
        tool_id = str(spec.get("id") or "")
        enabled = settings.is_tool_enabled(tool_id) if settings and hasattr(settings, "is_tool_enabled") else True
        available = runtime.is_tool_available(spec) if hasattr(runtime, "is_tool_available") else True
        readiness = spec.get("readiness") if isinstance(spec.get("readiness"), dict) else {}
        tools.append({
            "id": tool_id,
            "name": str(spec.get("name") or ""),
            "source_type": str(spec.get("source_type") or "builtin"),
            "source_id": str(spec.get("source_id") or ""),
            "enabled": bool(enabled),
            "available": bool(available),
            "tool_health": str(spec.get("tool_health") or readiness.get("health") or "available"),
            "readiness": {
                "code": str(readiness.get("code") or ""),
                "message": str(readiness.get("message") or ""),
                "details": dict(readiness.get("details") or {})
                if isinstance(readiness.get("details"), dict)
                else {},
            },
            "requires_confirmation": bool(spec.get("requires_confirmation", False)),
            "long_running": bool(spec.get("long_running", False)),
            "retry_safe": bool(spec.get("retry_safe", False)),
            "capability": str(spec.get("capability") or ""),
            "artifacts": list(spec.get("artifacts") or []),
            "effects": list(spec.get("effects") or []),
            "roles": list(spec.get("roles") or []),
            "dependencies": dict(spec.get("dependencies") or {}),
        })
    return {
        "count": len(tools),
        "enabled_count": sum(1 for tool in tools if tool["enabled"]),
        "available_count": sum(1 for tool in tools if tool["available"]),
        "tools": tools,
    }


def _mcp_summary(runtime: Any) -> dict[str, Any]:
    manager = getattr(runtime, "mcp_services", None)
    if not manager or not hasattr(manager, "list_public"):
        return {"count": 0, "services": []}
    services = []
    for service in manager.list_public():
        status = service.get("status") if isinstance(service.get("status"), dict) else {}
        transport = service.get("transport") if isinstance(service.get("transport"), dict) else {}
        logs = status.get("logs") if isinstance(status.get("logs"), list) else []
        services.append({
            "id": str(service.get("id") or ""),
            "name": str(service.get("name") or ""),
            "enabled": bool(service.get("enabled", False)),
            "transport": {
                "type": str(transport.get("type") or ""),
                "command": str(transport.get("command") or ""),
                "cwd": str(transport.get("cwd") or ""),
                "url_origin": _url_origin(transport.get("url")),
                "health_url_origin": _url_origin(transport.get("health_url")),
                "env_keys": list(transport.get("env_keys") or []),
                "header_keys": list(transport.get("header_keys") or []),
            },
            "session": {
                "state": str(status.get("state") or ""),
                "message": _truncate(status.get("message"), 500),
                "protocol_connected": bool(status.get("protocol_connected", False)),
                "protocol_version": str(status.get("protocol_version") or ""),
                "tool_ids": list(status.get("tool_ids") or []),
                "prerequisites": list(status.get("prerequisites") or []),
                "log_count": len(logs),
                "logs_tail": [_truncate(item, 500) for item in logs[-5:]],
            },
        })
    return {"count": len(services), "services": services}


def _run_summary(run: Any) -> dict[str, Any]:
    data = run.to_public_dict(include_events=False) if hasattr(run, "to_public_dict") else {}
    return {
        "id": str(data.get("id") or getattr(run, "id", "") or ""),
        "task_id": str(data.get("task_id") or getattr(run, "task_id", "") or ""),
        "conversation_id": str(data.get("conversation_id") or getattr(run, "conversation_id", "") or ""),
        "workspace_id": str(data.get("workspace_id") or getattr(run, "workspace_id", "") or ""),
        "mode": str(data.get("mode") or getattr(run, "mode", "") or ""),
        "status": str(data.get("status") or getattr(run, "status", "") or ""),
        "stage": str(data.get("stage") or getattr(run, "stage", "") or ""),
        "message": _truncate(data.get("message") or getattr(run, "message", ""), 500),
        "goal_preview": _truncate(data.get("user_content") or getattr(run, "user_content", ""), 500),
        "attempt": int(data.get("attempt") or getattr(run, "attempt", 1) or 1),
        "event_count": int(data.get("event_count") or len(getattr(run, "events", []) or [])),
        "created_at": str(data.get("created_at") or getattr(run, "created_at", "") or ""),
        "updated_at": str(data.get("updated_at") or getattr(run, "updated_at", "") or ""),
    }


def _run_evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    result = evidence.get("result") if isinstance(evidence.get("result"), dict) else {}
    tool_steps = evidence.get("tool_steps") if isinstance(evidence.get("tool_steps"), list) else []
    failures = evidence.get("failures") if isinstance(evidence.get("failures"), list) else []
    return {
        "schema_version": str(evidence.get("schema_version") or ""),
        "trace": evidence.get("trace") if isinstance(evidence.get("trace"), dict) else {},
        "context_pack": evidence.get("context_pack") if isinstance(evidence.get("context_pack"), dict) else {},
        "context_packs": list(evidence.get("context_packs") or []),
        "workspace_snapshot": evidence.get("workspace_snapshot") if isinstance(evidence.get("workspace_snapshot"), dict) else {},
        "capability_evidence": evidence.get("capability_evidence") if isinstance(evidence.get("capability_evidence"), dict) else {},
        "task_contract": evidence.get("task_contract") if isinstance(evidence.get("task_contract"), dict) else {},
        "capability_snapshot": evidence.get("capability_snapshot") if isinstance(evidence.get("capability_snapshot"), dict) else {},
        "plan": evidence.get("plan") if isinstance(evidence.get("plan"), dict) else {},
        "result": {
            "status": str(result.get("status") or ""),
            "summary": _truncate(result.get("summary") or result.get("message") or "", 1000),
            "artifact_count": len(result.get("artifacts") or []) if isinstance(result.get("artifacts"), list) else 0,
            "risk_count": len(result.get("risks") or []) if isinstance(result.get("risks"), list) else 0,
        },
        "tool_steps": [_tool_step_summary(step) for step in tool_steps[-50:] if isinstance(step, dict)],
        "failures": [_tool_step_summary(step) for step in failures[-20:] if isinstance(step, dict)],
        "failure_details": [_compact_dict(item) for item in (evidence.get("failure_details") or []) if isinstance(item, dict)],
        "verification_evidence": [
            _compact_dict(item)
            for item in (evidence.get("verification_evidence") or [])
            if isinstance(item, dict)
        ],
        "recovery": evidence.get("recovery") if isinstance(evidence.get("recovery"), dict) else {},
    }


def _recent_events(events: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    compact = []
    for event in events[-limit:]:
        if not isinstance(event, dict):
            continue
        compact.append({
            "event": str(event.get("event") or ""),
            "time": str(event.get("time") or ""),
            "status": str(event.get("status") or ""),
            "stage": str(event.get("stage") or ""),
            "tool": str(event.get("tool") or event.get("name") or ""),
            "task_id": str(event.get("task_id") or ""),
            "message": _truncate(event.get("message"), 500),
            "error": _truncate(event.get("error"), 1000),
            "terminal": event.get("terminal") if "terminal" in event else None,
            "recoverable": event.get("recoverable") if "recoverable" in event else None,
            "input_keys": sorted(str(key) for key in event.get("input", {}).keys())
            if isinstance(event.get("input"), dict) else [],
            "output_keys": sorted(str(key) for key in event.get("output", {}).keys())
            if isinstance(event.get("output"), dict) else [],
        })
    return compact


def _model_error_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [
        event for event in events
        if isinstance(event, dict)
        and event.get("event") == "error"
        and str(event.get("error") or "").strip()
    ]
    if not errors:
        return {"count": 0, "latest": {}}
    latest = errors[-1]
    return {
        "count": len(errors),
        "latest": {
            "time": str(latest.get("time") or ""),
            "error": _truncate(latest.get("error"), 1000),
            "terminal": bool(latest.get("terminal", True)),
            "recoverable": bool(latest.get("recoverable", False)),
        },
    }


def _tool_step_summary(step: dict[str, Any]) -> dict[str, Any]:
    output = step.get("output") if isinstance(step.get("output"), dict) else {}
    return {
        "time": str(step.get("time") or ""),
        "tool": str(step.get("tool") or ""),
        "status": str(step.get("status") or ""),
        "task_id": str(step.get("task_id") or ""),
        "error": _truncate(step.get("error"), 1000),
        "runtime_risks": list(step.get("runtime_risks") or []),
        "input_keys": sorted(str(key) for key in step.get("input", {}).keys())
        if isinstance(step.get("input"), dict) else [],
        "output": _compact_tool_output(output),
    }


def _compact_tool_output(output: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "status",
        "message",
        "error",
        "path",
        "paths",
        "file",
        "files",
        "file_count",
        "artifact",
        "artifacts",
        "artifact_kind",
        "created",
        "draft_id",
        "draft_stats",
        "exit_code",
        "file_size",
        "stdout_tail",
        "stderr_tail",
        "count",
        "content_chars",
        "nonempty_paragraph_count",
        "paragraph_count",
        "stats",
        "summary",
        "text_chars",
        "type",
        "validation",
        "warnings",
    }
    return {
        key: _compact_value(value)
        for key, value in output.items()
        if key in allowed_keys
    }


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _compact_value(item) for key, item in value.items()}


def _compact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate(value, 1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(key): _compact_value(item) for key, item in list(value.items())[:30]}
    return _truncate(str(value), 1000)


def _model_summary(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(model.get("id") or ""),
        "name": str(model.get("name") or ""),
        "provider": str(model.get("provider") or ""),
        "context_limit": model.get("context_limit"),
        "supports_tools": bool(model.get("supports_tools", False)),
        "thinking_mode": str(model.get("thinking_mode") or ""),
    }


def _command_version(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    if not path:
        return {"available": False, "version": ""}
    try:
        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            shell=False,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics should report failures.
        return {"available": True, "version": "", "error": _truncate(str(exc), 300)}
    return {
        "available": True,
        "version": _truncate((completed.stdout or completed.stderr or "").strip().splitlines()[0], 300),
        "exit_code": completed.returncode,
    }


def _url_origin(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _diagnostic_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    text = text[:64] or "run"
    return f"yuntaocode-diagnostic-{text}.json"


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}..."
