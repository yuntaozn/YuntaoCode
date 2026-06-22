from __future__ import annotations

import asyncio
import json
import locale
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
from typing import Any

from .core.cli_provider import (
    CLI_PROVIDER_STORE_SCHEMA_VERSION,
    cli_tool_registry_id,
    current_platform_name,
    normalize_cli_provider,
)
from .tool_registry import ToolRegistry, ToolSpec


MAX_STDOUT = 50_000
MAX_STDERR = 10_000
PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_WIN_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


class CliProviderManager:
    """Registers declarative CLI providers as normal ToolRegistry tools."""

    def __init__(self, path: Path, *, registry: ToolRegistry) -> None:
        self.path = path
        self.registry = registry
        self._providers = self._load()
        self._tool_configs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self._register_all()

    def list_public(self) -> list[dict[str, Any]]:
        return [self._public_provider(provider) for provider in self._providers.values()]

    def get_public(self, provider_id: str) -> dict[str, Any]:
        return self._public_provider(self.get_config(provider_id))

    def get_config(self, provider_id: str) -> dict[str, Any]:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"CLI provider not found: {provider_id}") from exc

    def upsert(self, value: dict[str, Any], *, provider_id: str | None = None) -> dict[str, Any]:
        candidate = dict(value)
        if provider_id:
            candidate["id"] = provider_id
        existing = self._providers.get(str(candidate.get("id") or ""))
        provider = normalize_cli_provider(candidate, existing=existing)
        self._unregister_provider(provider["id"])
        self._providers[provider["id"]] = provider
        self._register_provider(provider)
        self._save()
        return self._public_provider(provider)

    def delete(self, provider_id: str) -> None:
        self.get_config(provider_id)
        self._unregister_provider(provider_id)
        self._providers.pop(provider_id, None)
        self._save()

    def is_tool_available(self, tool_id: str, *, source_id: str = "") -> bool:
        item = self._tool_configs.get(str(tool_id or ""))
        if not item:
            return False
        provider, tool = item
        if source_id and provider["id"] != source_id:
            return False
        ok, _message = self._tool_availability(provider, tool)
        return ok

    def tool_runtime_metadata(self, tool_id: str, *, source_id: str = "") -> dict[str, Any]:
        item = self._tool_configs.get(str(tool_id or ""))
        if not item:
            return {}
        provider, tool = item
        if source_id and provider["id"] != source_id:
            return {}
        ok, message = self._tool_availability(provider, tool)
        if ok:
            return {"tool_health": "available"}
        return {
            "tool_health": "unavailable",
            "tool_last_error": message,
        }

    def capability_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for provider, tool in self._tool_configs.values():
            ok, message = self._tool_availability(provider, tool)
            if ok:
                continue
            issues.append({
                "code": "cli_provider_unavailable",
                "source_type": "cli",
                "source_id": provider["id"],
                "capability_id": tool["capability"],
                "tool_id": tool["registry_id"],
                "name": provider["name"],
                "message": message,
                "recommended_action": "configure",
            })
        return issues

    def _register_all(self) -> None:
        for provider in list(self._providers.values()):
            self._register_provider(provider)

    def _register_provider(self, provider: dict[str, Any]) -> None:
        provider_id = provider["id"]
        self._unregister_provider(provider_id)
        if not provider.get("enabled", True):
            return
        namespace = f"cli_{_normalize_namespace(provider_id)}"
        self.registry.set_provider_metadata(
            namespace,
            source_type="cli",
            source_id=provider_id,
            provider_kind="cli",
            display_name=str(provider.get("name") or provider_id),
            lifecycle="subprocess",
        )
        for tool in provider.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            registry_id = str(tool.get("registry_id") or cli_tool_registry_id(provider_id, tool.get("id") or "run"))

            async def handler(
                input_data: dict[str, Any],
                context: Any,
                *,
                _provider: dict[str, Any] = provider,
                _tool: dict[str, Any] = tool,
            ) -> dict[str, Any]:
                return await self._run_cli_tool(_provider, _tool, input_data, context)

            self.registry.register(
                ToolSpec(
                    id=registry_id,
                    name=str(tool.get("name") or registry_id),
                    description=_tool_description(provider, tool),
                    input_schema=dict(tool.get("input_schema") or {"type": "object"}),
                    requires_confirmation=bool(tool.get("requires_confirmation")),
                    local_only=bool(tool.get("local_only", True)),
                    capability=str(tool.get("capability") or f"cli.{provider_id}"),
                    artifacts=list(tool.get("artifacts") or []),
                    effects=list(tool.get("effects") or []),
                    roles=list(tool.get("roles") or []),
                    verification_strength=str(tool.get("verification_strength") or "") or None,
                    long_running=int(tool.get("timeout") or 0) > 120,
                    retry_safe=bool(tool.get("retry_safe")),
                    idempotent=bool(tool.get("idempotent")),
                ),
                handler,
            )
            self._tool_configs[registry_id] = (provider, tool)

    def _unregister_provider(self, provider_id: str) -> None:
        self.registry.unregister_source(source_type="cli", source_id=provider_id)
        for tool_id, (provider, _tool) in list(self._tool_configs.items()):
            if provider.get("id") == provider_id:
                self._tool_configs.pop(tool_id, None)

    async def _run_cli_tool(
        self,
        provider: dict[str, Any],
        tool: dict[str, Any],
        input_data: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        ok, availability_message = self._tool_availability(provider, tool)
        if not ok:
            return _error_output(provider, tool, availability_message)

        values = _render_values(tool, input_data, context)
        command = str(tool["command"])
        args = [_render_text(str(item), values) for item in tool.get("args") or []]
        cwd = _resolve_cwd(str(tool.get("cwd") or "workspace"), values, context)
        env = os.environ.copy()
        env.update({
            str(key): _render_text(str(value), values)
            for key, value in (tool.get("env") or {}).items()
        })
        timeout = int(tool.get("timeout") or 60)
        display_command = _compose_display_command(command, args)
        output_paths = _declared_output_paths(tool, values, context)

        if _should_backup_outputs(tool):
            backup_file = getattr(context, "backup_file", None)
            if callable(backup_file):
                for path in output_paths:
                    backup_file(path)

        context.log(
            "info",
            f"running CLI provider: {display_command[:200]}",
            {
                "provider_id": provider["id"],
                "tool_id": tool["registry_id"],
                "cwd": str(cwd),
                "timeout": timeout,
            },
        )

        stdout_bytes = b""
        stderr_bytes = b""
        timed_out = False
        exit_code = 1
        try:
            process_kwargs: dict[str, Any] = {}
            if sys.platform.startswith("win"):
                process_kwargs["creationflags"] = _WIN_NO_WINDOW
            else:
                process_kwargs["start_new_session"] = True
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
                **process_kwargs,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                timed_out = True
                await _kill_process_tree(process)
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=5)
                except asyncio.TimeoutError:
                    stderr_bytes += f"\nCLI provider timed out after {timeout}s".encode("utf-8")
            exit_code = int(process.returncode or 0)
        except OSError as exc:
            return _error_output(provider, tool, f"failed to execute CLI provider command: {exc}")

        stdout = _decode_output(stdout_bytes)[:MAX_STDOUT]
        stderr = _decode_output(stderr_bytes)[:MAX_STDERR]
        evidence = _evaluate_evidence(tool, values, context, exit_code=exit_code, stdout=stdout, stderr=stderr)
        required_evidence_failed = any(not item["ok"] and item.get("required", True) for item in evidence)
        failed = bool(timed_out or exit_code != 0 or required_evidence_failed)
        paths = sorted({str(path) for path in output_paths})

        context.log(
            "error" if failed else "info",
            f"CLI provider finished with exit code {exit_code}",
            {"timed_out": timed_out, "evidence_ok": not required_evidence_failed},
        )

        result: dict[str, Any] = {
            "provider_kind": "cli",
            "provider_id": provider["id"],
            "tool_id": tool["registry_id"],
            "capability": tool["capability"],
            "command": display_command,
            "executable": command,
            "args": args,
            "cwd": str(cwd),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": timed_out,
            "timeout": timeout,
            "stdout_truncated": len(stdout_bytes) > MAX_STDOUT,
            "stderr_truncated": len(stderr_bytes) > MAX_STDERR,
            "evidence": evidence,
            "effects": list(tool.get("effects") or []),
            "artifacts": list(tool.get("artifacts") or []),
            "roles": list(tool.get("roles") or []),
            "verification_strength": str(tool.get("verification_strength") or ""),
            "paths": paths,
        }
        if paths:
            result["path"] = paths[0]
        if failed:
            result["error"] = True
            result["message"] = _cli_failure_message(exit_code, timed_out, evidence)
        return result

    def _tool_availability(self, provider: dict[str, Any], tool: dict[str, Any]) -> tuple[bool, str]:
        if not bool(provider.get("enabled", True)):
            return False, f"CLI provider is disabled: {provider.get('id')}"
        platform = current_platform_name()
        if platform not in set(tool.get("platforms") or []):
            return False, f"CLI provider tool is not supported on this platform: {platform}"
        command = str(tool.get("command") or "").strip()
        if not command:
            return False, "CLI provider command is missing"
        if _command_exists(command):
            return True, ""
        return False, f"CLI provider command is not available: {command}"

    def _public_provider(self, provider: dict[str, Any]) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        for tool in provider.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            ok, message = self._tool_availability(provider, tool)
            tools.append({
                "id": tool.get("id"),
                "registry_id": tool.get("registry_id"),
                "name": tool.get("name"),
                "description": tool.get("description"),
                "capability": tool.get("capability"),
                "input_schema": tool.get("input_schema"),
                "artifacts": tool.get("artifacts"),
                "effects": tool.get("effects"),
                "roles": tool.get("roles"),
                "verification_strength": tool.get("verification_strength"),
                "requires_confirmation": tool.get("requires_confirmation"),
                "timeout": tool.get("timeout"),
                "available": ok,
                "availability_message": message,
            })
        return {
            "schema_version": provider.get("schema_version"),
            "id": provider.get("id"),
            "name": provider.get("name"),
            "description": provider.get("description"),
            "enabled": bool(provider.get("enabled", True)),
            "provider_kind": "cli",
            "source_type": "cli",
            "tools": tools,
        }

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        values = payload.get("providers") if isinstance(payload, dict) else []
        providers: dict[str, dict[str, Any]] = {}
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                continue
            try:
                provider = normalize_cli_provider(value)
            except ValueError:
                continue
            providers[provider["id"]] = provider
        return providers

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CLI_PROVIDER_STORE_SCHEMA_VERSION,
            "providers": list(self._providers.values()),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _tool_description(provider: dict[str, Any], tool: dict[str, Any]) -> str:
    description = str(tool.get("description") or "").strip()
    prefix = f"CLI provider '{provider.get('name') or provider.get('id')}'. "
    if description:
        return prefix + description
    return prefix + "Runs a declared local command with structured inputs and evidence."


