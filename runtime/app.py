from __future__ import annotations

import argparse
import json
import secrets
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tornado.ioloop
import tornado.web

from .api.backend import BackendLoginHandler
from .api.automations import AutomationActionHandler, AutomationDetailHandler, AutomationsHandler
from .api.attachments import AttachmentContentHandler, AttachmentDetailHandler, AttachmentsHandler
from .api.capability_packs import (
    CapabilityPackActionHandler,
    CapabilityPackDetailHandler,
    CapabilityPacksHandler,
)
from .api.cli_providers import CliProviderDetailHandler, CliProvidersHandler
from .api.backups import BackupRestoreHandler, BackupsHandler
from .api.conversations import (
    ConversationCompressHandler,
    ConversationConfirmHandler,
    ConversationDetailHandler,
    ConversationGuidanceHandler,
    ConversationMessagesHandler,
    ConversationMessagesStreamHandler,
    ConversationsHandler,
)
from .api.health import HealthHandler
from .api.logs import LogsWebSocketHandler
from .api.memories import MemoriesHandler, MemoryDetailHandler, MemoryPromptHandler
from .api.mcp_services import McpServiceActionHandler, McpServiceDetailHandler, McpServicesHandler
from .api.panel import PanelHandler
from .api.plugins import PluginsHandler
from .api.runs import RunActionHandler, RunDetailHandler, RunEventsStreamHandler, RunsHandler
from .api.settings import SettingsHandler
from .api.tasks import TaskDetailHandler, TasksHandler
from .api.tool_tasks import ToolTaskDetailHandler, ToolTasksHandler
from .api.tools import ToolsHandler
from .api.updates import SourceUpdateHandler
from .api.workspaces import WorkspaceDetailHandler, WorkspaceOpenHandler, WorkspacePickerHandler, WorkspacesHandler
from .config import RuntimeConfig
from .conversation_store import ConversationStore
from .automation_store import AutomationStore
from .automation_scheduler import AutomationScheduler
from .backup_store import BackupStore
from .attachment_store import AttachmentStore
from .capability_pack_store import CapabilityPackStore
from .cli_provider_manager import CliProviderManager
from .context_manager import warm_context_tokenizer
from .security import PathGuard
from .settings_store import SettingsStore
from .skills import CORE_BUILTIN_TOOL_GROUPS, DEFAULT_BUILTIN_TOOL_GROUPS, register_builtin_tools
from .task_runner import TaskRunner
from .task_store import TaskStore
from .tool_registry import ToolRegistry
from .run_store import RunStore
from .run_events import RunEventHub
from .product_task_store import ProductTaskStore
from .mcp_service_manager import McpServiceManager
from .workspace_store import WorkspaceStore


@dataclass(frozen=True)
class RuntimeFeatureSet:
    profile: str
    tool_groups: tuple[str, ...]
    mcp_services: bool = True
    cli_providers: bool = True
    automations: bool = True
    capability_packs: bool = True
    plugins: bool = True
    source_updates: bool = True
    memory_api: bool = True
    backup_api: bool = True

    @classmethod
    def from_profile(cls, profile: str) -> "RuntimeFeatureSet":
        normalized = (profile or "full").strip().lower()
        if normalized == "full":
            return cls(profile="full", tool_groups=DEFAULT_BUILTIN_TOOL_GROUPS)
        if normalized == "lite":
            return cls(
                profile="lite",
                tool_groups=CORE_BUILTIN_TOOL_GROUPS,
                mcp_services=False,
                cli_providers=False,
                automations=False,
                capability_packs=False,
                plugins=False,
                source_updates=False,
            )
        raise ValueError(f"unknown runtime profile: {profile}")

    def public(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "tool_groups": list(self.tool_groups),
            "mcp_services": self.mcp_services,
            "cli_providers": self.cli_providers,
            "automations": self.automations,
            "capability_packs": self.capability_packs,
            "plugins": self.plugins,
            "source_updates": self.source_updates,
            "memory_api": self.memory_api,
            "backup_api": self.backup_api,
        }


@dataclass
class RuntimeState:
    config: RuntimeConfig
    features: RuntimeFeatureSet
    registry: ToolRegistry
    tool_tasks: TaskStore
    product_tasks: ProductTaskStore
    runner: TaskRunner
    workspaces: WorkspaceStore
    conversations: ConversationStore
    settings: SettingsStore
    backups: BackupStore
    runs: RunStore
    run_events: RunEventHub
    mcp_services: McpServiceManager | None
    cli_providers: CliProviderManager | None
    attachments: AttachmentStore
    automations: AutomationStore | None
    automation_scheduler: AutomationScheduler | None
    capability_packs: CapabilityPackStore | None

    def is_tool_available(self, spec: dict[str, Any]) -> bool:
        if not bool(spec.get("available", True)):
            return False
        if spec.get("source_type") != "mcp":
            if spec.get("source_type") == "cli" or spec.get("provider_kind") == "cli":
                if self.cli_providers is None:
                    return False
                return self.cli_providers.is_tool_available(
                    str(spec.get("id") or ""),
                    source_id=str(spec.get("source_id") or ""),
                )
            return True
        if self.mcp_services is None:
            return False
        return self.mcp_services.is_connected(str(spec.get("source_id") or ""))

    def tool_runtime_metadata(self, spec: dict[str, Any]) -> dict[str, Any]:
        if spec.get("source_type") == "cli" or spec.get("provider_kind") == "cli":
            if self.cli_providers is None:
                return {}
            return self.cli_providers.tool_runtime_metadata(
                str(spec.get("id") or ""),
                source_id=str(spec.get("source_id") or ""),
            )
        if spec.get("source_type") != "mcp":
            return {}
        if self.mcp_services is None:
            return {}
        return self.mcp_services.tool_runtime_metadata(
            str(spec.get("id") or ""),
            source_id=str(spec.get("source_id") or ""),
        )

    def close(self) -> None:
        try:
            self.runs.close()
        finally:
            try:
                if self.automation_scheduler is not None:
                    self.automation_scheduler.stop()
                self.attachments.close()
            finally:
                if self.mcp_services is not None:
                    self.mcp_services.close()


def build_runtime(
    config: RuntimeConfig,
    *,
    profile: str | RuntimeFeatureSet = "full",
) -> RuntimeState:
    features = profile if isinstance(profile, RuntimeFeatureSet) else RuntimeFeatureSet.from_profile(profile)
    registry = ToolRegistry()
    register_builtin_tools(registry, groups=features.tool_groups)
    settings = SettingsStore()
    cli_providers = (
        CliProviderManager(settings.data_dir / "cli-providers.json", registry=registry)
        if features.cli_providers
        else None
    )
    attachments = AttachmentStore(settings.data_dir / "attachments.db", settings.data_dir / "attachments")
    tool_tasks = TaskStore(settings.data_dir / "tool-tasks.json")
    path_guard = PathGuard(config.workspace_roots)
    backups = BackupStore(settings.data_dir / "backups", path_guard)
    runner = TaskRunner(
        registry=registry,
        store=tool_tasks,
        path_guard=path_guard,
        backup_store=backups,
        settings=settings,
        attachment_store=attachments,
    )
    workspaces = WorkspaceStore(config.workspace_roots, path_guard, settings.data_dir / "workspaces.json")
    conversations = ConversationStore(settings.data_dir / "conversations.json")
    runs = RunStore.sqlite(
        settings.data_dir / "runtime.db",
        legacy_store_path=settings.data_dir / "runs.json",
    )
    product_tasks = ProductTaskStore(settings.data_dir / "runtime.db")
    run_events = RunEventHub(runs, product_tasks=product_tasks)
    mcp_services = (
        McpServiceManager(settings.data_dir / "mcp-services.json", registry=registry)
        if features.mcp_services
        else None
    )
    automations = AutomationStore(settings.data_dir / "automations.json") if features.automations else None
    automation_scheduler = None
    capability_packs = (
        CapabilityPackStore(settings.data_dir / "capability-packs")
        if features.capability_packs
        else None
    )
    runtime = RuntimeState(
        config=config,
        features=features,
        registry=registry,
        tool_tasks=tool_tasks,
        product_tasks=product_tasks,
        runner=runner,
        workspaces=workspaces,
        conversations=conversations,
        settings=settings,
        backups=backups,
        runs=runs,
        run_events=run_events,
        mcp_services=mcp_services,
        cli_providers=cli_providers,
        attachments=attachments,
        automations=automations,
        automation_scheduler=automation_scheduler,
        capability_packs=capability_packs,
    )
    if automations is not None:
        runtime.automation_scheduler = AutomationScheduler(runtime)
    return runtime