def _render_values(tool: dict[str, Any], input_data: dict[str, Any], context: Any) -> dict[str, str]:
    values: dict[str, str] = {
        "workspace": str(context.path_guard.workspace_roots[0]),
        "task_temp": str(getattr(context, "temp_dir", "") or ""),
    }
    path_inputs = {
        item["name"]: item
        for item in tool.get("inputs") or []
        if item.get("kind") in {"path", "file", "directory"} or item.get("access")
    }
    for key, value in input_data.items():
        if key in path_inputs and value not in (None, ""):
            values[key] = str(_resolve_runtime_path(str(value), context))
        else:
            values[key] = str(value)
    return values


def _render_text(template: str, values: dict[str, str]) -> str:
    def replace(match: Any) -> str:
        key = str(match.group(1))
        if key not in values:
            raise ValueError(f"missing CLI provider input for placeholder: {key}")
        return values[key]

    return PLACEHOLDER_PATTERN.sub(replace, template)


def _resolve_cwd(raw: str, values: dict[str, str], context: Any) -> Path:
    text = _render_text(raw, values).strip()
    if text in {"workspace", "{workspace}"}:
        return Path(values["workspace"]).resolve()
    if text in {"task_temp", "{task_temp}"}:
        temp_dir = Path(values["task_temp"]).resolve()
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir
    return _resolve_runtime_path(text, context)