def make_app(runtime: RuntimeState) -> tornado.web.Application:
    handler_kwargs: dict[str, Any] = {"runtime": runtime}
    static_path = Path(__file__).parent / "panel" / "static"
    template_path = Path(__file__).parent / "panel" / "templates"
    routes: list[Any] = [
        (r"/", PanelHandler),
        (r"/settings-page", PanelHandler, {"template_name": "settings.html", **handler_kwargs}),
        (r"/health", HealthHandler, handler_kwargs),
        (r"/settings", SettingsHandler, handler_kwargs),
    ]
    if runtime.features.source_updates:
        routes.append((r"/updates/source", SourceUpdateHandler, handler_kwargs))
    if runtime.features.memory_api:
        routes.extend([
            (r"/memories/prompt", MemoryPromptHandler, handler_kwargs),
            (r"/memories/([^/]+)", MemoryDetailHandler, handler_kwargs),
            (r"/memories", MemoriesHandler, handler_kwargs),
        ])
    if runtime.features.backup_api:
        routes.extend([
            (r"/backups/([^/]+)/restore", BackupRestoreHandler, handler_kwargs),
            (r"/backups", BackupsHandler, handler_kwargs),
        ])
    if runtime.features.plugins:
        routes.extend([
            (r"/plugins-page", PanelHandler, {"template_name": "plugins.html", **handler_kwargs}),
            (r"/plugins", PluginsHandler, handler_kwargs),
        ])
    if runtime.features.cli_providers:
        routes.extend([
            (r"/cli-providers/([^/]+)", CliProviderDetailHandler, handler_kwargs),
            (r"/cli-providers", CliProvidersHandler, handler_kwargs),
        ])
    if runtime.features.mcp_services:
        routes.extend([
            (r"/mcp-services-page", PanelHandler, {"template_name": "mcp-services.html", **handler_kwargs}),
            (r"/mcp-services/([^/]+)/actions", McpServiceActionHandler, handler_kwargs),
            (r"/mcp-services/([^/]+)", McpServiceDetailHandler, handler_kwargs),
            (r"/mcp-services", McpServicesHandler, handler_kwargs),
        ])
    if runtime.features.automations:
        routes.extend([
            (r"/automation-page", PanelHandler, {"template_name": "automation.html", **handler_kwargs}),
            (r"/automations/([^/]+)/actions", AutomationActionHandler, handler_kwargs),
            (r"/automations/([^/]+)", AutomationDetailHandler, handler_kwargs),
            (r"/automations", AutomationsHandler, handler_kwargs),
        ])
    if runtime.features.capability_packs:
        routes.extend([
            (r"/capability-packs/([^/]+)/actions", CapabilityPackActionHandler, handler_kwargs),
            (r"/capability-packs/([^/]+)", CapabilityPackDetailHandler, handler_kwargs),
            (r"/capability-packs", CapabilityPacksHandler, handler_kwargs),
        ])
    routes.extend([
        (r"/tools", ToolsHandler, handler_kwargs),
        (r"/attachments", AttachmentsHandler, handler_kwargs),
        (r"/attachments/([^/]+)/content", AttachmentContentHandler, handler_kwargs),
        (r"/attachments/([^/]+)", AttachmentDetailHandler, handler_kwargs),
        (r"/backend/login", BackendLoginHandler, handler_kwargs),
        (r"/workspaces/pick", WorkspacePickerHandler, handler_kwargs),
        (r"/workspaces/([^/]+)/open", WorkspaceOpenHandler, handler_kwargs),
        (r"/workspaces/([^/]+)", WorkspaceDetailHandler, handler_kwargs),
        (r"/workspaces", WorkspacesHandler, handler_kwargs),
        (r"/conversations", ConversationsHandler, handler_kwargs),
        (r"/conversations/([^/]+)", ConversationDetailHandler, handler_kwargs),
        (r"/conversations/([^/]+)/guidance", ConversationGuidanceHandler, handler_kwargs),
        (r"/conversations/([^/]+)/messages/stream", ConversationMessagesStreamHandler, handler_kwargs),
        (r"/conversations/([^/]+)/messages", ConversationMessagesHandler, handler_kwargs),
        (r"/conversations/([^/]+)/confirm", ConversationConfirmHandler, handler_kwargs),
        (r"/conversations/([^/]+)/compress", ConversationCompressHandler, handler_kwargs),
        (r"/runs/([^/]+)/events/stream", RunEventsStreamHandler, handler_kwargs),
        (r"/runs/([^/]+)/actions", RunActionHandler, handler_kwargs),
        (r"/runs/([^/]+)", RunDetailHandler, handler_kwargs),
        (r"/runs", RunsHandler, handler_kwargs),
        (r"/tasks", TasksHandler, handler_kwargs),
        (r"/tasks/([^/]+)", TaskDetailHandler, handler_kwargs),
        (r"/tool-tasks", ToolTasksHandler, handler_kwargs),
        (r"/tool-tasks/([^/]+)", ToolTaskDetailHandler, handler_kwargs),
        (r"/logs/([^/]+)", LogsWebSocketHandler, handler_kwargs),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": str(static_path)}),
    ])
    return tornado.web.Application(routes, template_path=str(template_path), static_path=str(static_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Intelligent Terminal runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="")
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        help="Allowed workspace root. Can be provided multiple times.",
    )
    parser.add_argument(
        "--profile",
        choices=("full", "lite"),
        default="full",
        help="Runtime assembly profile. full preserves the product backend; lite starts only the core runtime surface.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace_roots = args.workspace or [str(Path.cwd())]
    token = args.token or secrets.token_urlsafe(24)
    if args.port == 0:
        args.port = find_free_port(args.host)
    config = RuntimeConfig.build(args.host, args.port, token, workspace_roots)
    runtime = build_runtime(config, profile=args.profile)
    app = make_app(runtime)
    app.listen(config.port, address=config.host)
    io_loop = tornado.ioloop.IOLoop.current()
    io_loop.spawn_callback(warm_context_tokenizer)
    if runtime.mcp_services is not None:
        io_loop.spawn_callback(runtime.mcp_services.start_auto_services)
    if runtime.automation_scheduler is not None:
        io_loop.spawn_callback(runtime.automation_scheduler.start)

    print(json.dumps({
        "event": "ready",
        "url": f"http://{config.host}:{config.port}",
        "profile": runtime.features.profile,
        "workspace_roots": [str(root) for root in runtime.runner.path_guard.workspace_roots],
    }, ensure_ascii=False), flush=True)

    try:
        io_loop.start()
    except KeyboardInterrupt:
        print(json.dumps({"event": "stopped"}, ensure_ascii=False), file=sys.stderr)
    finally:
        runtime.close()


def find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    main()