def _resolve_runtime_path(raw_path: str, context: Any) -> Path:
    path = Path(str(raw_path)).expanduser()
    temp_dir = getattr(context, "temp_dir", None)
    if temp_dir is not None and path.is_absolute():
        temp_root = Path(temp_dir).resolve()
        try:
            resolved = path.resolve()
            resolved.relative_to(temp_root)
            return resolved
        except (OSError, ValueError):
            pass
    return context.path_guard.resolve(str(raw_path))


def _declared_output_paths(tool: dict[str, Any], values: dict[str, str], context: Any) -> list[Path]:
    paths: list[Path] = []
    for output in tool.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        rendered = _render_text(str(output.get("path") or ""), values)
        if rendered:
            paths.append(_resolve_runtime_path(rendered, context))
    for evidence in tool.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        if str(evidence.get("type") or "") not in {"file_exists", "file_min_size"}:
            continue
        rendered = _render_text(str(evidence.get("path") or ""), values)
        if rendered:
            paths.append(_resolve_runtime_path(rendered, context))
    return list(dict.fromkeys(paths))


def _evaluate_evidence(
    tool: dict[str, Any],
    values: dict[str, str],
    context: Any,
    *,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for evidence in tool.get("evidence") or []:
        kind = str(evidence.get("type") or "")
        required = bool(evidence.get("required", True))
        result: dict[str, Any] = {"type": kind, "required": required, "ok": False}
        if kind == "exit_code_zero":
            result["ok"] = exit_code == 0
            result["message"] = "exit code is zero" if result["ok"] else f"exit code is {exit_code}"
        elif kind in {"file_exists", "file_min_size"}:
            path = _resolve_runtime_path(_render_text(str(evidence.get("path") or ""), values), context)
            result["path"] = str(path)
            exists = path.exists()
            if kind == "file_exists":
                result["ok"] = exists
                result["message"] = "file exists" if exists else "file does not exist"
            else:
                min_bytes = int(evidence.get("min_bytes") or 1)
                size = path.stat().st_size if exists and path.is_file() else 0
                result["ok"] = bool(exists and size >= min_bytes)
                result["size"] = size
                result["min_bytes"] = min_bytes
                result["message"] = "file size is sufficient" if result["ok"] else "file size is too small"
        elif kind == "stdout_contains":
            text = _render_text(str(evidence.get("text") or ""), values)
            result["ok"] = bool(text and text in stdout)
            result["message"] = "stdout contains expected text" if result["ok"] else "stdout missing expected text"
        elif kind == "stderr_not_contains":
            text = _render_text(str(evidence.get("text") or ""), values)
            result["ok"] = bool(not text or text not in stderr)
            result["message"] = "stderr does not contain forbidden text" if result["ok"] else "stderr contains forbidden text"
        else:
            result["message"] = f"unsupported evidence type: {kind}"
        results.append(result)
    return results


def _should_backup_outputs(tool: dict[str, Any]) -> bool:
    return bool(set(tool.get("effects") or []) & {"file_write", "file_delete", "local_state_change"})


def _error_output(provider: dict[str, Any], tool: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "error": True,
        "message": message,
        "content": message,
        "provider_kind": "cli",
        "provider_id": provider.get("id"),
        "tool_id": tool.get("registry_id"),
        "capability": tool.get("capability"),
        "effects": list(tool.get("effects") or []),
        "artifacts": list(tool.get("artifacts") or []),
        "roles": list(tool.get("roles") or []),
    }


def _cli_failure_message(exit_code: int, timed_out: bool, evidence: list[dict[str, Any]]) -> str:
    if timed_out:
        return "CLI provider command timed out"
    if exit_code != 0:
        return f"CLI provider command exited with code {exit_code}"
    failed = [
        str(item.get("message") or item.get("type") or "evidence failed")
        for item in evidence
        if not item.get("ok") and item.get("required", True)
    ]
    return "; ".join(failed) or "CLI provider evidence failed"


def _command_exists(command: str) -> bool:
    path = Path(command)
    if path.is_absolute() or any(sep in command for sep in ("/", "\\")):
        return path.expanduser().is_file()
    return shutil.which(command) is not None


def _compose_display_command(command: str, args: list[str]) -> str:
    if sys.platform.startswith("win"):
        return " ".join([command, *(_quote_windows_arg(arg) for arg in args)])
    return " ".join([command, *(shlex.quote(arg) for arg in args)])


def _quote_windows_arg(value: Any) -> str:
    text = str(value)
    if not text:
        return "''"
    return "'" + text.replace("'", "''") + "'"


def _decode_output(raw: bytes) -> str:
    encodings = ["utf-8-sig", locale.getpreferredencoding(False), "gbk", "cp936", "utf-16"]
    seen: set[str] = set()
    for encoding in encodings:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if sys.platform.startswith("win"):
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=_WIN_NO_WINDOW,
            )
            await asyncio.wait_for(killer.communicate(), timeout=5)
            return
        except Exception:
            pass
    try:
        if not sys.platform.startswith("win"):
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            return


def _normalize_namespace(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
    return normalized or "provider"
